from __future__ import annotations

import base64
import io
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import quote

import qrcode
from qrcode.constants import ERROR_CORRECT_M

from core.config import get_data_dir

_TRYCF_RE = re.compile(r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com")
_TS_APPROVAL_URL_RE = re.compile(r"https://login\.tailscale\.com/[^\s\"'<>]+")
_IPV4_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")
_VIRTUAL_ADAPTER_RE = re.compile(
    r"(vethernet|wsl|hyper-v|docker|vmware|virtualbox|vbox|bluetooth|tailscale|zerotier|"
    r"loopback|teredo|isatap|hamachi|wireguard|nordlynx|openvpn|tap-windows|npcap|tunnel|pseudo)",
    re.I,
)

CLOUDFLARED_WIN64_URL = (
    "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
)


def _is_tailscale_cgnat(ip_str: str) -> bool:
    try:
        ip = ipaddress.IPv4Address(ip_str)
        return ip in ipaddress.IPv4Network("100.64.0.0/10")
    except Exception:
        return False


def _is_usable_lan_ipv4(ip_str: str) -> bool:
    try:
        ip = ipaddress.IPv4Address(ip_str)
    except Exception:
        return False
    if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        return False
    if _is_tailscale_cgnat(ip_str):
        return False
    return ip.is_private


def _detect_default_outbound_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return str(s.getsockname()[0])
    except Exception:
        return ""


def list_physical_lan_ips() -> list[dict[str, Any]]:
    """
    Enumerate real physical Wi-Fi / Ethernet IPv4 addresses on this PC,
    excluding virtual adapters (WSL, Hyper-V, Docker, Bluetooth, Tailscale VPN 100.64.0.0/10).
    """
    default_ip = _detect_default_outbound_ip()
    found: list[dict[str, Any]] = []
    seen_ips: set[str] = set()
    virtual_ips: set[str] = set()

    # Fast native Windows ipconfig parse (<25ms, zero PowerShell startup overhead)
    if os.name == "nt":
        try:
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            p = subprocess.run(
                ["ipconfig"],
                capture_output=True,
                timeout=3,
                creationflags=creationflags,
            )
            raw = p.stdout
            text = ""
            for enc in ("cp949", "utf-8", "mbcs"):
                try:
                    text = raw.decode(enc)
                    break
                except Exception:
                    continue

            cur_adapter = ""
            cur_ip = ""
            cur_has_gw = False

            def _flush() -> None:
                nonlocal cur_adapter, cur_ip, cur_has_gw
                if cur_ip:
                    if _VIRTUAL_ADAPTER_RE.search(cur_adapter) or _is_tailscale_cgnat(cur_ip):
                        virtual_ips.add(cur_ip)
                    elif cur_ip not in seen_ips and _is_usable_lan_ipv4(cur_ip):
                        seen_ips.add(cur_ip)
                        clean_lbl = re.sub(
                            r"^(이더넷 어댑터|무선 LAN 어댑터|Ethernet adapter|Wireless LAN adapter)\s*",
                            "",
                            cur_adapter,
                            flags=re.I,
                        ).strip(": ")
                        is_wifi = bool(re.search(r"(wi-fi|wifi|무선|wlan)", cur_adapter, re.I))
                        found.append(
                            {
                                "ip": cur_ip,
                                "label": clean_lbl or ("Wi-Fi" if is_wifi else "유선 LAN"),
                                "is_wifi": is_wifi,
                                "has_gateway": cur_has_gw,
                                "recommended": cur_ip == default_ip,
                            }
                        )
                cur_ip = ""
                cur_has_gw = False

            for line in text.splitlines():
                if not line.startswith(" ") and line.strip().endswith(":"):
                    _flush()
                    cur_adapter = line.strip().rstrip(":")
                    continue
                low = line.lower()
                if "ipv4" in low or "ip address" in low:
                    m = _IPV4_RE.search(line)
                    if m:
                        cur_ip = m.group(1)
                elif "기본 게이트웨이" in line or "default gateway" in low:
                    m = _IPV4_RE.search(line)
                    if m and m.group(1) != "0.0.0.0":
                        cur_has_gw = True
            _flush()
        except Exception:
            pass

    # Fallback only when ipconfig didn't populate physical NICs (or default route wasn't listed)
    if default_ip and default_ip not in seen_ips and default_ip not in virtual_ips and _is_usable_lan_ipv4(default_ip):
        seen_ips.add(default_ip)
        found.append(
            {
                "ip": default_ip,
                "label": "기본 네트워크",
                "is_wifi": False,
                "has_gateway": True,
                "recommended": True,
            }
        )

    if not found:
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                ip_s = str(info[4][0])
                if ip_s not in seen_ips and ip_s not in virtual_ips and _is_usable_lan_ipv4(ip_s):
                    seen_ips.add(ip_s)
                    found.append(
                        {
                            "ip": ip_s,
                            "label": "로컬 LAN",
                            "is_wifi": False,
                            "has_gateway": False,
                            "recommended": ip_s == default_ip,
                        }
                    )
        except Exception:
            pass

    # Rank best candidate first: default outbound route -> has gateway -> Wi-Fi / 192.168.x -> rest
    def _rank(item: dict[str, Any]) -> tuple[int, int, int, int]:
        ip_s = item["ip"]
        return (
            0 if item.get("recommended") else 1,
            0 if item.get("has_gateway") else 1,
            0 if ip_s.startswith("192.168.") else (1 if ip_s.startswith("10.") else 2),
            0 if item.get("is_wifi") else 1,
        )

    found.sort(key=_rank)
    if found and not any(x["recommended"] for x in found):
        found[0]["recommended"] = True
    return found


def get_lan_ip(preferred_ip: str = "") -> str:
    candidates = list_physical_lan_ips()
    pref = (preferred_ip or "").strip()
    if pref and any(c["ip"] == pref for c in candidates):
        return pref
    if candidates:
        return candidates[0]["ip"]
    fallback = _detect_default_outbound_ip()
    if fallback and _is_usable_lan_ipv4(fallback):
        return fallback
    return "127.0.0.1"


def make_qr_data_uri(text: str) -> str:
    """Generate ISO/IEC 18004 compliant high-contrast QR (border=4 quiet zone, M error correction) for instant phone scan."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=8,
        border=4,
    )
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#000000", back_color="#ffffff")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _run_quick(cmd: list[str], timeout: int = 5) -> tuple[int, str, str]:
    try:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=creationflags,
        )
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except Exception as exc:
        return -1, "", str(exc)


def probe_url_health(base_url: str, timeout_sec: float = 3.5) -> dict[str, Any]:
    """Actively test whether a given base URL actually reaches our /api/health endpoint."""
    clean = (base_url or "").strip().rstrip("/")
    if not clean:
        return {"ok": False, "url": "", "latency_ms": 0, "error": "주소가 비어 있습니다."}
    target = f"{clean}/api/health"
    t0 = time.perf_counter()
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(target, headers={"User-Agent": "ChurchSearchHealthCheck/1.0"})
        with opener.open(req, timeout=timeout_sec) as resp:
            ms = int((time.perf_counter() - t0) * 1000)
            body = json.loads(resp.read().decode("utf-8", errors="ignore"))
            if resp.status == 200 and isinstance(body, dict) and body.get("status") == "ok":
                return {"ok": True, "url": clean, "latency_ms": ms, "version": body.get("version", ""), "error": ""}
            return {"ok": False, "url": clean, "latency_ms": ms, "error": f"예상치 못한 응답 (HTTP {resp.status})"}
    except Exception as exc:
        ms = int((time.perf_counter() - t0) * 1000)
        return {"ok": False, "url": clean, "latency_ms": ms, "error": str(exc)[:180]}


class NetworkTunnelManager:
    def __init__(self, port: int):
        self.port = port
        self._cf_proc: subprocess.Popen[str] | None = None
        self._cf_url: str = ""
        self._cf_error: str = ""

    def _find_tailscale(self) -> str:
        found = shutil.which("tailscale")
        if found:
            return found
        cand = Path(r"C:\Program Files\Tailscale\tailscale.exe")
        return str(cand) if cand.exists() else ""

    def _find_cloudflared(self) -> str:
        found = shutil.which("cloudflared")
        if found:
            return found
        local_bin = get_data_dir() / "bin" / "cloudflared.exe"
        return str(local_bin) if local_bin.exists() else ""

    def ensure_cloudflared(self) -> tuple[str, str]:
        """Return path to cloudflared.exe, auto-downloading the official binary into data/bin/ if missing."""
        existing = self._find_cloudflared()
        if existing:
            return existing, ""
        if os.name != "nt":
            return "", "cloudflared가 설치되어 있지 않습니다."
        bin_dir = get_data_dir() / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        dst = bin_dir / "cloudflared.exe"
        tmp = bin_dir / "cloudflared.exe.tmp"
        try:
            req = urllib.request.Request(
                CLOUDFLARED_WIN64_URL,
                headers={"User-Agent": "MokpoSarangChurchQA/4.2"},
            )
            with urllib.request.urlopen(req, timeout=45) as resp, tmp.open("wb") as out_f:
                shutil.copyfileobj(resp, out_f)
            if tmp.stat().st_size < 5_000_000:
                tmp.unlink(missing_ok=True)
                return "", "cloudflared 다운로드 파일이 손상되었습니다."
            tmp.replace(dst)
            return str(dst), ""
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            return "", f"Cloudflare 터널 도구 자동 준비 실패: {exc}"

    def get_tailscale_info(self) -> dict[str, Any]:
        ts_bin = self._find_tailscale()
        if not ts_bin:
            return {
                "installed": False,
                "logged_in": False,
                "ip": "",
                "dns_name": "",
                "funnel_url": "",
                "funnel_active": False,
                "suggested_funnel_url": "",
            }

        rc, out, _ = _run_quick([ts_bin, "status", "--json"])
        ts_ip = ""
        dns_name = ""
        backend_state = ""
        if rc == 0 and out:
            try:
                data = json.loads(out)
                backend_state = str(data.get("BackendState", ""))
                self_node = data.get("Self", {})
                ips = self_node.get("TailscaleIPs", [])
                ts_ip = next((ip for ip in ips if "." in ip), "")
                dns_name = str(self_node.get("DNSName", "")).rstrip(".")
            except Exception:
                pass

        funnel_active = False
        funnel_url = ""
        funnel_wrong_port = False
        rc_f, out_f, _ = _run_quick([ts_bin, "funnel", "status"])
        if rc_f == 0 and out_f and "Funnel on" in out_f:
            if f":{self.port}" in out_f:
                funnel_active = True
                if dns_name:
                    funnel_url = f"https://{dns_name}"
            else:
                funnel_wrong_port = True

        return {
            "installed": True,
            "logged_in": backend_state == "Running" and bool(ts_ip),
            "ip": ts_ip,
            "dns_name": dns_name,
            "funnel_active": funnel_active,
            "funnel_wrong_port": funnel_wrong_port,
            "funnel_url": funnel_url,
            "suggested_funnel_url": f"https://{dns_name}" if dns_name else "",
        }

    def start_tailscale_funnel(self) -> dict[str, Any]:
        ts_bin = self._find_tailscale()
        if not ts_bin:
            return {"ok": False, "message": "Tailscale이 설치되어 있지 않습니다.", "approval_url": ""}
        rc, out, err = _run_quick([ts_bin, "funnel", "--bg", str(self.port)], timeout=14)
        combined = "\n".join(x for x in (out, err) if x)
        m_url = _TS_APPROVAL_URL_RE.search(combined)
        approval_url = m_url.group(0).rstrip(".,)") if m_url else ""
        if rc == 0:
            info = self.get_tailscale_info()
            return {
                "ok": True,
                "url": info.get("funnel_url") or info.get("suggested_funnel_url"),
                "approval_url": "",
                "message": "고정 외부 주소(Tailscale Funnel)가 켜졌습니다! 이제 어디서나 QR 하나로 접속할 수 있습니다.",
            }
        if approval_url:
            return {
                "ok": False,
                "url": "",
                "approval_url": approval_url,
                "message": "Tailscale 계정에서 외부 공개(Funnel) 1회 허용이 필요합니다. 아래 '허용 페이지 열기' 버튼을 눌러 허용한 뒤 다시 켜 주세요.",
            }
        return {
            "ok": False,
            "url": "",
            "approval_url": "",
            "message": err or out or "Tailscale 외부 공개를 켜지 못했습니다. 로그인 상태 또는 Cloudflare 즉시 열기를 확인해 주세요.",
        }

    def stop_tailscale_funnel(self) -> dict[str, Any]:
        ts_bin = self._find_tailscale()
        if not ts_bin:
            return {"ok": True, "message": "Tailscale 미설치"}
        rc, out, err = _run_quick([ts_bin, "funnel", "--https=443", "off"], timeout=10)
        if rc != 0:
            _run_quick([ts_bin, "funnel", "reset"], timeout=10)
        return {"ok": True, "message": "Tailscale 외부 공개를 껐습니다."}

    def start_cloudflare_tunnel(self, named_token: str = "", auto_download: bool = True) -> dict[str, Any]:
        self.stop_cloudflare_tunnel()
        cf_bin = self._find_cloudflared()
        if not cf_bin and auto_download:
            cf_bin, dl_err = self.ensure_cloudflared()
            if not cf_bin:
                return {"ok": False, "url": "", "message": dl_err}
        if not cf_bin:
            return {
                "ok": False,
                "url": "",
                "message": "Cloudflare 터널 도구(cloudflared)를 찾을 수 없습니다.",
            }
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if named_token.strip():
            cmd = [cf_bin, "tunnel", "run", "--token", named_token.strip()]
        else:
            cmd = [cf_bin, "tunnel", "--url", f"http://127.0.0.1:{self.port}", "--no-autoupdate"]
        self._cf_error = ""
        self._cf_url = ""
        self._cf_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )
        # Wait up to 14 seconds for quick tunnel HTTPS URL
        if not named_token.strip() and self._cf_proc.stdout:
            deadline = time.time() + 14.0
            while time.time() < deadline:
                if self._cf_proc.poll() is not None:
                    break
                line = self._cf_proc.stdout.readline()
                if not line:
                    continue
                m = _TRYCF_RE.search(line)
                if m:
                    self._cf_url = m.group(0)
                    return {
                        "ok": True,
                        "url": self._cf_url,
                        "message": "무료 외부 HTTPS 주소(Cloudflare)가 즉시 열렸습니다! 이제 QR 하나로 어디서나 접속할 수 있습니다.",
                    }
            if not self._cf_url:
                self.stop_cloudflare_tunnel()
                return {
                    "ok": False,
                    "url": "",
                    "message": "Cloudflare 외부 주소 발급 시간이 초과되었습니다. 인터넷 연결을 확인한 뒤 다시 시도해 주세요.",
                }
        return {"ok": True, "url": self._cf_url, "message": "Cloudflare 터널을 시작했습니다."}

    def stop_cloudflare_tunnel(self) -> None:
        if self._cf_proc and self._cf_proc.poll() is None:
            try:
                self._cf_proc.terminate()
                self._cf_proc.wait(timeout=4)
            except Exception:
                self._cf_proc.kill()
        self._cf_proc = None
        self._cf_url = ""

    def get_network_summary(
        self,
        custom_public_url: str = "",
        apk_available: bool = False,
        preferred_lan_ip: str = "",
    ) -> dict[str, Any]:
        lan_candidates = list_physical_lan_ips()
        lan_ip = get_lan_ip(preferred_ip=preferred_lan_ip)
        local_url = f"http://127.0.0.1:{self.port}"
        lan_url = f"http://{lan_ip}:{self.port}"
        ts = self.get_tailscale_info()
        ts_url = f"http://{ts['ip']}:{self.port}" if ts["ip"] else ""
        cf_active = bool(self._cf_proc and self._cf_proc.poll() is None and self._cf_url)

        # IMPORTANT: NEVER place private Tailscale VPN IP (100.64.0.0/10) into primary public QR!
        # General phones without Tailscale app CANNOT reach 100.x.x.x.
        public_https_url = (
            custom_public_url.strip().rstrip("/")
            or (ts.get("funnel_url", "") if ts.get("funnel_active") else "")
            or (self._cf_url if cf_active else "")
        )
        has_public_https = bool(public_https_url)
        primary_external = public_https_url or lan_url
        access_scope = "public_https" if has_public_https else "lan_only"

        apk_url = f"{primary_external}/downloads/mokpo-sarang-qa.apk" if apk_available else ""
        apk_connect_url = (
            f"churchsearch://connect?url={quote(primary_external, safe='')}&lan={quote(lan_url, safe='')}"
        )
        # Camera-universal smart connect web URL (works in BOTH iPhone & Android default camera!)
        smart_connect_url = (
            f"{primary_external}/connect?url={quote(primary_external, safe='')}&lan={quote(lan_url, safe='')}"
        )

        lan_options = [
            {
                **c,
                "url": f"http://{c['ip']}:{self.port}",
                "selected": c["ip"] == lan_ip,
            }
            for c in lan_candidates
        ]

        return {
            "port": self.port,
            "local_url": local_url,
            "lan_ip": lan_ip,
            "lan_url": lan_url,
            "lan_qr": make_qr_data_uri(lan_url),
            "lan_options": lan_options,
            "access_scope": access_scope,
            "has_public_https": has_public_https,
            "public_https_url": public_https_url,
            "tailscale": ts,
            "tailscale_url": ts_url,
            "tailscale_qr": make_qr_data_uri(ts_url) if ts_url else "",
            "cloudflare": {
                "installed": bool(self._find_cloudflared()),
                "active": cf_active,
                "url": self._cf_url if cf_active else "",
            },
            "custom_public_url": custom_public_url,
            "primary_external_url": primary_external,
            "primary_external_qr": make_qr_data_uri(primary_external),
            "apk_available": apk_available,
            "apk_url": apk_url,
            "apk_qr": make_qr_data_uri(apk_url) if apk_url else "",
            "apk_connect_url": apk_connect_url,
            "apk_connect_qr": make_qr_data_uri(apk_connect_url),
            "smart_connect_url": smart_connect_url,
            "smart_connect_qr": make_qr_data_uri(smart_connect_url),
        }
