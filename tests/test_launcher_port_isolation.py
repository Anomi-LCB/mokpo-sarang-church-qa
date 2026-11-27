from __future__ import annotations

import importlib.util
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from fastapi.testclient import TestClient

from core.config import APP_NAME, DEFAULT_PORT
from server.main import create_app

_LAUNCHER_PATH = Path(__file__).resolve().parent.parent / "packaging" / "windows" / "launcher.py"
_SPEC = importlib.util.spec_from_file_location("church_launcher", _LAUNCHER_PATH)
assert _SPEC and _SPEC.loader
_LAUNCHER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_LAUNCHER)
_is_our_server_healthy = _LAUNCHER._is_our_server_healthy
_is_port_free = _LAUNCHER._is_port_free
_pick_port_or_existing = _LAUNCHER._pick_port_or_existing
_notify_existing_show_window = _LAUNCHER._notify_existing_show_window
APP_USER_MODEL_ID = _LAUNCHER.APP_USER_MODEL_ID


def _start_dummy_http(app_name_value: str, *, show_window_result: bool = True) -> tuple[HTTPServer, int, list[bool]]:
    show_calls: list[bool] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = json.dumps({"status": "ok", "app": app_name_value}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            if self.path == "/api/internal/show-window":
                show_calls.append(True)
                body = json.dumps({"ok": True, "shown": show_window_result}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.end_headers()

        def log_message(self, format: str, *args) -> None:
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, port, show_calls


def test_default_port_avoids_8765() -> None:
    assert DEFAULT_PORT != 8765
    assert DEFAULT_PORT == 17865


def test_launcher_uses_native_webview_and_explicit_app_id() -> None:
    src = _LAUNCHER_PATH.read_text(encoding="utf-8")
    assert APP_USER_MODEL_ID == "MokpoSarangChurch.AdminQA"
    assert "SetCurrentProcessExplicitAppUserModelID" in src
    assert "webview.create_window" in src
    # Must never spawn external Edge/Chrome browser windows or webbrowser.open on launch
    assert "msedge.exe" not in src
    assert "webbrowser.open" not in src


def test_launcher_rejects_foreign_app_on_loopback_and_picks_free_port() -> None:
    """Simulate Unified Office Suite listening on 127.0.0.1:P returning 200 on /api/health."""
    srv, foreign_port, _ = _start_dummy_http("Unified Office Suite")
    try:
        # Must NOT mistake foreign app for our church app
        assert _is_our_server_healthy(foreign_port) is False
        # Must detect foreign loopback listener as NOT free (no Windows 0.0.0.0 dual-bind trap!)
        assert _is_port_free(foreign_port) is False
        # Must skip foreign_port and choose a truly free port instantaneously (< 1.0s)
        t0 = time.perf_counter()
        chosen, already_running = _pick_port_or_existing(foreign_port, span=10)
        elapsed = time.perf_counter() - t0
        assert already_running is False
        assert chosen != foreign_port
        assert _is_port_free(chosen) is True
        assert elapsed < 1.0, f"Port scan too slow: {elapsed:.2f}s"
    finally:
        srv.shutdown()
        srv.server_close()


def test_launcher_recognizes_existing_church_app_instance_and_restores_window() -> None:
    srv, our_port, show_calls = _start_dummy_http(APP_NAME, show_window_result=True)
    try:
        assert _is_our_server_healthy(our_port) is True
        chosen, already_running = _pick_port_or_existing(our_port, span=5)
        assert already_running is True
        assert chosen == our_port
        assert _notify_existing_show_window(our_port) is True
        assert len(show_calls) == 1
    finally:
        srv.shutdown()
        srv.server_close()


def test_launcher_detects_headless_instance_requiring_new_native_window() -> None:
    srv, our_port, show_calls = _start_dummy_http(APP_NAME, show_window_result=False)
    try:
        assert _notify_existing_show_window(our_port) is False
        assert len(show_calls) == 1
    finally:
        srv.shutdown()
        srv.server_close()


def test_internal_show_window_endpoint_invokes_callback(tmp_path: Path) -> None:
    called: list[bool] = []
    app = create_app(db_path=tmp_path / "show_win.db", on_show_window=lambda: (called.append(True) or True))
    with TestClient(app, client=("127.0.0.1", 54321)) as client:
        res = client.post("/api/internal/show-window")
        assert res.status_code == 200
        assert res.json() == {"ok": True, "shown": True}
        assert len(called) == 1

    # Non-loopback client must be forbidden
    with TestClient(app, client=("192.168.0.55", 54321)) as remote_client:
        res_remote = remote_client.post("/api/internal/show-window")
        assert res_remote.status_code == 403

    # Headless app (no callback) returns shown=False cleanly
    app_headless = create_app(db_path=tmp_path / "headless.db", on_show_window=None)
    with TestClient(app_headless, client=("127.0.0.1", 54321)) as client_hl:
        res_hl = client_hl.post("/api/internal/show-window")
        assert res_hl.status_code == 200
        assert res_hl.json() == {"ok": True, "shown": False}
