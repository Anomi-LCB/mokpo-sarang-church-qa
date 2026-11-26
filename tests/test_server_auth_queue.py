from __future__ import annotations

import asyncio
import time
from pathlib import Path

from fastapi.testclient import TestClient

from server.main import create_app
from server.queue_manager import QueryQueueManager


def test_pin_auth_roles_and_grounded_sse(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CHURCH_SEARCH_DATA_DIR", str(tmp_path / "data"))
    app = create_app(db_path=tmp_path / "data" / "srv.db")

    with TestClient(app) as client:
        # 1. Health works without auth
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

        # 2. Protected routes block unauthenticated requests
        assert client.get("/api/notebooks").status_code == 401

        # 3. Wrong PIN rejected
        assert client.post("/api/auth/login", json={"pin": "9999", "label": "외부인"}).status_code == 401

        # 4. Member PIN login succeeds, but cannot access admin endpoints
        m_login = client.post("/api/auth/login", json={"pin": "1234", "label": "김목사"})
        assert m_login.status_code == 200
        m_token = m_login.json()["token"]
        assert m_login.json()["role"] == "member"
        assert client.get("/api/notebooks", headers={"Authorization": f"Bearer {m_token}"}).status_code == 200
        assert (
            client.put(
                "/api/admin/pins",
                json={"member_pin": "5678"},
                headers={"Authorization": f"Bearer {m_token}"},
            ).status_code
            == 403
        )

        # 5. Admin PIN login succeeds and creates a custom notebook + ingests TXT
        a_login = client.post("/api/auth/login", json={"pin": "0000", "label": "행정관리자"})
        assert a_login.status_code == 200
        a_token = a_login.json()["token"]
        a_hdr = {"Authorization": f"Bearer {a_token}"}

        nb_res = client.post(
            "/api/notebooks",
            json={"name": "테스트 자료실", "description": "단위 테스트", "system_rules": ""},
            headers=a_hdr,
        )
        assert nb_res.status_code == 200
        nb_id = nb_res.json()["id"]

        up_res = client.post(
            f"/api/notebooks/{nb_id}/documents/upload",
            files={"files": ("rules.txt", "본 교회의 주일 예배는 오전 9시와 11시에 드립니다.".encode("utf-8"), "text/plain")},
            headers=a_hdr,
        )
        assert up_res.status_code == 200
        job_id = up_res.json()["job_id"]
        for _ in range(30):
            j = client.get(f"/api/jobs/{job_id}", headers=a_hdr).json()
            if j["status"] == "done":
                break
            time.sleep(0.1)
        assert j["status"] == "done"

        # 6. Out-of-corpus query returns immediate SSE Grounding Gate refusal without calling CLI
        sse_res = client.post(
            "/api/chat/stream",
            json={"notebook_id": nb_id, "query": "화성 탐사선 발사 비용은 얼마인가요?", "mode": "practical"},
            headers=a_hdr,
        )
        assert sse_res.status_code == 200
        body_text = sse_res.text
        assert '"has_evidence": false' in body_text
        assert "찾을 수 없습니다" in body_text

        # 7. Persistent chat session appears in list, can be renamed, restored, and deleted
        sessions = client.get(f"/api/notebooks/{nb_id}/sessions", headers=a_hdr).json()
        assert len(sessions) == 1
        sid = sessions[0]["id"]
        msgs = client.get(f"/api/sessions/{sid}/messages", headers=a_hdr).json()
        assert len(msgs) == 2

        ren = client.patch(f"/api/sessions/{sid}", json={"title": "주일 예배 문의"}, headers=a_hdr)
        assert ren.status_code == 200 and ren.json()["title"] == "주일 예배 문의"

        del_res = client.delete(f"/api/sessions/{sid}", headers=a_hdr)
        assert del_res.status_code == 200
        assert client.get(f"/api/notebooks/{nb_id}/sessions", headers=a_hdr).json() == []


def test_async_multi_user_queue_concurrency():
    async def _run():
        q = QueryQueueManager(max_concurrent=2)
        active_now = 0
        max_seen = 0
        queued_events = []

        async def worker(tid: str):
            nonlocal active_now, max_seen
            acquired = False
            try:
                async for st in q.wait_turn(tid):
                    if st["stage"] == "queued":
                        queued_events.append((tid, st["position"]))
                    elif st["stage"] == "acquired":
                        acquired = True
                active_now += 1
                max_seen = max(max_seen, active_now)
                await asyncio.sleep(0.12)
                active_now -= 1
            finally:
                if acquired:
                    await q.release()

        await asyncio.gather(*(worker(f"t{i}") for i in range(4)))
        assert max_seen == 2
        assert len(queued_events) >= 2
        assert q.status()["active"] == 0 and q.status()["queued"] == 0

    asyncio.run(_run())
