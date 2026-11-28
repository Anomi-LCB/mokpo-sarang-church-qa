from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient

from core.config import APP_VERSION, DEFAULT_NOTEBOOK_ID
from server.main import create_app


def test_personal_local_loopback_auto_login_and_remote_security(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CHURCH_SEARCH_DATA_DIR", str(tmp_path / "data"))
    app = create_app(db_path=tmp_path / "data" / "local_personal.db")

    # 1. Direct loopback (127.0.0.1) auto-authenticates as personal local PC admin without PIN wall
    with TestClient(app, client=("127.0.0.1", 51234)) as local_client:
        me = local_client.get("/api/auth/me").json()
        assert me["authenticated"] is True
        assert me["role"] == "admin"
        assert me["label"] == "내 PC"
        assert me["local_auto_login"] is True
        assert me["is_default_pin"] is False
        assert me.get("token")

        # 2. Reverse-proxied / tunneled request MUST NEVER auto-login even if socket is 127.0.0.1!
        spoof_client = TestClient(app, client=("127.0.0.1", 51235))
        with spoof_client:
            for hdr in (
                {"X-Forwarded-For": "203.0.113.45"},
                {"X-Forwarded-Host": "church.trycloudflare.com"},
                {"CF-Connecting-IP": "198.51.100.2"},
            ):
                r = spoof_client.get("/api/auth/me", headers=hdr).json()
                assert r["authenticated"] is False, f"Tunnel header {hdr} bypassed PIN!"

        # 3. Clicking Logout locks the local session until next PIN login (doesn't immediately re-auto-login)
        out = local_client.post("/api/auth/logout")
        assert out.status_code == 200
        after_out = local_client.get("/api/auth/me").json()
        assert after_out["authenticated"] is False

        # 4. Logging back in with PIN clears the local lock
        login = local_client.post("/api/auth/login", json={"pin": "0000", "label": "내 PC", "client_id": "pc1"}).json()
        assert login["ok"] is True
        after_in = local_client.get("/api/auth/me").json()
        assert after_in["authenticated"] is True

        # 5. Default desktop preferences: local_auto_login=True, keep_tray_on_close=False
        cli = local_client.get("/api/admin/cli").json()
        assert cli["local_auto_login"] is True
        assert cli["keep_tray_on_close"] is False

        # 6. Turning OFF local_auto_login enforces PIN even on direct loopback
        upd = local_client.put(
            "/api/admin/cli",
            json={
                "connection_mode": cli["connection_mode"],
                "provider": cli["provider"],
                "model": cli["model"],
                "api_provider": cli["api_provider"],
                "api_model": cli["api_model"],
                "api_base_url": cli["api_base_url"],
                "max_concurrent": cli["max_concurrent"],
                "custom_public_url": cli["custom_public_url"],
                "cli_failover_enabled": cli["cli_failover_enabled"],
                "default_double_verify": cli["default_double_verify"],
                "default_chat_shared": cli["default_chat_shared"],
                "audit_log_enabled": cli["audit_log_enabled"],
                "local_auto_login": False,
                "keep_tray_on_close": True,
            },
        )
        assert upd.status_code == 200
        cli2 = local_client.get("/api/admin/cli").json()
        assert cli2["local_auto_login"] is False
        assert cli2["keep_tray_on_close"] is True

    # Fresh direct loopback client now sees authenticated=False because local_auto_login was turned off
    with TestClient(app, client=("127.0.0.1", 51236)) as fresh_local:
        assert fresh_local.get("/api/auth/me").json()["authenticated"] is False

    # Remote LAN device MUST ALWAYS require PIN
    with TestClient(app, client=("192.168.0.77", 51237)) as lan_client:
        assert lan_client.get("/api/auth/me").json()["authenticated"] is False


def test_first_class_local_pc_engine_without_external_ai(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CHURCH_SEARCH_DATA_DIR", str(tmp_path / "data"))
    app = create_app(db_path=tmp_path / "data" / "offline_pc.db")

    import server.cli_providers as cp
    import server.main as sm

    # Simulate a brand-new personal Windows PC with ZERO CLI tools installed and ZERO API keys saved
    monkeypatch.setattr(cp, "detect_cli_providers", lambda: [])
    monkeypatch.setattr(sm, "detect_cli_providers", lambda: [])
    for env_key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "CUSTOM_OPENAI_API_KEY"):
        monkeypatch.delenv(env_key, raising=False)

    with TestClient(app, client=("127.0.0.1", 51300)) as client:
        me = client.get("/api/auth/me").json()
        assert me["authenticated"] is True

        cli = client.get("/api/admin/cli").json()
        assert "PC 로컬 내장 엔진" in cli["active_engine_summary"]

        up = client.post(
            f"/api/notebooks/{DEFAULT_NOTEBOOK_ID}/documents/upload",
            files={
                "files": (
                    "bylaws.txt",
                    "제7조 (장로 피택 자격)\n장로 후보자는 만 40세 이상이며 무흠 세례교인으로 7년 이상 경과한 자로 한다.\n".encode("utf-8"),
                    "text/plain",
                )
            },
        )
        assert up.status_code == 200
        job_id = up.json()["job_id"]
        for _ in range(30):
            if client.get(f"/api/jobs/{job_id}").json()["status"] == "done":
                break

        res = client.post(
            "/api/chat/stream",
            json={
                "notebook_id": DEFAULT_NOTEBOOK_ID,
                "query": "장로 후보자 피택 자격 나이",
                "mode": "auto",
                "instant": False,
            },
        )
        assert res.status_code == 200
        body = res.text
        assert "event: error" not in body
        assert "local-pc-engine" in body
        assert "연결할 수 없어" not in body
        assert "만 40세" in body
        assert "event: done" in body


def test_windows_installer_is_uac_free_personal_app_and_launcher_exits_cleanly() -> None:
    root = Path(__file__).resolve().parent.parent
    iss = (root / "packaging" / "windows" / "installer.iss").read_text(encoding="utf-8-sig")
    assert f"AppVersion={APP_VERSION}" in iss
    assert "PrivilegesRequired=lowest" in iss
    assert "PrivilegesRequiredOverridesAllowed" not in iss
    assert "DefaultDirName={localappdata}\\Programs\\목포사랑의교회 행정Q&A" in iss
    assert "KillRunningApp" in iss
    assert "PrepareToInstall" in iss
    assert "InitializeUninstall" in iss
    assert "{userstartup}" in iss
    assert "{commonstartup}" not in iss
    # Tailscale must be custom-only so standard personal Windows install never touches system VPN/UAC
    assert 'Name: "tailscale";' in iss
    for line in iss.splitlines():
        if 'Name: "tailscale";' in line:
            assert "Types: custom" in line and "full" not in line

    launcher = (root / "packaging" / "windows" / "launcher.py").read_text(encoding="utf-8")
    assert "--server-worker" in launcher
    assert "_patch_edgechromium_deadlock_free" in launcher
    assert "RemoveWebResourceRequestedFilter" in launcher
    assert "win.events.loaded" not in launcher
    assert "_show_startup_failed_dialog" in launcher
    assert "timeout_graceful_shutdown=2" in launcher
    assert "_request_worker_shutdown" in launcher


def test_internal_desktop_prefs_and_shutdown_loopback_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CHURCH_SEARCH_DATA_DIR", str(tmp_path / "data"))
    shutdown_called = {"count": 0}
    app = create_app(
        db_path=tmp_path / "data" / "internal.db",
        on_shutdown=lambda: shutdown_called.__setitem__("count", shutdown_called["count"] + 1),
    )

    with TestClient(app, client=("192.168.0.50", 51400)) as remote:
        assert remote.get("/api/internal/desktop-prefs").status_code == 403
        assert remote.post("/api/internal/shutdown").status_code == 403

    with TestClient(app, client=("127.0.0.1", 51401)) as local:
        assert local.get("/api/internal/desktop-prefs", headers={"X-Forwarded-For": "1.2.3.4"}).status_code == 403
        prefs = local.get("/api/internal/desktop-prefs").json()
        assert prefs["ok"] is True
        assert prefs["keep_tray_on_close"] is False
        assert prefs["local_auto_login"] is True
        res = local.post("/api/internal/shutdown").json()
        assert res["ok"] is True and res["shutting_down"] is True


def test_database_auto_heals_corrupted_db_from_backup_and_fresh_fallback(tmp_path: Path) -> None:
    import shutil
    import sqlite3
    from core.database import Database

    # 1. Create a healthy DB, save a backup, then corrupt the live DB
    data_dir = tmp_path / "data"
    db_path = data_dir / "church_search.db"
    backups_dir = data_dir / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)

    db1 = Database(db_path=db_path)
    db1.ensure_default_notebook()
    db1.set_setting("sentinel_key", "preserved_value_123")
    db1.close_pooled_connections()

    backup_copy = backups_dir / "backup_20261128_090000_daily.db"
    shutil.copy2(db_path, backup_copy)

    # Corrupt live DB with garbage bytes + bogus -wal
    db_path.write_bytes(b"NOT A VALID SQLITE DATABASE FILE" * 200)
    Path(str(db_path) + "-wal").write_bytes(b"CORRUPT WAL")

    # Re-opening MUST auto-heal from the healthy backup without crashing!
    db2 = Database(db_path=db_path)
    assert db2.get_setting("sentinel_key") == "preserved_value_123"
    assert list(data_dir.glob("church_search.db.corrupt_*")), "Corrupt DB should be quarantined"
    db2.close_pooled_connections()

    # 2. Corrupt live DB with NO backups available -> MUST initialize a clean DB without crashing!
    shutil.rmtree(backups_dir)
    db_path.write_bytes(b"BROKEN_NO_BACKUP_BYTES" * 100)
    db3 = Database(db_path=db_path)
    nb = db3.ensure_default_notebook()
    assert nb["id"] == DEFAULT_NOTEBOOK_ID
    db3.close_pooled_connections()

    # Verify PRAGMA quick_check passes cleanly after WAL checkpoint on close
    conn = sqlite3.connect(str(db_path))
    assert conn.execute("PRAGMA quick_check;").fetchall() == [("ok",)]
    conn.close()
