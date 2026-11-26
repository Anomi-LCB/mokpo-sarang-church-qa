from __future__ import annotations

import importlib.util
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from core.config import APP_NAME, DEFAULT_PORT

_LAUNCHER_PATH = Path(__file__).resolve().parent.parent / "packaging" / "windows" / "launcher.py"
_SPEC = importlib.util.spec_from_file_location("church_launcher", _LAUNCHER_PATH)
assert _SPEC and _SPEC.loader
_LAUNCHER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_LAUNCHER)
_is_our_server_healthy = _LAUNCHER._is_our_server_healthy
_is_port_free = _LAUNCHER._is_port_free
_pick_port_or_existing = _LAUNCHER._pick_port_or_existing


def _start_dummy_http(app_name_value: str) -> tuple[HTTPServer, int]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = json.dumps({"status": "ok", "app": app_name_value}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, port


def test_default_port_avoids_8765() -> None:
    assert DEFAULT_PORT != 8765
    assert DEFAULT_PORT == 17865


def test_launcher_rejects_foreign_app_on_loopback_and_picks_free_port() -> None:
    """Simulate Unified Office Suite listening on 127.0.0.1:P returning 200 on /api/health."""
    srv, foreign_port = _start_dummy_http("Unified Office Suite")
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


def test_launcher_recognizes_existing_church_app_instance() -> None:
    srv, our_port = _start_dummy_http(APP_NAME)
    try:
        assert _is_our_server_healthy(our_port) is True
        chosen, already_running = _pick_port_or_existing(our_port, span=5)
        assert already_running is True
        assert chosen == our_port
    finally:
        srv.shutdown()
        srv.server_close()
