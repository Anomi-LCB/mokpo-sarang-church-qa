from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections import defaultdict
from dataclasses import dataclass

from fastapi import HTTPException, Request, Response

from core.database import Database

COOKIE_NAME = "church_search_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 14  # 14 days
TICKET_TTL_SECONDS = 120  # Short-lived file/image download ticket
DEFAULT_MEMBER_PIN = "1234"
DEFAULT_ADMIN_PIN = "0000"


@dataclass
class AuthUser:
    role: str  # "member" | "admin"
    label: str
    owner_id: str = ""


def _hash_secret(pin: str, salt: str) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return f"{salt}${dk.hex()}"


def _verify_secret(pin: str, stored: str) -> bool:
    if "$" not in stored:
        return False
    salt, expected = stored.split("$", 1)
    actual = _hash_secret(pin, salt).split("$", 1)[1]
    return hmac.compare_digest(actual, expected)


class PinAuthManager:
    def __init__(self, db: Database):
        self.db = db
        self._failed_attempts: dict[str, list[float]] = defaultdict(list)
        self._ensure_defaults()

    def _ensure_defaults(self) -> None:
        if not self.db.get_setting("auth_secret"):
            self.db.set_setting("auth_secret", secrets.token_hex(32))
        if not self.db.get_setting("token_version"):
            self.db.set_setting("token_version", "1")
        if not self.db.get_setting("pin_member_hash"):
            self.db.set_setting("pin_member_hash", _hash_secret(DEFAULT_MEMBER_PIN, secrets.token_hex(8)))
            self.db.set_setting("pin_member_is_default", "1")
        if not self.db.get_setting("pin_admin_hash"):
            self.db.set_setting("pin_admin_hash", _hash_secret(DEFAULT_ADMIN_PIN, secrets.token_hex(8)))
            self.db.set_setting("pin_admin_is_default", "1")

    @property
    def _secret(self) -> bytes:
        s = self.db.get_setting("auth_secret") or "fallback"
        return s.encode("utf-8")

    @property
    def token_version(self) -> int:
        return int(self.db.get_setting("token_version", "1") or "1")

    def is_using_default_pins(self) -> bool:
        m_hash = self.db.get_setting("pin_member_hash", "") or ""
        a_hash = self.db.get_setting("pin_admin_hash", "") or ""
        return _verify_secret(DEFAULT_MEMBER_PIN, m_hash) or _verify_secret(DEFAULT_ADMIN_PIN, a_hash)

    def _check_rate_limit(self, client_ip: str) -> None:
        now = time.time()
        recent = [t for t in self._failed_attempts[client_ip] if now - t < 60.0]
        self._failed_attempts[client_ip] = recent
        if len(recent) >= 5:
            raise HTTPException(
                status_code=429,
                detail="비밀번호/PIN 입력 오류가 반복되어 1분간 잠겼습니다. 잠시 후 다시 시도하세요.",
            )

    def authenticate_pin(self, pin: str, client_ip: str, label: str = "", client_id: str = "") -> AuthUser:
        self._check_rate_limit(client_ip)
        pin_clean = pin.strip()
        admin_hash = self.db.get_setting("pin_admin_hash", "") or ""
        member_hash = self.db.get_setting("pin_member_hash", "") or ""

        clean_cid = "".join(ch for ch in (client_id or "") if ch.isalnum() or ch in "-_")[:32]
        owner_id = clean_cid or f"usr_{secrets.token_hex(6)}"

        if _verify_secret(pin_clean, admin_hash):
            self._failed_attempts.pop(client_ip, None)
            user = AuthUser(role="admin", label=label.strip() or "관리자", owner_id=owner_id)
            self.db.log_audit("login_ok", user.role, user.label, client_ip, "관리자 로그인")
            return user
        if _verify_secret(pin_clean, member_hash):
            self._failed_attempts.pop(client_ip, None)
            user = AuthUser(role="member", label=label.strip() or "교역자/행정팀", owner_id=owner_id)
            self.db.log_audit("login_ok", user.role, user.label, client_ip, "팀원 로그인")
            return user

        self._failed_attempts[client_ip].append(time.time())
        self.db.log_audit("login_fail", "unknown", label.strip() or "-", client_ip, "잘못된 PIN/비밀번호 입력")
        raise HTTPException(status_code=401, detail="PIN 또는 비밀번호가 올바르지 않습니다.")

    def verify_admin_pin(self, pin: str | None, client_ip: str, actor_label: str = "관리자") -> None:
        """Strictly re-verify Admin PIN/password for destructive operations (e.g. deleting documents/notebooks)."""
        self._check_rate_limit(client_ip)
        pin_clean = (pin or "").strip()
        admin_hash = self.db.get_setting("pin_admin_hash", "") or ""
        if pin_clean and _verify_secret(pin_clean, admin_hash):
            self._failed_attempts.pop(client_ip, None)
            return
        self._failed_attempts[client_ip].append(time.time())
        self.db.log_audit("delete_pin_fail", "admin", actor_label, client_ip, "삭제 승인용 관리자 PIN 불일치")
        raise HTTPException(status_code=403, detail="삭제하려면 정확한 관리자 PIN/비밀번호를 입력해야 합니다.")

    def has_custom_creator_pin(self) -> bool:
        return bool(self.db.get_setting("pin_creator_hash", ""))

    def verify_creator_pin(self, pin: str | None, client_ip: str, actor_label: str = "제작자") -> None:
        """Strictly gate Creator-only feedback inbox behind Creator PIN (defaults to Admin PIN until customized)."""
        self._check_rate_limit(client_ip)
        pin_clean = (pin or "").strip()
        target_hash = self.db.get_setting("pin_creator_hash", "") or self.db.get_setting("pin_admin_hash", "") or ""
        if pin_clean and _verify_secret(pin_clean, target_hash):
            self._failed_attempts.pop(client_ip, None)
            return
        self._failed_attempts[client_ip].append(time.time())
        self.db.log_audit("creator_pin_fail", "admin", actor_label, client_ip, "제작자 제보함 암호 불일치")
        raise HTTPException(status_code=403, detail="제작자 전용 암호(기본값: 관리자 PIN)가 일치하지 않습니다.")

    def set_creator_pin(self, new_pin: str) -> None:
        p = new_pin.strip()
        if len(p) < 4 or len(p) > 32:
            raise HTTPException(status_code=400, detail="제작자 전용 암호는 4~32자리여야 합니다.")
        self.db.set_setting("pin_creator_hash", _hash_secret(p, secrets.token_hex(8)))

    def get_or_create_relay_token(self) -> str:
        tok = (self.db.get_setting("creator_relay_token", "") or "").strip()
        if not tok:
            tok = "cr_" + secrets.token_hex(16)
            self.db.set_setting("creator_relay_token", tok)
        return tok

    def verify_relay_token(self, token: str | None) -> bool:
        expected = self.get_or_create_relay_token()
        return bool(token) and hmac.compare_digest(token.strip(), expected)

    def revoke_all_sessions(self) -> int:
        new_ver = self.token_version + 1
        self.db.set_setting("token_version", str(new_ver))
        return new_ver

    def update_pins(self, member_pin: str | None = None, admin_pin: str | None = None, revoke_existing: bool = True) -> None:
        changed = False
        if member_pin is not None:
            p = member_pin.strip()
            if len(p) < 4 or len(p) > 32:
                raise HTTPException(status_code=400, detail="팀원 PIN/비밀번호는 4~32자리여야 합니다.")
            self.db.set_setting("pin_member_hash", _hash_secret(p, secrets.token_hex(8)))
            self.db.set_setting("pin_member_is_default", "1" if p == DEFAULT_MEMBER_PIN else "0")
            changed = True
        if admin_pin is not None:
            p = admin_pin.strip()
            if len(p) < 4 or len(p) > 32:
                raise HTTPException(status_code=400, detail="관리자 PIN/비밀번호는 4~32자리여야 합니다.")
            self.db.set_setting("pin_admin_hash", _hash_secret(p, secrets.token_hex(8)))
            self.db.set_setting("pin_admin_is_default", "1" if p == DEFAULT_ADMIN_PIN else "0")
            changed = True
        if changed and revoke_existing:
            self.revoke_all_sessions()

    def _sign_payload(self, payload: dict) -> str:
        raw = base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii")
        sig = hmac.new(self._secret, raw.encode("ascii"), hashlib.sha256).hexdigest()
        return f"{raw}.{sig}"

    def _verify_signed(self, token: str | None) -> dict | None:
        if not token or "." not in token:
            return None
        raw, sig = token.rsplit(".", 1)
        expected = hmac.new(self._secret, raw.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        try:
            payload = json.loads(base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8"))
        except Exception:
            return None
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        if int(payload.get("ver", 0)) != self.token_version:
            return None
        return payload

    def issue_token(self, user: AuthUser) -> str:
        return self._sign_payload(
            {
                "kind": "session",
                "ver": self.token_version,
                "role": user.role,
                "label": user.label,
                "oid": user.owner_id,
                "exp": int(time.time()) + SESSION_TTL_SECONDS,
            }
        )

    def issue_file_ticket(self, user: AuthUser, ttl_seconds: int = TICKET_TTL_SECONDS) -> str:
        """Issue a short-lived scoped ticket for GET downloads/page-images so session tokens stay out of URLs."""
        return self._sign_payload(
            {
                "kind": "ticket",
                "ver": self.token_version,
                "role": user.role,
                "label": user.label,
                "oid": user.owner_id,
                "exp": int(time.time()) + ttl_seconds,
            }
        )

    def verify_token(self, token: str | None, allow_ticket: bool = False) -> AuthUser | None:
        payload = self._verify_signed(token)
        if not payload:
            return None
        kind = payload.get("kind", "session")
        if kind == "ticket" and not allow_ticket:
            return None
        return AuthUser(
            role=str(payload.get("role", "member")),
            label=str(payload.get("label", "팀원")),
            owner_id=str(payload.get("oid", "")),
        )

    def get_user_from_request(self, request: Request) -> AuthUser | None:
        # 1. Explicit Authorization Bearer header (do not silently fall back to cookie if invalid)
        auth_hdr = request.headers.get("Authorization", "")
        if auth_hdr.lower().startswith("bearer "):
            return self.verify_token(auth_hdr[7:].strip(), allow_ticket=False)
        # 2. HttpOnly session cookie
        cookie_tok = request.cookies.get(COOKIE_NAME)
        if cookie_tok:
            u = self.verify_token(cookie_tok, allow_ticket=False)
            if u:
                return u
        # 3. Short-lived ?ticket=... ONLY on safe GET file/image download routes
        if request.method == "GET":
            ticket = request.query_params.get("ticket")
            if ticket:
                return self.verify_token(ticket, allow_ticket=True)
        return None

    def set_cookie(self, response: Response, token: str, is_https: bool = False) -> None:
        response.set_cookie(
            key=COOKIE_NAME,
            value=token,
            max_age=SESSION_TTL_SECONDS,
            httponly=True,
            samesite="lax",
            secure=is_https,
            path="/",
        )

    def clear_cookie(self, response: Response) -> None:
        response.delete_cookie(key=COOKIE_NAME, path="/")


def get_client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def require_user(request: Request) -> AuthUser:
    mgr: PinAuthManager = request.app.state.auth
    user = mgr.get_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="PIN/비밀번호 로그인이 필요합니다.")
    return user


def require_admin(request: Request) -> AuthUser:
    user = require_user(request)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다.")
    return user
