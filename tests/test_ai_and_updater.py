from __future__ import annotations

import hashlib
import io
import json
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from fastapi.testclient import TestClient

from server.ai_secrets import decrypt_secret, encrypt_secret, mask_secret
from server.main import create_app
from server.updater import is_newer_version, parse_version, validate_and_extract_patch_zip


def _start_mock_http_server(routes: dict[str, tuple[int, str, bytes]]):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def _handle(self):
            path = self.path.split("?", 1)[0]
            if path in routes:
                status, ctype, body = routes[path]
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def do_GET(self):
            self._handle()

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length > 0:
                self.rfile.read(length)
            self._handle()

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, f"http://127.0.0.1:{port}"


def _make_patch_zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_dpapi_secret_roundtrip_and_mask():
    raw = "demo-key-placeholder-value-9876"
    enc = encrypt_secret(raw)
    assert enc != raw
    assert enc.startswith(("dpapi:", "obf:"))
    assert decrypt_secret(enc) == raw
    masked = mask_secret(raw)
    assert masked.startswith("demo-k")
    assert masked.endswith("9876")
    assert "placeholder" not in masked


def test_installer_seed_import_and_cli_api_streaming(tmp_path: Path):
    db_path = tmp_path / "church_search.db"
    # Simulate Windows Installer writing initial_ai_config.json on first boot
    seed = tmp_path / "initial_ai_config.json"
    seed.write_text(
        json.dumps(
            {
                "ai_connection_mode": "api",
                "ai_api_provider": "anthropic",
                "ai_api_key": "demo-installer-seed-key-4321",
                "ai_api_model": "claude-sonnet-4-5",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    sse_openai = (
        'data: {"choices":[{"delta":{"content":"OK "}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"테스트 응답 완료 [목포사랑의교회 정관] 제1조 p.1"}}]}\n\n'
        "data: [DONE]\n\n"
    ).encode("utf-8")
    srv, base_url = _start_mock_http_server(
        {
            "/v1/chat/completions": (200, "text/event-stream; charset=utf-8", sse_openai),
        }
    )

    try:
        app = create_app(db_path=db_path)
        with TestClient(app) as client:
            # Plaintext installer seed MUST be deleted immediately on startup
            assert not seed.exists()

            # Admin login
            r_login = client.post("/api/auth/login", json={"pin": "0000", "label": "관리자"})
            assert r_login.status_code == 200

            # Raw DB value must be encrypted, NOT plaintext
            raw_stored = app.state.db.get_setting("ai_api_key_anthropic", "")
            assert raw_stored.startswith(("dpapi:", "obf:"))
            assert "demo-installer-seed" not in raw_stored

            # GET /api/admin/cli must never leak plaintext key
            r_cfg = client.get("/api/admin/cli")
            assert r_cfg.status_code == 200
            cfg_data = r_cfg.json()
            assert cfg_data["connection_mode"] == "api"
            assert cfg_data["api_provider"] == "anthropic"
            assert "demo-installer-seed" not in r_cfg.text
            ant = next(a for a in cfg_data["api_providers"] if a["id"] == "anthropic")
            assert ant["has_key"] is True
            assert ant["key_masked"].endswith("4321")

            # Switch to openai_compatible pointing to our local mock SSE server
            r_put = client.put(
                "/api/admin/cli",
                json={
                    "connection_mode": "api",
                    "provider": "claude",
                    "model": "",
                    "api_provider": "openai_compatible",
                    "api_model": "local-test-model",
                    "api_base_url": f"{base_url}/v1",
                    "api_key": "local-key-1234",
                    "max_concurrent": 2,
                    "custom_public_url": "",
                    "cli_failover_enabled": True,
                    "default_double_verify": False,
                    "default_chat_shared": False,
                    "audit_log_enabled": True,
                },
            )
            assert r_put.status_code == 200

            # Live connection test against mock API
            r_test = client.post(
                "/api/admin/ai/test",
                json={"mode": "api", "provider": "openai_compatible"},
            )
            assert r_test.status_code == 200
            td = r_test.json()
            assert td["ok"] is True
            assert "OK" in td["reply_preview"]
            assert td["model"] == "local-test-model"

            # Verify key clearing works cleanly
            r_clr = client.put(
                "/api/admin/cli",
                json={
                    "connection_mode": "api",
                    "provider": "claude",
                    "model": "",
                    "api_provider": "anthropic",
                    "api_model": "",
                    "api_base_url": "",
                    "clear_api_key": True,
                    "max_concurrent": 2,
                    "custom_public_url": "",
                    "cli_failover_enabled": True,
                    "default_double_verify": False,
                    "default_chat_shared": False,
                    "audit_log_enabled": True,
                },
            )
            assert r_clr.status_code == 200
            ant_after = next(a for a in client.get("/api/admin/cli").json()["api_providers"] if a["id"] == "anthropic")
            assert ant_after["key_source"] != "saved"
    finally:
        srv.shutdown()


def test_opt_in_updater_check_skip_sha256_zip_safety_and_apply(tmp_path: Path):
    assert parse_version("v2.4.0") == (2, 4, 0)
    assert is_newer_version("9.9.9", "2.4.0") is True
    assert is_newer_version("2.4.0", "2.4.0") is False
    assert is_newer_version("2.3.9", "2.4.0") is False

    # Build a valid lean Windows update patch ZIP (no data/ folder)
    valid_zip = _make_patch_zip_bytes(
        {
            "update-manifest.json": json.dumps({"version": "9.9.9"}).encode("utf-8"),
            "목포사랑의교회 행정Q&A.exe": b"MZ_FAKE_EXE_FOR_TEST",
            "_internal/app_marker.txt": b"v9.9.9",
        }
    )
    good_sha = hashlib.sha256(valid_zip).hexdigest()

    # Build a malicious ZIP trying to overwrite data/church_search.db
    evil_zip = _make_patch_zip_bytes(
        {
            "목포사랑의교회 행정Q&A.exe": b"MZ",
            "data/church_search.db": b"EVIL_OVERWRITE",
        }
    )

    manifest_good = json.dumps(
        {
            "version": "9.9.9",
            "published_at": "2026-11-26T13:00:00+09:00",
            "title": "목포사랑의교회 행정Q&A v9.9.9",
            "notes_md": "### 주요 업데이트\n- CLI/API 선택 지원\n- 안전 자동 업데이트",
            "assets": {
                "win_patch_zip": {
                    "name": "patch-v9.9.9.zip",
                    "url": "",  # filled once port is bound
                    "sha256": good_sha,
                    "size_bytes": len(valid_zip),
                }
            },
        },
        ensure_ascii=False,
    )

    routes: dict[str, tuple[int, str, bytes]] = {
        "/patch-v9.9.9.zip": (200, "application/zip", valid_zip),
    }
    srv, base_url = _start_mock_http_server(routes)
    manifest_obj = json.loads(manifest_good)
    manifest_obj["assets"]["win_patch_zip"]["url"] = f"{base_url}/patch-v9.9.9.zip"
    routes["/manifest.json"] = (200, "application/json", json.dumps(manifest_obj, ensure_ascii=False).encode("utf-8"))

    bad_manifest = json.loads(json.dumps(manifest_obj))
    bad_manifest["assets"]["win_patch_zip"]["sha256"] = "0" * 64
    routes["/bad-manifest.json"] = (200, "application/json", json.dumps(bad_manifest, ensure_ascii=False).encode("utf-8"))

    try:
        db_path = tmp_path / "church_search.db"
        app = create_app(db_path=db_path)
        with TestClient(app) as client:
            assert client.post("/api/auth/login", json={"pin": "0000", "label": "관리자"}).status_code == 200

            # 1. Point update feed to mock manifest
            r_set = client.put(
                "/api/updates/settings",
                json={"channel": "custom", "custom_url": f"{base_url}/manifest.json", "auto_check": True},
            )
            assert r_set.status_code == 200

            r_chk = client.get("/api/updates/check?force=1")
            assert r_chk.status_code == 200
            chk = r_chk.json()
            assert chk["ok"] is True
            assert chk["update_available"] is True
            assert chk["should_notify"] is True
            assert chk["latest"]["version"] == "9.9.9"
            assert "CLI/API 선택 지원" in chk["latest"]["notes_md"]

            # 2. User skips this version -> should_notify becomes False
            r_skip = client.post("/api/updates/skip", json={"version": "9.9.9"})
            assert r_skip.status_code == 200
            chk2 = client.get("/api/updates/check").json()
            assert chk2["update_available"] is True
            assert chk2["is_skipped"] is True
            assert chk2["should_notify"] is False

            # 3. Malicious offline patch touching data/ MUST be rejected with 400
            r_evil = client.post(
                "/api/updates/upload-patch",
                files={"file": ("evil.zip", evil_zip, "application/zip")},
            )
            assert r_evil.status_code == 400
            assert "data/" in r_evil.json()["detail"]

            # 4. SHA-256 mismatch MUST fail cleanly
            client.put("/api/updates/settings", json={"channel": "custom", "custom_url": f"{base_url}/bad-manifest.json"})
            client.get("/api/updates/check?force=1")
            assert client.post("/api/updates/download").status_code == 200
            for _ in range(30):
                st = client.get("/api/updates/status").json()["progress"]
                if st["status"] in {"error", "ready"}:
                    break
                time.sleep(0.1)
            assert st["status"] == "error"
            assert "SHA-256" in st["error"]

            # 5. Valid SHA-256 download -> ready -> apply creates automatic pre_update backup
            client.put("/api/updates/settings", json={"channel": "custom", "custom_url": f"{base_url}/manifest.json"})
            client.get("/api/updates/check?force=1")
            assert client.post("/api/updates/download").status_code == 200
            for _ in range(30):
                st = client.get("/api/updates/status").json()["progress"]
                if st["status"] in {"error", "ready"}:
                    break
                time.sleep(0.1)
            assert st["status"] == "ready"
            assert st["staged_ready"] is True
            assert st["staged_file_count"] == 3

            r_apply = client.post("/api/updates/apply")
            assert r_apply.status_code == 200
            ap = r_apply.json()
            assert ap["ok"] is True
            assert ap["backup"]["name"].endswith(".db")
    finally:
        srv.shutdown()
