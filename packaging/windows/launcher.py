from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if not getattr(sys, "frozen", False) and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("PYTHONUTF8", "1")

import pystray
from PIL import Image
import uvicorn

from core.config import APP_NAME, DEFAULT_PORT, get_base_dir, get_data_dir, get_resource_dir
from server.main import create_app


def _setup_noconsole_logging() -> None:
    """Prevent uvicorn/logging crashes when running as a --noconsole Windows .exe (stdout/stderr is None)."""
    log_path = get_data_dir() / "server.log"
    if sys.stdout is None or sys.stderr is None:
        log_f = open(log_path, "a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = log_f  # type: ignore[assignment]
        if sys.stderr is None:
            sys.stderr = log_f  # type: ignore[assignment]


def _is_port_healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1.5) as resp:
            return resp.status == 200
    except Exception:
        return False


def _is_port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def _open_app_window(url: str) -> None:
    """Open Edge or Chrome in clean frameless app mode, falling back to default browser."""
    browser_candidates = [
        shutil.which("msedge"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        shutil.which("chrome"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for b in browser_candidates:
        if b and Path(b).exists():
            try:
                subprocess.Popen([b, f"--app={url}", "--window-size=1280,860"])
                return
            except Exception:
                pass
    webbrowser.open(url)


def _load_tray_icon() -> Image.Image:
    candidates = [
        get_resource_dir() / "packaging" / "windows" / "app_icon.png",
        get_base_dir() / "app_icon.png",
        get_resource_dir() / "frontend" / "dist" / "icon-192.png",
    ]
    for p in candidates:
        if p.exists():
            try:
                return Image.open(p).convert("RGBA")
            except Exception:
                pass
    return Image.new("RGBA", (64, 64), (30, 58, 95, 255))


def _toggle_startup_shortcut() -> str:
    startup_dir = Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup"
    lnk_path = startup_dir / "목포사랑의교회 행정Q&A.vbs"
    if lnk_path.exists():
        lnk_path.unlink(missing_ok=True)
        return "removed"
    if getattr(sys, "frozen", False):
        target = f'"{sys.executable}"'
    else:
        target = f'"{sys.executable}" "{Path(__file__).resolve()}"'
    vbs = f'Set WshShell = CreateObject("WScript.Shell")\nWshShell.Run {target}, 0, False\n'
    lnk_path.write_text(vbs, encoding="utf-8")
    return "added"


def _has_startup_shortcut() -> bool:
    startup_dir = Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup"
    return (startup_dir / "목포사랑의교회 행정Q&A.vbs").exists()


def main() -> None:
    _setup_noconsole_logging()
    port = int(os.environ.get("CHURCH_SEARCH_PORT", str(DEFAULT_PORT)))

    # If already running on this port, simply open the UI window and exit cleanly
    if _is_port_healthy(port):
        if "--headless" not in sys.argv:
            _open_app_window(f"http://127.0.0.1:{port}")
        return

    if not _is_port_free(port):
        for cand in range(port + 1, port + 20):
            if _is_port_free(cand):
                port = cand
                break

    os.environ["CHURCH_SEARCH_PORT"] = str(port)
    tray_ref: dict[str, pystray.Icon | None] = {"icon": None}
    server_ref: dict[str, uvicorn.Server | None] = {"server": None}

    def _graceful_shutdown() -> None:
        srv = server_ref.get("server")
        if srv is not None:
            srv.should_exit = True
        ic = tray_ref.get("icon")
        if ic is not None:
            try:
                ic.stop()
            except Exception:
                pass

    app = create_app(port=port, on_shutdown=_graceful_shutdown)
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning", log_config=None)
    server = uvicorn.Server(config)
    server_ref["server"] = server

    def _run_server() -> None:
        try:
            server.run()
        except Exception as exc:
            import traceback
            print(f"[FATAL] Server crashed: {exc}", flush=True)
            traceback.print_exc()

    server_thread = threading.Thread(target=_run_server, daemon=True)
    server_thread.start()

    url = f"http://127.0.0.1:{port}"
    # Wait up to 8s for server readiness
    for _ in range(40):
        if _is_port_healthy(port):
            break
        time.sleep(0.2)

    if "--headless" not in sys.argv:
        _open_app_window(url)

    def on_open(icon, item):
        _open_app_window(url)

    def on_toggle_startup(icon, item):
        _toggle_startup_shortcut()
        icon.update_menu()

    def on_quit(icon, item):
        server.should_exit = True
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("목포사랑의교회 행정Q&A 열기", on_open, default=True),
        pystray.MenuItem(
            "Windows 시작 시 자동 실행",
            on_toggle_startup,
            checked=lambda item: _has_startup_shortcut(),
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("서버 완전 종료", on_quit),
    )
    tray = pystray.Icon("ChurchSearchServer", _load_tray_icon(), f"{APP_NAME} (:{port})", menu)
    tray_ref["icon"] = tray
    tray.run()


if __name__ == "__main__":
    main()
