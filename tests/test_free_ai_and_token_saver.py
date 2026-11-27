from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from core.config import DEFAULT_NOTEBOOK_ID
from server.main import create_app


def test_quick_connect_gemini_validates_encrypts_and_activates(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CHURCH_SEARCH_DATA_DIR", str(tmp_path / "data"))
    app = create_app(db_path=tmp_path / "data" / "free_ai.db")

    # Mock live Gemini probe in server.main so test stays 100% offline & deterministic
    import server.main as sm

    monkeypatch.setattr(
        sm,
        "test_ai_connection",
        AsyncMock(
            return_value={
                "ok": True,
                "mode": "api",
                "provider": "gemini_api",
                "model": "gemini-2.5-flash",
                "latency_ms": 142,
                "reply_preview": "OK",
                "message": "API 연결 성공 (142ms)",
            }
        ),
    )

    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"pin": "0000", "label": "관리자", "client_id": "adm"}).json()
        hdr = {"Authorization": f"Bearer {login['token']}"}

        res = client.post(
            "/api/admin/ai/quick-connect-gemini",
            json={"api_key": "AIzaSyTestFreeKey123456789", "model": "gemini-2.5-flash"},
            headers=hdr,
        )
        assert res.status_code == 200
        body = res.json()
        assert body["ok"] is True
        assert body["model"] == "gemini-2.5-flash"

        cli = client.get("/api/admin/cli", headers=hdr).json()
        assert cli["connection_mode"] == "api"
        assert cli["api_provider"] == "gemini_api"
        assert "무료 Google Gemini" in cli["active_engine_summary"]
        gem = next(p for p in cli["api_providers"] if p["id"] == "gemini_api")
        assert gem["has_key"] is True
        assert gem["key_source"] == "saved"


def test_ollama_status_and_activate_switches_to_local_zero_cost_ai(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CHURCH_SEARCH_DATA_DIR", str(tmp_path / "data"))
    app = create_app(db_path=tmp_path / "data" / "ollama.db")

    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"pin": "0000", "label": "관리자", "client_id": "adm"}).json()
        hdr = {"Authorization": f"Bearer {login['token']}"}

        # Mock local Ollama daemon as running with gemma3:4b already installed
        monkeypatch.setattr(
            app.state.ollama,
            "probe_running",
            AsyncMock(return_value=(True, [{"name": "gemma3:4b", "size_gb": 3.3}])),
        )
        monkeypatch.setattr(app.state.ollama, "ensure_running", AsyncMock(return_value=True))

        st = client.get("/api/admin/ollama/status", headers=hdr).json()
        assert st["running"] is True
        assert st["ram_gb"] >= 1
        assert any(m["name"] == "gemma3:4b" for m in st["installed_models"])
        assert len(st["recommended_models"]) >= 3

        act = client.post("/api/admin/ollama/activate", json={"model": "gemma3:4b"}, headers=hdr)
        assert act.status_code == 200
        assert act.json()["ok"] is True

        cli = client.get("/api/admin/cli", headers=hdr).json()
        assert cli["connection_mode"] == "api"
        assert cli["api_provider"] == "openai_compatible"
        assert cli["api_model"] == "gemma3:4b"
        assert "로컬 무료 AI · Ollama" in cli["active_engine_summary"]


def test_token_saver_upgrade_skips_duplicate_user_message(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CHURCH_SEARCH_DATA_DIR", str(tmp_path / "data"))
    app = create_app(db_path=tmp_path / "data" / "saver.db")

    import server.main as sm

    async def _fake_stream(*args, **kwargs):
        yield "api:gemini_api", "정리된 AI 답변: 당회 정기회의는 매월 셋째 주일 오후 2시에 개회합니다. (제12조, p.1)"

    monkeypatch.setattr(sm, "stream_cli_with_failover", _fake_stream)

    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"pin": "0000", "label": "관리자", "client_id": "adm"}).json()
        hdr = {"Authorization": f"Bearer {login['token']}"}

        # Seed a single tiny policy doc
        up = client.post(
            f"/api/notebooks/{DEFAULT_NOTEBOOK_ID}/documents/upload",
            files={
                "files": (
                    "rules.txt",
                    "제12조 (당회 정기회의)\n당회 정기회의는 매월 셋째 주일 오후 2시에 개회한다.\n".encode("utf-8"),
                    "text/plain",
                )
            },
            headers=hdr,
        )
        assert up.status_code == 200
        # Wait for sync indexing job
        job_id = up.json()["job_id"]
        for _ in range(30):
            j = client.get(f"/api/jobs/{job_id}", headers=hdr).json()
            if j["status"] == "done":
                break

        # 1) Token-saver 0-won instant search
        r1 = client.post(
            "/api/chat/stream",
            json={
                "notebook_id": DEFAULT_NOTEBOOK_ID,
                "query": "당회 정기회의 시간",
                "mode": "auto",
                "instant": True,
            },
            headers=hdr,
        )
        assert r1.status_code == 200
        sessions = client.get(f"/api/notebooks/{DEFAULT_NOTEBOOK_ID}/sessions", headers=hdr).json()
        sid = sessions[0]["id"]
        msgs_before = client.get(f"/api/sessions/{sid}/messages", headers=hdr).json()
        assert len([m for m in msgs_before if m["role"] == "user"]) == 1

        # 2) 1-click [AI로 깔끔하게 정리] with skip_user_message=True
        r2 = client.post(
            "/api/chat/stream",
            json={
                "notebook_id": DEFAULT_NOTEBOOK_ID,
                "session_id": sid,
                "query": "당회 정기회의 시간",
                "mode": "practical",
                "instant": False,
                "skip_user_message": True,
            },
            headers=hdr,
        )
        assert r2.status_code == 200
        assert "정리된 AI 답변" in r2.text

        msgs_after = client.get(f"/api/sessions/{sid}/messages", headers=hdr).json()
        # Still ONLY ONE user bubble in history — no duplicate user question!
        assert len([m for m in msgs_after if m["role"] == "user"]) == 1
        assert len([m for m in msgs_after if m["role"] == "assistant"]) == 2
