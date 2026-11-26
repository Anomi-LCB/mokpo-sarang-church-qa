from __future__ import annotations

import asyncio
import base64
import io
import json
import secrets
from typing import Any

import qrcode
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core.config import DEFAULT_NOTEBOOK_ID
from core.database import Database
from core.std_store import StandardizationStore
from server.auth import AuthUser, PinAuthManager, _hash_secret, _verify_secret, get_client_ip, require_admin, require_user
from server.event_bus import RealtimeEventBus

router = APIRouter(prefix="/api", tags=["groups-realtime-search"])


class GroupCreateReq(BaseModel):
    name: str = Field(..., min_length=2, max_length=60)
    description: str = Field(default="", max_length=300)


class GroupJoinReq(BaseModel):
    invite_code: str = Field(..., min_length=4, max_length=24)


class GroupInviteMemberReq(BaseModel):
    owner_id: str = Field(..., min_length=1, max_length=48)
    member_label: str = Field(default="", max_length=40)


class MemberPermissionReq(BaseModel):
    can_create_group: bool


class RecoveryCodeReq(BaseModel):
    code: str = Field(..., min_length=4, max_length=32)


def _qr_data_url(text: str) -> str:
    img = qrcode.make(text)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _emit(request: Request, event_type: str, **payload: Any) -> None:
    bus: RealtimeEventBus | None = getattr(request.app.state, "events", None)
    if bus is not None:
        bus.publish(event_type, **payload)


# ---- Groups & Invitations (Unified for Group Chat + Standardization Studio) ----
@router.get("/groups")
def list_groups_route(
    request: Request,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    db: Database = request.app.state.db
    db.upsert_member(user.owner_id, user.label, user.role)
    can_create = db.can_user_create_group(user.owner_id, user.role)
    groups = db.list_groups(owner_id=user.owner_id, is_admin=(user.role == "admin"))
    me = db.get_member(user.owner_id) or {}
    # Provide safe member directory list (label + owner_id) for direct invitation by leaders/admins
    members_dir = [
        {
            "owner_id": m["owner_id"],
            "label": m["label"],
            "role": m["role"],
            "can_create_group": bool(m["can_create_group"]),
            "group_count": m.get("group_count", 0),
            "last_seen_at": m["last_seen_at"],
        }
        for m in db.list_members()
    ]
    return {
        "groups": groups,
        "can_create_group": can_create,
        "has_recovery_code": bool(me.get("recovery_code_hash")),
        "members_directory": members_dir if (user.role == "admin" or can_create or any(g.get("my_role") == "leader" for g in groups)) else [],
    }


@router.post("/groups")
def create_group_route(
    body: GroupCreateReq,
    request: Request,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    db: Database = request.app.state.db
    db.upsert_member(user.owner_id, user.label, user.role)
    if not db.can_user_create_group(user.owner_id, user.role):
        raise HTTPException(
            status_code=403,
            detail="그룹 개설 권한이 없습니다. 관리자에게 '그룹 개설 권한' 부여를 요청하세요.",
        )
    grp = db.create_group(
        name=body.name,
        description=body.description,
        creator_owner_id=user.owner_id,
        creator_label=user.label,
    )
    grp["my_role"] = "leader"
    db.log_audit("group_created", user.role, user.label, get_client_ip(request), f"그룹: {grp['name']}")
    _emit(request, "group_updated", group_id=grp["id"], actor_label=user.label)
    return grp


@router.post("/groups/join")
def join_group_by_code(
    body: GroupJoinReq,
    request: Request,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    db: Database = request.app.state.db
    db.upsert_member(user.owner_id, user.label, user.role)
    grp = db.get_group_by_invite_code(body.invite_code)
    if not grp:
        raise HTTPException(status_code=404, detail="일치하는 그룹 초대 코드를 찾을 수 없습니다.")
    updated = db.add_group_member(grp["id"], user.owner_id, user.label, role="member")
    if updated is not None:
        updated["my_role"] = db.get_group_member_role(grp["id"], user.owner_id) or "member"
    db.log_audit("group_joined", user.role, user.label, get_client_ip(request), f"초대참여: {grp['name']}")
    _emit(request, "group_updated", group_id=grp["id"], actor_label=user.label)
    return {"ok": True, "group": updated}


@router.post("/groups/{group_id}/invite")
def invite_member_to_group(
    group_id: str,
    body: GroupInviteMemberReq,
    request: Request,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    db: Database = request.app.state.db
    grp = db.get_group(group_id)
    if not grp:
        raise HTTPException(status_code=404, detail="그룹을 찾을 수 없습니다.")
    is_leader = db.get_group_member_role(group_id, user.owner_id) == "leader"
    if user.role != "admin" and not is_leader:
        raise HTTPException(status_code=403, detail="관리자 또는 해당 그룹장만 멤버를 직접 초대할 수 있습니다.")
    target_member = db.get_member(body.owner_id)
    label = body.member_label.strip() or (target_member["label"] if target_member else "교역자")
    updated = db.add_group_member(group_id, body.owner_id, label, role="member")
    db.log_audit("group_invited", user.role, user.label, get_client_ip(request), f"{grp['name']} ← {label}")
    _emit(request, "group_updated", group_id=group_id, actor_label=user.label)
    return {"ok": True, "group": updated}


@router.post("/groups/{group_id}/regenerate-code")
def regenerate_group_code(
    group_id: str,
    request: Request,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    db: Database = request.app.state.db
    grp = db.get_group(group_id)
    if not grp:
        raise HTTPException(status_code=404, detail="그룹을 찾을 수 없습니다.")
    is_leader = db.get_group_member_role(group_id, user.owner_id) == "leader"
    if user.role != "admin" and not is_leader:
        raise HTTPException(status_code=403, detail="관리자 또는 그룹장만 초대 코드를 재발급할 수 있습니다.")
    updated = db.regenerate_group_invite_code(group_id)
    _emit(request, "group_updated", group_id=group_id, actor_label=user.label)
    return {"ok": True, "group": updated}


@router.get("/groups/{group_id}/invite-qr")
def get_group_invite_qr(
    group_id: str,
    request: Request,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    db: Database = request.app.state.db
    grp = db.get_group(group_id)
    if not grp:
        raise HTTPException(status_code=404, detail="그룹을 찾을 수 없습니다.")
    if user.role != "admin" and not db.is_group_member(group_id, user.owner_id):
        raise HTTPException(status_code=403, detail="그룹 멤버만 초대 QR을 조회할 수 있습니다.")
    tunnel = getattr(request.app.state, "tunnel", None)
    custom_url = db.get_setting("custom_public_url", "") or ""
    base = ""
    if tunnel:
        summary = tunnel.get_network_summary(custom_public_url=custom_url, apk_available=False)
        base = str(summary.get("primary_external_url") or summary.get("lan_url") or "").rstrip("/")
    if not base:
        base = str(request.base_url).rstrip("/")
    join_url = f"{base}/?join={grp['invite_code']}"
    return {
        "invite_code": grp["invite_code"],
        "join_url": join_url,
        "qr_data_url": _qr_data_url(join_url),
    }


@router.delete("/groups/{group_id}/members/{member_owner_id}")
def remove_group_member_route(
    group_id: str,
    member_owner_id: str,
    request: Request,
    user: AuthUser = Depends(require_user),
) -> dict[str, bool]:
    db: Database = request.app.state.db
    grp = db.get_group(group_id)
    if not grp:
        raise HTTPException(status_code=404, detail="그룹을 찾을 수 없습니다.")
    is_leader = db.get_group_member_role(group_id, user.owner_id) == "leader"
    if user.role != "admin" and not is_leader and member_owner_id != user.owner_id:
        raise HTTPException(status_code=403, detail="본인 탈퇴 또는 관리자·그룹장만 멤버를 제외할 수 있습니다.")
    db.remove_group_member(group_id, member_owner_id)
    _emit(request, "group_updated", group_id=group_id, actor_label=user.label)
    return {"ok": True}


@router.delete("/groups/{group_id}")
def delete_group_route(
    group_id: str,
    request: Request,
    user: AuthUser = Depends(require_user),
) -> dict[str, bool]:
    db: Database = request.app.state.db
    grp = db.get_group(group_id)
    if not grp:
        raise HTTPException(status_code=404, detail="그룹을 찾을 수 없습니다.")
    is_leader = db.get_group_member_role(group_id, user.owner_id) == "leader"
    if user.role != "admin" and not is_leader:
        raise HTTPException(status_code=403, detail="관리자 또는 그룹장만 그룹을 삭제할 수 있습니다.")
    db.delete_group(group_id)
    db.log_audit("group_deleted", user.role, user.label, get_client_ip(request), f"그룹 삭제: {grp['name']}")
    _emit(request, "group_updated", group_id=group_id, actor_label=user.label)
    return {"ok": True}


def _clean_member(m: dict[str, Any]) -> dict[str, Any]:
    return {
        "owner_id": m["owner_id"],
        "label": m["label"],
        "role": m["role"],
        "can_create_group": bool(m.get("can_create_group")),
        "group_count": int(m.get("group_count") or 0),
        "last_seen_at": m.get("last_seen_at") or "",
    }


# ---- Admin Member Directory & Group Creator Grant Management ----
@router.get("/admin/members")
def list_members_admin(
    request: Request,
    _: AuthUser = Depends(require_admin),
) -> list[dict[str, Any]]:
    return [_clean_member(m) for m in request.app.state.db.list_members()]


@router.patch("/admin/members/{owner_id}/permissions")
def update_member_permissions_admin(
    owner_id: str,
    body: MemberPermissionReq,
    request: Request,
    user: AuthUser = Depends(require_admin),
) -> dict[str, Any]:
    db: Database = request.app.state.db
    updated = db.set_member_group_permission(owner_id, body.can_create_group)
    if not updated:
        raise HTTPException(status_code=404, detail="해당 사용자 기록을 찾을 수 없습니다.")
    db.log_audit(
        "member_perm_updated",
        user.role,
        user.label,
        get_client_ip(request),
        f"{updated['label']} 그룹개설권한={'부여' if body.can_create_group else '회수'}",
    )
    _emit(request, "group_updated", actor_label=user.label)
    return _clean_member(updated)


# ---- Optional Cross-Device Personal Recovery Code ----
@router.post("/auth/recovery-code")
def set_personal_recovery_code(
    body: RecoveryCodeReq,
    request: Request,
    user: AuthUser = Depends(require_user),
) -> dict[str, bool]:
    db: Database = request.app.state.db
    db.upsert_member(user.owner_id, user.label, user.role)
    code_hash = _hash_secret(body.code.strip(), secrets.token_hex(8))
    db.set_member_recovery_hash(user.owner_id, code_hash)
    return {"ok": True}


@router.post("/auth/claim-recovery")
def claim_personal_recovery_code(
    body: RecoveryCodeReq,
    request: Request,
    response: Response,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    db: Database = request.app.state.db
    auth: PinAuthManager = request.app.state.auth
    raw = body.code.strip()
    found = db.find_member_by_recovery_code(lambda h: _verify_secret(raw, h))
    if not found:
        raise HTTPException(status_code=404, detail="일치하는 개인 복구 코드를 찾을 수 없습니다.")
    merged_user = AuthUser(
        role=user.role,
        label=found.get("label") or user.label,
        owner_id=found["owner_id"],
    )
    token = auth.issue_token(merged_user)
    is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    auth.set_cookie(response, token, is_https=is_https)
    return {
        "ok": True,
        "owner_id": merged_user.owner_id,
        "label": merged_user.label,
        "role": merged_user.role,
        "token": token,
    }


# ---- Unified Quick Search (Ctrl+K Command Palette) ----
@router.get("/search/quick")
def quick_search_all(
    request: Request,
    q: str = "",
    notebook_id: str = DEFAULT_NOTEBOOK_ID,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    db: Database = request.app.state.db
    store: StandardizationStore | None = getattr(request.app.state, "std_store", None)
    needle = (q or "").strip().lower()

    docs = db.list_documents(notebook_id)
    if needle:
        docs = [
            d
            for d in docs
            if needle in d["title"].lower()
            or needle in (d.get("category") or "").lower()
            or needle in (d.get("original_filename") or "").lower()
            or any(needle in t.lower() for t in (d.get("tags") or []))
        ]

    forms = db.list_forms(notebook_id, query=q)[:15]
    sessions = db.list_sessions(notebook_id, owner_id=user.owner_id, is_admin=(user.role == "admin"), limit=40)
    if needle:
        sessions = [
            s
            for s in sessions
            if needle in (s.get("title") or "").lower() or needle in (s.get("group_name") or "").lower()
        ]

    boards: list[dict[str, Any]] = []
    if store is not None:
        gids = db.get_user_group_ids(user.owner_id)
        all_b = store.list_boards(allowed_group_ids=gids, is_admin=(user.role == "admin"))
        boards = [
            b
            for b in all_b
            if not needle
            or needle in b["title"].lower()
            or needle in b["category"].lower()
            or needle in (b.get("group_name") or "").lower()
        ][:12]

    return {
        "documents": docs[:15],
        "forms": forms[:12],
        "sessions": sessions[:12],
        "boards": boards[:12],
    }


# ---- Real-Time Live Sync SSE Stream (Group Chats + Standardization Studio) ----
@router.get("/events/stream")
async def realtime_events_stream(
    request: Request,
    _: AuthUser = Depends(require_user),
) -> StreamingResponse:
    bus: RealtimeEventBus = request.app.state.events
    queue = bus.subscribe()

    async def gen():
        try:
            yield "event: connected\ndata: {\"ok\": true}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    evt = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield f"event: {evt['type']}\ndata: {json.dumps(evt, ensure_ascii=False)}\n\n"
                except TimeoutError:
                    yield ": ping\n\n"
        finally:
            bus.unsubscribe(queue)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
