from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from core.database import Database
from core.ingest import ingest_file
from server.event_bus import RealtimeEventBus
from server.main import create_app


def _login_headers(client: TestClient, pin: str, label: str, client_id: str) -> tuple[dict[str, str], dict]:
    r = client.post("/api/auth/login", json={"pin": pin, "label": label, "client_id": client_id})
    assert r.status_code == 200, r.text
    data = r.json()
    return {"Authorization": f"Bearer {data['token']}"}, data


def _seed_sample_doc(db: Database, tmp_path: Path) -> str:
    db.create_notebook("mokpo-sarang-church", "목포사랑의교회 행정Q&A", "테스트 노트북")
    txt = tmp_path / "규정_샘플.txt"
    txt.write_text(
        "제1조 (목적) 본 규정은 목포사랑의교회 행정 및 재정 집행의 표준을 정함을 목적으로 한다.\n"
        "제2조 (지출결의) 모든 지출은 회계, 원회계, 재정부장, 당회장의 위임전결 결재를 거친다.\n",
        encoding="utf-8",
    )
    docs = ingest_file(db, "mokpo-sarang-church", txt, title="목포사랑의교회 행정 샘플 규정", category="시행세칙")
    assert len(docs) == 1
    return docs[0]["id"]


def test_v3_group_permissions_invites_collab_chat_and_std(tmp_path: Path) -> None:
    db_path = tmp_path / "test_v3.db"
    db = Database(db_path)
    doc_id = _seed_sample_doc(db, tmp_path)
    app = create_app(db_path=db_path)

    with TestClient(app) as client:
        admin_h, admin_me = _login_headers(client, "0000", "관리자", "dev_admin_01")
        pastor_a_h, pastor_a = _login_headers(client, "1234", "김목사", "dev_pastor_a")
        pastor_b_h, pastor_b = _login_headers(client, "1234", "박목사", "dev_pastor_b")
        outsider_h, _outsider = _login_headers(client, "1234", "최목사", "dev_outsider")

        # 1. Non-granted member CANNOT create group (strict Q6 rule!)
        r_denied = client.post("/api/groups", headers=pastor_a_h, json={"name": "교구1팀", "description": "테스트"})
        assert r_denied.status_code == 403

        # 2. Admin sees member directory and grants group creation permission to 김목사
        r_members = client.get("/api/admin/members", headers=admin_h)
        assert r_members.status_code == 200
        owner_ids = [m["owner_id"] for m in r_members.json()]
        assert pastor_a["owner_id"] in owner_ids
        assert pastor_b["owner_id"] in owner_ids

        r_grant = client.patch(
            f"/api/admin/members/{pastor_a['owner_id']}/permissions",
            headers=admin_h,
            json={"can_create_group": True},
        )
        assert r_grant.status_code == 200
        assert r_grant.json()["can_create_group"] is True

        # 3. Now 김목사 CAN create a group and becomes leader automatically
        r_grp = client.post(
            "/api/groups",
            headers=pastor_a_h,
            json={"name": "재정·행정 표준화팀", "description": "2026 재정 규정 공동 검토"},
        )
        assert r_grp.status_code == 200, r_grp.text
        grp = r_grp.json()
        group_id = grp["id"]
        invite_code = grp["invite_code"]
        assert len(invite_code) == 6
        assert grp["my_role"] == "leader"

        # Invite QR & Link endpoint works for leader
        r_qr = client.get(f"/api/groups/{group_id}/invite-qr", headers=pastor_a_h)
        assert r_qr.status_code == 200
        assert f"join={invite_code}" in r_qr.json()["join_url"]
        assert r_qr.json()["qr_data_url"].startswith("data:image/png;base64,")

        # 4. 박목사 joins via 6-char invite code (case-insensitive)
        r_join = client.post("/api/groups/join", headers=pastor_b_h, json={"invite_code": invite_code.lower()})
        assert r_join.status_code == 200, r_join.text
        assert r_join.json()["group"]["id"] == group_id
        assert r_join.json()["group"]["member_count"] == 2

        # 5. Collaborative Group Chat: 김목사 starts a private chat, shares to group, 박목사 reads & appends!
        s = db.create_session(
            "sess_collab_01",
            "mokpo-sarang-church",
            user_label="김목사",
            title="지출결의 결재선 문의",
            owner_id=pastor_a["owner_id"],
        )
        db.add_message(
            s["id"],
            "user",
            "지출결의 결재선은 어떻게 되나요?",
            mode="instant",
            author_label="김목사",
            author_owner_id=pastor_a["owner_id"],
        )
        r_scope = client.patch(
            f"/api/sessions/{s['id']}",
            headers=pastor_a_h,
            json={"group_id": group_id, "is_shared": False},
        )
        assert r_scope.status_code == 200
        assert r_scope.json()["group_id"] == group_id

        # Outsider is blocked from seeing or reading group chat
        r_out_sess = client.get("/api/notebooks/mokpo-sarang-church/sessions", headers=outsider_h)
        assert r_out_sess.status_code == 200
        assert all(row["id"] != s["id"] for row in r_out_sess.json())
        assert client.get(f"/api/sessions/{s['id']}/messages", headers=outsider_h).status_code == 403

        # Group member 박목사 sees it, reads it, AND continues asking in the same collaborative chat!
        b_sessions = client.get("/api/notebooks/mokpo-sarang-church/sessions", headers=pastor_b_h).json()
        assert any(row["id"] == s["id"] and row["group_name"] == "재정·행정 표준화팀" for row in b_sessions)

        r_stream = client.post(
            "/api/chat/stream",
            headers=pastor_b_h,
            json={
                "notebook_id": "mokpo-sarang-church",
                "session_id": s["id"],
                "query": "위임전결 결재",
                "doc_ids": [doc_id],
                "mode": "practical",
                "instant": True,
            },
        )
        assert r_stream.status_code == 200
        msgs = client.get(f"/api/sessions/{s['id']}/messages", headers=pastor_a_h).json()
        user_authors = [m["author_label"] for m in msgs if m["role"] == "user"]
        assert "김목사" in user_authors
        assert "박목사" in user_authors

        # 6. Group-scoped Standardization Board: leader 김목사 creates group board
        r_board = client.post(
            "/api/std/boards",
            headers=pastor_a_h,
            json={
                "title": "재정팀 전용 지출결의서 통일",
                "category": "재정부",
                "work_type": "결재·공문 양식 통일",
                "group_id": group_id,
                "description": "재정·행정 표준화팀 전용 과제",
            },
        )
        assert r_board.status_code == 200, r_board.text
        board_id = r_board.json()["id"]
        assert r_board.json()["group_id"] == group_id

        # Outsider cannot see or open the group board; 박목사 CAN see and submit to it
        outsider_boards = client.get("/api/std/boards", headers=outsider_h).json()
        assert all(b["id"] != board_id for b in outsider_boards)
        assert client.get(f"/api/std/boards/{board_id}", headers=outsider_h).status_code == 403

        b_boards = client.get("/api/std/boards", headers=pastor_b_h).json()
        assert any(b["id"] == board_id and b["group_name"] == "재정·행정 표준화팀" for b in b_boards)
        r_sub = client.post(
            f"/api/std/boards/{board_id}/submissions",
            headers=pastor_b_h,
            data={"title": "박목사 지출결의서 초안", "notes": "회계-원회계-재정부장-당회장", "use_ai": "false"},
        )
        assert r_sub.status_code == 200

        # 7. Document Library metadata update (admin pins & tags)
        r_lib = client.patch(
            f"/api/documents/{doc_id}/library",
            headers=admin_h,
            json={"is_pinned_default": True, "tags": ["필수", "재정"]},
        )
        assert r_lib.status_code == 200
        assert r_lib.json()["is_pinned_default"] == 1
        assert r_lib.json()["tags"] == ["필수", "재정"]

        # 8. Ctrl+K Quick Search respects visibility scopes
        r_qs_b = client.get("/api/search/quick?notebook_id=mokpo-sarang-church&q=재정", headers=pastor_b_h)
        assert r_qs_b.status_code == 200
        qs_b = r_qs_b.json()
        assert any(b["id"] == board_id for b in qs_b["boards"])

        r_qs_out = client.get("/api/search/quick?notebook_id=mokpo-sarang-church&q=재정", headers=outsider_h)
        assert r_qs_out.status_code == 200
        assert all(b["id"] != board_id for b in r_qs_out.json()["boards"])

        # 9. Cross-device Personal Recovery Code preserves identity & groups
        r_set_rec = client.post("/api/auth/recovery-code", headers=pastor_b_h, json={"code": "park-sarang-2026"})
        assert r_set_rec.status_code == 200

        # New device logs in first (different owner_id), then claims 박목사's recovery code
        new_dev_h, new_dev = _login_headers(client, "1234", "박목사 폰", "dev_phone_new_99")
        assert new_dev["owner_id"] != pastor_b["owner_id"]
        r_claim = client.post("/api/auth/claim-recovery", headers=new_dev_h, json={"code": "park-sarang-2026"})
        assert r_claim.status_code == 200, r_claim.text
        claimed = r_claim.json()
        assert claimed["owner_id"] == pastor_b["owner_id"]
        recovered_h = {"Authorization": f"Bearer {claimed['token']}"}
        rec_groups = client.get("/api/groups", headers=recovered_h).json()["groups"]
        assert any(g["id"] == group_id for g in rec_groups)

        # 10. Revoking permission prevents creating another group
        client.patch(
            f"/api/admin/members/{pastor_a['owner_id']}/permissions",
            headers=admin_h,
            json={"can_create_group": False},
        )
        r_revoked = client.post("/api/groups", headers=pastor_a_h, json={"name": "권한회수테스트"})
        assert r_revoked.status_code == 403
        assert admin_me["can_create_group"] is True


def test_realtime_event_bus_pub_sub() -> None:
    async def _run() -> None:
        bus = RealtimeEventBus()
        q = bus.subscribe()
        bus.publish("chat_updated", session_id="s_123", group_id="g_1")
        evt = await asyncio.wait_for(q.get(), timeout=1.0)
        assert evt["type"] == "chat_updated"
        assert evt["session_id"] == "s_123"
        assert evt["group_id"] == "g_1"
        bus.unsubscribe(q)

    asyncio.run(_run())
