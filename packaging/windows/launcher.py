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

from core.config import APP_NAME, DEFAULT_PORT, get_base_dir, get_data_dir, get_resource_dir

APP_USER_MODEL_ID = "MokpoSarangChurch.AdminQA"


def _set_windows_app_id(app_id: str = APP_USER_MODEL_ID) -> None:
    """Register an explicit Windows AppUserModelID so Taskbar pins this .exe (never Edge)."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass


def _setup_noconsole_logging(log_name: str = "server.log") -> None:
    """Prevent uvicorn/logging crashes when running as a --noconsole Windows .exe (stdout/stderr is None)."""
    log_path = get_data_dir() / log_name
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


def _query_desktop_prefs(port: int) -> dict[str, Any]:
    """Read lightweight desktop settings (keep_tray_on_close) from the backend worker."""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}/api/internal/desktop-prefs", timeout=0.5) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {"keep_tray_on_close": False}


def _request_worker_shutdown(port: int) -> bool:
    """Ask the isolated backend engine process to checkpoint SQLite WAL and shut down cleanly."""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/internal/shutdown",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with opener.open(req, timeout=1.2) as resp:
            return resp.status == 200
    except Exception:
        return False


def _notify_existing_show_window(port: int) -> bool:
    """Restore an existing native window either directly via Win32 FindWindowW or via loopback HTTP."""
    if _activate_existing_win32_window():
        return True
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/internal/show-window",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with opener.open(req, timeout=1.5) as resp:
            if resp.status != 200:
                return False
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            return bool(isinstance(data, dict) and data.get("shown"))
    except Exception:
        return False


def _activate_existing_win32_window() -> bool:
    """Find and surface an already-running native 목포사랑의교회 행정Q&A window (even if hidden in tray)."""
    if sys.platform != "win32":
        return False
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, APP_NAME)
        if not hwnd:
            return False
        user32.ShowWindow(hwnd, 5)  # SW_SHOW (works even if hidden to tray)
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002)
        user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0001 | 0x0002)
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def _is_port_free(port: int) -> bool:
    """
    Strictly and instantaneously (<1ms) verify a port is unused on BOTH 127.0.0.1, ::1, and 0.0.0.0
    using kernel bind checks with SO_EXCLUSIVEADDRUSE.
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
    """Scan preferred_port..preferred_port+span-1 in <5ms for an existing instance or a free port."""
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
    """Dedicated persistent WebView2 profile directory (keeps local settings, 내 기본 정보, dark mode)."""
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


def _load_tray_icon():
    from PIL import Image

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
        _activate_existing_win32_window()
        return True
    except Exception:
        return False


def _patch_edgechromium_deadlock_free() -> None:
    """
    Eliminate pywebview 6.x WinForms + WebView2 GIL deadlocks (`AppHangB1` / 응답 없음):
    1. Remove pywebview's eager `AddWebResourceRequestedFilter('*', All)` + `WebResourceRequested` /
       `WebResourceResponseReceived` callbacks on the WinForms UI thread so Chromium fetches directly
       from localhost at native C++ speed with ZERO .NET->Python GIL round-trips per HTTP request.
    2. Apply `AreDefaultContextMenusEnabled = True` and `IsStatusBarEnabled = False` directly on
       the WinForms STA UI thread inside `on_webview_ready` (NEVER from a background `_on_loaded` thread!).
    """
    try:
        from webview.platforms import edgechromium as ec  # type: ignore[import-untyped]
    except Exception:
        return

    if getattr(ec.EdgeChrome, "_church_qa_patched", False):
        return

    orig_ready = ec.EdgeChrome.on_webview_ready

    def _safe_on_webview_ready(self, sender, args):
        orig_ready(self, sender, args)
        if not getattr(args, "IsSuccess", False):
            return
        try:
            core = sender.CoreWebView2
            # Detach synchronous UI-thread network interceptors (massive perf + zero GIL deadlock!)
            try:
                core.WebResourceRequested -= self.on_web_resource_request
                core.WebResourceResponseReceived -= self.on_web_resource_response
                core.RemoveWebResourceRequestedFilter("*", ec.CoreWebView2WebResourceContext.All)
            except Exception:
                pass
            # Configure native context menu cleanly ON the WinForms STA UI thread
            core.Settings.AreDefaultContextMenusEnabled = True
            core.Settings.IsStatusBarEnabled = False
        except Exception:
            pass

    ec.EdgeChrome.on_webview_ready = _safe_on_webview_ready
    ec.EdgeChrome._church_qa_patched = True


def _run_native_window(
    url: str,
    *,
    should_hide_on_close: Any,
    on_hide_to_tray: Any = None,
    shutting_down_ref: dict[str, bool],
    window_ref: dict[str, Any],
) -> bool:
    """Host the app inside a pure, isolated, deadlock-free native Windows WebView2 window."""
    try:
        import webview  # type: ignore[import-untyped]
    except Exception as exc:
        print(f"[ERROR] pywebview import failed: {exc}", flush=True)
        return False

    try:
        _patch_edgechromium_deadlock_free()
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

        def _on_closing() -> bool | None:
            if shutting_down_ref.get("flag", False):
                return True
            try:
                hide_now = bool(should_hide_on_close()) if callable(should_hide_on_close) else bool(should_hide_on_close)
            except Exception:
                hide_now = False
            if hide_now:
                if callable(on_hide_to_tray):
                    threading.Thread(target=on_hide_to_tray, daemon=True).start()
                threading.Thread(target=win.hide, daemon=True).start()
                return False
            return True

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


def _spawn_self(args: list[str], *, hidden: bool = False) -> subprocess.Popen[Any]:
    cmd = (
        [sys.executable, *args]
        if getattr(sys, "frozen", False)
        else [sys.executable, str(Path(__file__).resolve()), *args]
    )
    kwargs: dict[str, Any] = {"cwd": str(get_base_dir())}
    if hidden:
        creationflags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        kwargs.update(
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=True,
        )
    return subprocess.Popen(cmd, **kwargs)


def _spawn_window_client() -> None:
    """Spawn a fresh UI process so headless tray '열기' opens a true native window."""
    try:
        _spawn_self([], hidden=False)
    except Exception as exc:
        print(f"[ERROR] Failed to spawn native window client: {exc}", flush=True)


def _show_webview_missing_dialog(url: str) -> None:
    if sys.platform == "win32":
        try:
            ctypes.windll.user32.MessageBoxW(
                0,
                f"Windows 기본 WebView2 런타임을 불러오지 못했습니다.\n\n"
                f"로컬 엔진은 정상 실행 중입니다.\n"
                f"주소: {url}\n\n"
                f"Microsoft Edge WebView2 Runtime을 설치한 뒤 프로그램을 다시 실행해 주세요.",
                APP_NAME,
                0x30,
            )
        except Exception:
            pass


def _show_startup_failed_dialog(detail: str) -> None:
    """Never open an Edge ERR_CONNECTION_REFUSED window when the local backend failed to boot."""
    log_path = get_data_dir() / "server.log"
    msg = (
        "로컬 검색 엔진 시작 중 오류가 발생했습니다.\n\n"
        f"원인: {detail or '내부 서버가 응답하지 않았습니다.'}\n"
        f"로그 위치: {log_path}\n\n"
        "프로그램을 다시 실행해 보시고, 문제가 반복되면 최신 설치 파일로 재설치해 주세요."
    )
    print(f"[FATAL] {msg}", flush=True)
    if sys.platform == "win32":
        try:
            ctypes.windll.user32.MessageBoxW(0, msg, f"{APP_NAME} — 시작 오류", 0x10)
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


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        SYNCHRONIZE = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not handle:
            return False
        try:
            res = ctypes.windll.kernel32.WaitForSingleObject(handle, 0)
            return res == 0x00000102  # WAIT_TIMEOUT => still alive
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _run_server_worker(port: int, parent_pid: int) -> None:
    """
    Isolated backend engine process (FastAPI + Uvicorn + SQLite + Kiwi + PDF OCR).
    Runs in its OWN OS process & Python GIL so the native desktop window NEVER freezes!
    """
    _setup_noconsole_logging("server.log")
    import uvicorn
    from server.main import create_app

    os.environ["CHURCH_SEARCH_PORT"] = str(port)
    server_ref: dict[str, uvicorn.Server | None] = {"server": None}

    def _graceful_shutdown() -> None:
        srv = server_ref.get("server")
        if srv is not None:
            srv.should_exit = True

    app = create_app(port=port, on_shutdown=_graceful_shutdown)
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=port,
        log_level="warning",
        log_config=None,
        timeout_graceful_shutdown=2,
    )
    server = uvicorn.Server(config)
    server_ref["server"] = server

    # Parent-PID watchdog: if UI window exits/crashes and user did NOT opt into tray mode, exit cleanly
    if parent_pid > 0:
        def _watch_parent() -> None:
            while not server.should_exit:
                time.sleep(1.0)
                if not _is_pid_alive(parent_pid):
                    try:
                        db = getattr(app.state, "db", None)
                        keep = bool(db and db.get_setting("keep_tray_on_close", "0") == "1")
                    except Exception:
                        keep = False
                    if not keep:
                        server.should_exit = True
                    return

        threading.Thread(target=_watch_parent, daemon=True).start()

    server.run()


def _run_headless_server(port: int) -> None:
    """Headless server + system tray mode (used by Windows Startup task and automated tests)."""
    _setup_noconsole_logging("server.log")
    import pystray
    import uvicorn
    from server.main import create_app

    os.environ["CHURCH_SEARCH_PORT"] = str(port)
    tray_ref: dict[str, Any] = {"icon": None}
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
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=port,
        log_level="warning",
        log_config=None,
        timeout_graceful_shutdown=2,
    )
    server = uvicorn.Server(config)
    server_ref["server"] = server

    def _get_keep_tray() -> bool:
        try:
            db = getattr(app.state, "db", None)
            return bool(db and db.get_setting("keep_tray_on_close", "0") == "1")
        except Exception:
            return False

    def _toggle_keep_tray() -> None:
        try:
            db = getattr(app.state, "db", None)
            if db is not None:
                cur = db.get_setting("keep_tray_on_close", "0") == "1"
                db.set_setting("keep_tray_on_close", "0" if cur else "1")
        except Exception:
            pass

    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    for _ in range(100):
        if _is_our_server_healthy(port) or not server_thread.is_alive():
            break
        time.sleep(0.2)

    if not _is_our_server_healthy(port):
        server.should_exit = True
        server_thread.join(timeout=2.0)
        return

    menu = pystray.Menu(
        pystray.MenuItem("목포사랑의교회 행정Q&A 열기", lambda ic, it: _spawn_window_client(), default=True),
        pystray.MenuItem(
            "창 닫을 때 백그라운드 유지 (스마트폰 연결용)",
            lambda ic, it: (_toggle_keep_tray(), ic.update_menu()),
            checked=lambda it: _get_keep_tray(),
        ),
        pystray.MenuItem(
            "Windows 시작 시 자동 실행",
            lambda ic, it: (_toggle_startup_shortcut(), ic.update_menu()),
            checked=lambda it: _has_startup_shortcut(),
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("프로그램 완전 종료", lambda ic, it: _graceful_shutdown()),
    )
    tray = pystray.Icon("ChurchSearchServer", _load_tray_icon(), f"{APP_NAME} (:{port})", menu)
    tray_ref["icon"] = tray
    try:
        tray.run()
    finally:
        server.should_exit = True
        server_thread.join(timeout=3.0)


def _parse_flag_int(flag: str, default: int) -> int:
    if flag in sys.argv:
        idx = sys.argv.index(flag)
        if idx + 1 < len(sys.argv):
            try:
                return int(sys.argv[idx + 1])
            except ValueError:
                pass
    return default


def main() -> None:
    if "--server-worker" in sys.argv:
        w_port = _parse_flag_int("--port", int(os.environ.get("CHURCH_SEARCH_PORT", str(DEFAULT_PORT))))
        w_parent = _parse_flag_int("--parent-pid", 0)
        _run_server_worker(w_port, w_parent)
        return

    _setup_noconsole_logging("ui.log")
    _set_windows_app_id()
    headless = "--headless" in sys.argv
    preferred_port = int(os.environ.get("CHURCH_SEARCH_PORT", str(DEFAULT_PORT)))

    port, already_running = _pick_port_or_existing(preferred_port)
    if already_running:
        if headless:
            return
        if _notify_existing_show_window(port):
            return
        ok = _run_native_window(
            f"http://127.0.0.1:{port}",
            should_hide_on_close=False,
            shutting_down_ref={"flag": True},
            window_ref={"window": None},
        )
        if not ok:
            _show_webview_missing_dialog(f"http://127.0.0.1:{port}")
        return

    if headless:
        _run_headless_server(port)
        return

    # Personal Standalone Dual-Process Launch:
    # 1) Start isolated backend engine subprocess (--server-worker) with its own GIL.
    # 2) Host pure, deadlock-free native WebView2 window in this main UI process.
    worker_proc = _spawn_self(
        ["--server-worker", "--port", str(port), "--parent-pid", str(os.getpid())],
        hidden=True,
    )

    url = f"http://127.0.0.1:{port}"
    server_ready = False
    for _ in range(100):
        if _is_our_server_healthy(port):
            server_ready = True
            break
        if worker_proc.poll() is not None:
            break
        time.sleep(0.2)

    if not server_ready:
        detail = (
            f"백엔드 엔진 프로세스가 조기 종료되었습니다 (코드 {worker_proc.returncode})."
            if worker_proc.poll() is not None
            else "로컬 검색 엔진 응답 시간이 초과되었습니다."
        )
        _show_startup_failed_dialog(detail)
        if worker_proc.poll() is None:
            worker_proc.terminate()
        return

    tray_ref: dict[str, Any] = {"icon": None}
    window_ref: dict[str, Any] = {"window": None}
    shutting_down_ref: dict[str, bool] = {"flag": False}

    def _shutdown_all() -> None:
        shutting_down_ref["flag"] = True
        win = window_ref.get("window")
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass
        ic = tray_ref.get("icon")
        if ic is not None:
            try:
                ic.stop()
            except Exception:
                pass

    def _ensure_tray_running() -> None:
        """Lazily start system tray ONLY when the user opted into keep_tray_on_close."""
        if tray_ref.get("icon") is not None:
            return
        try:
            import pystray

            menu = pystray.Menu(
                pystray.MenuItem(
                    "목포사랑의교회 행정Q&A 열기",
                    lambda ic, it: _bring_window_to_front(window_ref.get("window")),
                    default=True,
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("프로그램 완전 종료", lambda ic, it: _shutdown_all()),
            )
            tray = pystray.Icon("ChurchSearchServer", _load_tray_icon(), f"{APP_NAME} (:{port})", menu)
            tray_ref["icon"] = tray
            tray.run_detached()
        except Exception as exc:
            print(f"[WARN] Tray icon init skipped: {exc}", flush=True)

    try:
        ok = _run_native_window(
            url,
            should_hide_on_close=lambda: bool(_query_desktop_prefs(port).get("keep_tray_on_close", False)),
            on_hide_to_tray=_ensure_tray_running,
            shutting_down_ref=shutting_down_ref,
            window_ref=window_ref,
        )
        if not ok:
            _show_webview_missing_dialog(url)
    finally:
        shutting_down_ref["flag"] = True
        ic = tray_ref.get("icon")
        if ic is not None:
            try:
                ic.stop()
            except Exception:
                pass
        # Cleanly checkpoint SQLite WAL and stop isolated engine worker!
        if worker_proc.poll() is None:
            _request_worker_shutdown(port)
            try:
                worker_proc.wait(timeout=4.0)
            except subprocess.TimeoutExpired:
                worker_proc.terminate()
                try:
                    worker_proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    worker_proc.kill()


if __name__ == "__main__":
    main()
