from __future__ import annotations

import base64
import io
import json
import re
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import quote

import qrcode

from core.config import get_data_dir

_TRYCF_RE = re.compile(r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com")


def get_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return str(s.getsockname()[0])
    except Exception:
        return "127.0.0.1"


def make_qr_data_uri(text: str) -> str:
    qr = qrcode.QRCode(version=1, box_size=6, border=2)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0f172a", back_color="#ffffff")
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

    def get_tailscale_info(self) -> dict[str, Any]:
        ts_bin = self._find_tailscale()
        if not ts_bin:
            return {"installed": False, "ip": "", "dns_name": "", "funnel_url": "", "funnel_active": False}

        rc, out, _ = _run_quick([ts_bin, "status", "--json"])
        ts_ip = ""
        dns_name = ""
        if rc == 0 and out:
            try:
                data = json.loads(out)
                self_node = data.get("Self", {})
                ips = self_node.get("TailscaleIPs", [])
                ts_ip = next((ip for ip in ips if "." in ip), "")
                dns_name = str(self_node.get("DNSName", "")).rstrip(".")
            except Exception:
                pass

        funnel_active = False
        funnel_url = ""
        rc_f, out_f, _ = _run_quick([ts_bin, "funnel", "status"])
        if rc_f == 0 and out_f and f":{self.port}" in out_f and "Funnel on" in out_f:
            funnel_active = True
            if dns_name:
                funnel_url = f"https://{dns_name}"

        return {
            "installed": True,
            "ip": ts_ip,
            "dns_name": dns_name,
            "funnel_active": funnel_active,
            "funnel_url": funnel_url,
            "suggested_funnel_url": f"https://{dns_name}" if dns_name else "",
        }

    def start_tailscale_funnel(self) -> dict[str, Any]:
        ts_bin = self._find_tailscale()
        if not ts_bin:
            return {"ok": False, "message": "Tailscale이 설치되어 있지 않습니다."}
        rc, out, err = _run_quick([ts_bin, "funnel", "--bg", str(self.port)], timeout=12)
        if rc == 0:
            info = self.get_tailscale_info()
            return {"ok": True, "url": info.get("funnel_url") or info.get("suggested_funnel_url"), "message": out or "Tailscale Funnel이 활성화되었습니다."}
        return {
            "ok": False,
            "message": err or out or "Tailscale Funnel 활성화에 실패했습니다. Tailscale 관리자 페이지에서 Funnel 권한을 1회 켜주세요.",
        }

    def stop_tailscale_funnel(self) -> dict[str, Any]:
        ts_bin = self._find_tailscale()
        if not ts_bin:
            return {"ok": True, "message": "Tailscale 미설치"}
        rc, out, err = _run_quick([ts_bin, "funnel", "--https=443", "off"], timeout=10)
        if rc != 0:
            _run_quick([ts_bin, "funnel", "reset"], timeout=10)
        return {"ok": True, "message": out or err or "Tailscale Funnel이 중지되었습니다."}

    def start_cloudflare_tunnel(self, named_token: str = "") -> dict[str, Any]:
        self.stop_cloudflare_tunnel()
        cf_bin = self._find_cloudflared()
        if not cf_bin:
            return {
                "ok": False,
                "message": "cloudflared.exe가 설치되어 있지 않습니다. (winget install Cloudflare.cloudflared 로 설치하거나 Tailscale Funnel을 사용하세요.)",
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
        # Wait up to 8 seconds for quick tunnel URL
        if not named_token.strip() and self._cf_proc.stdout:
            import time
            deadline = time.time() + 8.0
            while time.time() < deadline:
                if self._cf_proc.poll() is not None:
                    break
                line = self._cf_proc.stdout.readline()
                if not line:
                    continue
                m = _TRYCF_RE.search(line)
                if m:
                    self._cf_url = m.group(0)
                    return {"ok": True, "url": self._cf_url, "message": "Cloudflare 외부 터널이 연결되었습니다."}
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

    def get_network_summary(self, custom_public_url: str = "", apk_available: bool = False) -> dict[str, Any]:
        lan_ip = get_lan_ip()
        local_url = f"http://127.0.0.1:{self.port}"
        lan_url = f"http://{lan_ip}:{self.port}"
        ts = self.get_tailscale_info()
        ts_url = f"http://{ts['ip']}:{self.port}" if ts["ip"] else ""
        cf_active = bool(self._cf_proc and self._cf_proc.poll() is None)

        primary_external = (
            custom_public_url.strip().rstrip("/")
            or ts.get("funnel_url", "")
            or (self._cf_url if cf_active else "")
            or ts_url
            or lan_url
        )

        apk_url = f"{primary_external}/downloads/church-search.apk" if apk_available else ""
        apk_connect_url = (
            f"churchsearch://connect?url={quote(primary_external, safe='')}&lan={quote(lan_url, safe='')}"
        )

        return {
            "port": self.port,
            "local_url": local_url,
            "lan_url": lan_url,
            "lan_qr": make_qr_data_uri(lan_url),
            "tailscale": ts,
            "tailscale_url": ts_url,
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
        }
