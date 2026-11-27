from __future__ import annotations

import ctypes
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
if not getattr(sys, "frozen", False) and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("PYTHONUTF8", "1")

import pystray
from PIL import Image
import uvicorn

from core.config import APP_NAME, DEFAULT_PORT, get_base_dir, get_data_dir, get_resource_dir
from server.main import create_app

APP_USER_MODEL_ID = "MokpoSarangChurch.AdminQA"


def _set_windows_app_id(app_id: str = APP_USER_MODEL_ID) -> None:
    """Register an explicit Windows AppUserModelID so Taskbar pins this .exe (never Edge)."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass


def _setup_noconsole_logging() -> None:
    """Prevent uvicorn/logging crashes when running as a --noconsole Windows .exe (stdout/stderr is None)."""
    log_path = get_data_dir() / "server.log"
    if sys.stdout is None or sys.stderr is None:
        log_f = open(log_path, "a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = log_f  # type: ignore[assignment]
        if sys.stderr is None:
            sys.stderr = log_f  # type: ignore[assignment]


def _is_our_server_healthy(port: int) -> bool:
    """Return True ONLY when *our* 목포사랑의교회 행정Q&A server is responding on `port`."""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}/api/health", timeout=0.6) as resp:
            if resp.status != 200:
                return False
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            return isinstance(data, dict) and data.get("app") == APP_NAME
    except Exception:
        return False


def _notify_existing_show_window(port: int) -> bool:
    """Ask the running primary instance to surface its native desktop window.

    Returns True if an existing native window was restored/focused; False if the
    running instance is headless (no GUI window yet) or unreachable.
    """
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/internal/show-window",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with opener.open(req, timeout=2.0) as resp:
            if resp.status != 200:
                return False
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            return bool(isinstance(data, dict) and data.get("shown"))
    except Exception:
        return False


def _is_port_free(port: int) -> bool:
    """
    Strictly and instantaneously (<1ms) verify a port is unused on BOTH 127.0.0.1, ::1, and 0.0.0.0
    using kernel bind checks with SO_EXCLUSIVEADDRUSE.
    Prevents BOTH:
      1. Windows Winsock dual-bind trap (0.0.0.0 succeeding while another app holds 127.0.0.1), and
      2. Multi-second Windows TCP loopback SYN-RST connect delays on closed ports.
    """
    for family, host in (
        (socket.AF_INET, "127.0.0.1"),
        (socket.AF_INET, "0.0.0.0"),
    ):
        with socket.socket(family, socket.SOCK_STREAM) as s:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                try:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                except OSError:
                    pass
            try:
                s.bind((host, port))
            except OSError:
                return False

    if socket.has_ipv6:
        try:
            with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as s6:
                if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    try:
                        s6.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                    except OSError:
                        pass
                try:
                    s6.bind(("::1", port))
                except OSError:
                    return False
        except OSError:
            pass

    return True


def _pick_port_or_existing(preferred_port: int, span: int = 25) -> tuple[int, bool]:
    """
    Scan preferred_port .. preferred_port+span-1 in <5ms:
    - Only probe /api/health on ports that are ACTUALLY occupied (instant kernel bind check).
    - If our own 목포사랑의교회 행정Q&A server is already healthy on an occupied port, return (port, True).
    - Otherwise return the first strictly free port (port, False).
    """
    first_free: int | None = None
    for cand in range(preferred_port, preferred_port + span):
        if _is_port_free(cand):
            if first_free is None:
                first_free = cand
        else:
            if _is_our_server_healthy(cand):
                return cand, True

    if first_free is not None:
        return first_free, False

    raise RuntimeError(f"사용 가능한 포트를 찾을 수 없습니다 ({preferred_port}~{preferred_port + span - 1}).")


def _get_webview_storage_dir() -> Path:
    """Dedicated persistent WebView2 profile directory (keeps login, 내 기본 정보, dark mode, offline DB)."""
    local_app = os.environ.get("LOCALAPPDATA")
    if local_app:
        prof = Path(local_app) / "MokpoSarangChurchQA" / "webview2_profile"
    else:
        prof = get_data_dir() / "webview2_profile"
    prof.mkdir(parents=True, exist_ok=True)
    return prof


def _find_app_icon_ico() -> Path | None:
    candidates = [
        get_resource_dir() / "packaging" / "windows" / "app_icon.ico",
        get_base_dir() / "app_icon.ico",
        ROOT / "packaging" / "windows" / "app_icon.ico",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


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


def _bring_window_to_front(win: Any) -> bool:
    """Restore and focus the native pywebview window cleanly from any thread."""
    if win is None:
        return False
    try:
        win.show()
        try:
            win.restore()
        except Exception:
            pass
        native = getattr(win, "native", None)
        if native is not None and sys.platform == "win32":
            try:
                hwnd = int(native.Handle.ToInt64())
                user32 = ctypes.windll.user32
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002)  # HWND_TOPMOST
                user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0001 | 0x0002)  # HWND_NOTOPMOST
                user32.SetForegroundWindow(hwnd)
            except Exception:
                pass
        return True
    except Exception:
        return False


def _run_native_window(
    url: str,
    *,
    hide_on_close: bool,
    shutting_down_ref: dict[str, bool],
    window_ref: dict[str, Any],
) -> bool:
    """Host the app inside a true native Windows WebView2 window owned by this .exe.

    - Never launches external Edge/Chrome browser windows or restores prior web tabs.
    - Pinning the running taskbar icon pins 목포사랑의교회 행정Q&A.exe directly.
    - Returns True if the native window ran and exited cleanly, False if WebView2 failed to start.
    """
    try:
        import webview  # type: ignore[import-untyped]
    except Exception as exc:
        print(f"[ERROR] pywebview import failed: {exc}", flush=True)
        return False

    try:
        webview.settings["ALLOW_DOWNLOADS"] = True
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True

        win = webview.create_window(
            APP_NAME,
            url=url,
            width=1320,
            height=860,
            min_size=(420, 560),
            text_select=True,
            zoomable=True,
            background_color="#FFFFFF",
        )
        window_ref["window"] = win

        def _on_loaded() -> None:
            try:
                native = getattr(win, "native", None)
                wv = getattr(native, "webview", None) if native is not None else None
                core = getattr(wv, "CoreWebView2", None) if wv is not None else None
                if core is not None:
                    # Enable native copy/paste context menu inside the desktop window
                    core.Settings.AreDefaultContextMenusEnabled = True
                    core.Settings.IsStatusBarEnabled = False
            except Exception:
                pass

        def _on_closing() -> bool | None:
            if hide_on_close and not shutting_down_ref.get("flag", False):
                # Hide asynchronously after FormClosing cancels cleanly; server & tray stay alive
                threading.Thread(target=win.hide, daemon=True).start()
                return False
            return True

        win.events.loaded += _on_loaded
        win.events.closing += _on_closing

        icon_ico = _find_app_icon_ico()
        start_kwargs: dict[str, Any] = {
            "gui": "edgechromium",
            "private_mode": False,
            "storage_path": str(_get_webview_storage_dir()),
        }
        if icon_ico is not None:
            start_kwargs["icon"] = str(icon_ico)

        webview.start(**start_kwargs)
        return True
    except Exception as exc:
        print(f"[ERROR] Native WebView2 window failed: {exc}", flush=True)
        return False
    finally:
        window_ref["window"] = None


def _spawn_window_client() -> None:
    """Spawn a fresh process of ourselves so headless tray '열기' opens a true native window."""
    try:
        if getattr(sys, "frozen", False):
            subprocess.Popen([sys.executable])
        else:
            subprocess.Popen([sys.executable, str(Path(__file__).resolve())])
    except Exception as exc:
        print(f"[ERROR] Failed to spawn native window client: {exc}", flush=True)


def _show_webview_missing_dialog(url: str) -> None:
    """If an old PC lacks Windows WebView2 Runtime, inform the user clearly instead of hijacking Edge tabs."""
    if sys.platform == "win32":
        try:
            ctypes.windll.user32.MessageBoxW(
                0,
                f"Windows 기본 WebView2 런타임을 불러오지 못했습니다.\n\n"
                f"서버는 백그라운드에서 정상 실행 중입니다.\n"
                f"주소: {url}\n\n"
                f"Microsoft Edge WebView2 Runtime을 설치한 뒤 프로그램을 다시 실행해 주세요.",
                APP_NAME,
                0x30,
            )
        except Exception:
            pass


def _toggle_startup_shortcut() -> str:
    startup_dir = Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup"
    lnk_path = startup_dir / "목포사랑의교회 행정Q&A.vbs"
    if lnk_path.exists():
        lnk_path.unlink(missing_ok=True)
        return "removed"
    if getattr(sys, "frozen", False):
        vbs_cmd = f'"""{sys.executable}"" --headless"'
    else:
        vbs_cmd = f'"""{sys.executable}"" ""{Path(__file__).resolve()}"" --headless"'
    vbs = f'Set WshShell = CreateObject("WScript.Shell")\nWshShell.Run {vbs_cmd}, 0, False\n'
    lnk_path.write_text(vbs, encoding="utf-8")
    return "added"


def _has_startup_shortcut() -> bool:
    startup_dir = Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup"
    return (startup_dir / "목포사랑의교회 행정Q&A.vbs").exists()


def main() -> None:
    _setup_noconsole_logging()
    _set_windows_app_id()
    headless = "--headless" in sys.argv
    preferred_port = int(os.environ.get("CHURCH_SEARCH_PORT", str(DEFAULT_PORT)))

    # If our own app is already running:
    # 1) Ask the primary instance to bring its native desktop window to front.
    # 2) If the primary instance is running --headless (no GUI window yet), open our own native window for it.
    port, already_running = _pick_port_or_existing(preferred_port)
    if already_running:
        if headless:
            return
        if _notify_existing_show_window(port):
            return
        ok = _run_native_window(
            f"http://127.0.0.1:{port}",
            hide_on_close=False,
            shutting_down_ref={"flag": True},
            window_ref={"window": None},
        )
        if not ok:
            _show_webview_missing_dialog(f"http://127.0.0.1:{port}")
        return

    os.environ["CHURCH_SEARCH_PORT"] = str(port)
    tray_ref: dict[str, pystray.Icon | None] = {"icon": None}
    server_ref: dict[str, uvicorn.Server | None] = {"server": None}
    window_ref: dict[str, Any] = {"window": None}
    shutting_down_ref: dict[str, bool] = {"flag": False}

    def _show_native_window() -> bool:
        win = window_ref.get("window")
        if win is not None:
            return _bring_window_to_front(win)
        return False

    def _graceful_shutdown() -> None:
        shutting_down_ref["flag"] = True
        win = window_ref.get("window")
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass
        srv = server_ref.get("server")
        if srv is not None:
            srv.should_exit = True
        ic = tray_ref.get("icon")
        if ic is not None:
            try:
                ic.stop()
            except Exception:
                pass

    app = create_app(
        port=port,
        on_shutdown=_graceful_shutdown,
        on_show_window=_show_native_window if not headless else None,
    )
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
    # Wait up to 10s for *our* server readiness before creating the native window
    for _ in range(50):
        if _is_our_server_healthy(port):
            break
        time.sleep(0.2)

    def on_open(icon, item):
        if not _show_native_window():
            _spawn_window_client()

    def on_toggle_startup(icon, item):
        _toggle_startup_shortcut()
        icon.update_menu()

    def on_quit(icon, item):
        _graceful_shutdown()

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

    if headless:
        tray.run()
        return

    # Normal launch: tray runs in background thread, native WebView2 window owns the main thread
    tray.run_detached()
    try:
        ok = _run_native_window(
            url,
            hide_on_close=True,
            shutting_down_ref=shutting_down_ref,
            window_ref=window_ref,
        )
        if not ok:
            _show_webview_missing_dialog(url)
            # Keep background server + tray alive until user exits via tray
            while not shutting_down_ref.get("flag", False) and server_thread.is_alive():
                time.sleep(0.5)
    finally:
        shutting_down_ref["flag"] = True
        server.should_exit = True
        try:
            tray.stop()
        except Exception:
            pass


if __name__ == "__main__":
    main()
