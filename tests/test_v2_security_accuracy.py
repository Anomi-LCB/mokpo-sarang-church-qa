from __future__ import annotations

import time
from pathlib import Path

import docx
from fastapi.testclient import TestClient

from core.config import DEFAULT_NOTEBOOK_ID
from core.database import Database
from core.retriever import retrieve
from core.verifier import verify_citations
from server.main import create_app


def test_space_insensitive_and_synonym_retrieval_on_church_corpus():
    db = Database()
    # "위임목사" is printed as "위임 목사" (spaced) in 2000 헌법.pdf
    r1 = retrieve(db, DEFAULT_NOTEBOOK_ID, "위임목사 청빙 자격", top_k=8)
    assert r1.has_evidence is True
    assert any("총회헌법" in c["doc_title"] or "정관" in c["doc_title"] for c in r1.chunks)

    # "징계" bridges to "권징" via synonym group
    r2 = retrieve(db, DEFAULT_NOTEBOOK_ID, "교회 징계 책벌 절차", top_k=8)
    assert r2.has_evidence is True
    assert any("권징" in c["content"] or "권징" in c["heading"] for c in r2.chunks)

    # Curated form catalog has clean titles without noisy prose sentences
    forms = db.list_forms(DEFAULT_NOTEBOOK_ID)
    titles = [f["title"] for f in forms]
    assert "위임전결규정 전결권자표" in titles
    assert "학습·세례 신청서" in titles
    assert not any("대리자가 이를 대결할 수 있다" in t for t in titles)
    assert not any("행정서식은 당회결의로" in t for t in titles)


def test_post_generation_citation_verifier_catches_hallucinations():
    db = Database()
    res = retrieve(db, DEFAULT_NOTEBOOK_ID, "무임 장로 제직회 참여", top_k=5)
    assert res.has_evidence is True

    # Real grounded citation passes verification
    good_answer = "헌법적 규칙 제9조에 따르면 무임 장로는 당회의 결의로 제직회 회원이 될 수 있습니다. (p.201)"
    v_good = verify_citations(good_answer, res)
    assert v_good["status"] == "verified"
    assert v_good["unverified_refs"] == []

    # Fabricated clause & page caught immediately
    bad_answer = "제999조에 따르면 모든 장로는 매주 보고해야 합니다. (p.888)"
    v_bad = verify_citations(bad_answer, res)
    assert v_bad["status"] in ("unverified", "partial")
    assert "제999조" in v_bad["unverified_refs"]
    assert "p.888" in v_bad["unverified_refs"]


def test_v2_security_privacy_tickets_instant_report_backup_and_audit(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CHURCH_SEARCH_DATA_DIR", str(tmp_path / "data"))
    app = create_app(db_path=tmp_path / "data" / "v2.db")

    with TestClient(app) as client:
        # 1. Security response headers present
        h = client.get("/api/health")
        assert h.headers.get("X-Content-Type-Options") == "nosniff"
        assert h.headers.get("X-Frame-Options") == "DENY"
        assert h.headers.get("Referrer-Policy") == "no-referrer"

        # 2. Admin logs in & uploads a sample policy document
        a_login = client.post("/api/auth/login", json={"pin": "0000", "label": "관리자", "client_id": "dev_admin"}).json()
        assert a_login["is_default_pin"] is True
        a_hdr = {"Authorization": f"Bearer {a_login['token']}"}

        up = client.post(
            f"/api/notebooks/{DEFAULT_NOTEBOOK_ID}/documents/upload",
            files={"files": ("bylaw.txt", "제12조 (당회 정기회의)\n당회 정기회의는 매월 셋째 주일 오후 2시에 개회한다.\n".encode("utf-8"), "text/plain")},
            headers=a_hdr,
        ).json()
        for _ in range(30):
            j = client.get(f"/api/jobs/{up['job_id']}", headers=a_hdr).json()
            if j["status"] == "done":
                break
            time.sleep(0.1)
        assert j["status"] == "done"

        # 3. Member A logs in & runs Instant Offline Search (<50ms, no CLI needed) -> private session
        u1 = client.post("/api/auth/login", json={"pin": "1234", "label": "김목사", "client_id": "dev_userA"}).json()
        u1_hdr = {"Authorization": f"Bearer {u1['token']}"}
        u2 = client.post("/api/auth/login", json={"pin": "1234", "label": "이목사", "client_id": "dev_userB"}).json()
        u2_hdr = {"Authorization": f"Bearer {u2['token']}"}

        inst_res = client.post(
            "/api/chat/stream",
            json={"notebook_id": DEFAULT_NOTEBOOK_ID, "query": "당회 정기회의 개회 시간", "instant": True},
            headers=u1_hdr,
        )
        assert inst_res.status_code == 200
        assert "즉시 원문 검색 결과" in inst_res.text
        assert "오후 2시" in inst_res.text

        u1_sessions = client.get(f"/api/notebooks/{DEFAULT_NOTEBOOK_ID}/sessions", headers=u1_hdr).json()
        assert len(u1_sessions) == 1
        sid = u1_sessions[0]["id"]
        assert u1_sessions[0]["is_shared"] == 0

        # 4. Private chat isolation: User B cannot list or read User A's private chat!
        assert client.get(f"/api/notebooks/{DEFAULT_NOTEBOOK_ID}/sessions", headers=u2_hdr).json() == []
        assert client.get(f"/api/sessions/{sid}/messages", headers=u2_hdr).status_code == 403

        # 5. User A shares session with team -> User B can read it, but still cannot delete it!
        sh = client.patch(f"/api/sessions/{sid}", json={"is_shared": True}, headers=u1_hdr)
        assert sh.status_code == 200 and sh.json()["is_shared"] == 1
        assert len(client.get(f"/api/notebooks/{DEFAULT_NOTEBOOK_ID}/sessions", headers=u2_hdr).json()) == 1
        assert client.get(f"/api/sessions/{sid}/messages", headers=u2_hdr).status_code == 200
        assert client.delete(f"/api/sessions/{sid}", headers=u2_hdr).status_code == 403

        # 6. Export executive Word (.docx) meeting report & download ONLY via short-lived ticket (not ?token=)
        rep = client.post(
            "/api/reports/export-docx",
            json={
                "notebook_name": "목포사랑의교회 법규·행정",
                "question": "당회 정기회의 개회 시간",
                "answer": "매월 셋째 주일 오후 2시에 개회합니다. (제12조)",
                "mode": "instant",
                "citations": [{"doc_title": "bylaw", "heading": "제12조", "section_path": "", "page_start": 1, "page_end": 1, "excerpt": "매월 셋째 주일 오후 2시"}],
            },
            headers=u1_hdr,
        ).json()
        assert rep["ok"] is True
        dl_url = rep["download_url"]

        # Unauthenticated or legacy ?token= rejected cleanly!
        c_anon = TestClient(app)
        assert c_anon.get(dl_url).status_code == 401
        assert c_anon.get(f"{dl_url}?token={u1['token']}").status_code == 401

        # Short-lived ticket succeeds & returns valid DOCX
        tkt = client.post("/api/auth/ticket", headers=u1_hdr).json()["ticket"]
        dl_resp = c_anon.get(f"{dl_url}?ticket={tkt}")
        assert dl_resp.status_code == 200
        tmp_docx = tmp_path / "downloaded_report.docx"
        tmp_docx.write_bytes(dl_resp.content)
        wd = docx.Document(str(tmp_docx))
        full_txt = "\n".join(p.text for p in wd.paragraphs) + "\n" + "\n".join(
            cell.text for tbl in wd.tables for r in tbl.rows for cell in r.cells
        )
        assert "당회 정기회의 개회 시간" in full_txt
        assert "매월 셋째 주일 오후 2시" in full_txt

        # 7. Online DB Backup & Restore
        bk = client.post("/api/admin/backups", headers=a_hdr).json()
        assert bk["name"].startswith("backup_") and bk["size_bytes"] > 4096
        bks = client.get("/api/admin/backups", headers=a_hdr).json()
        assert any(b["name"] == bk["name"] for b in bks)
        rst = client.post(f"/api/admin/backups/{bk['name']}/restore", headers=a_hdr).json()
        assert rst["ok"] is True and rst["safety_backup"].startswith("backup_")

        # 8. Alphanumeric password change revokes existing member sessions immediately!
        pw_res = client.put(
            "/api/admin/pins",
            json={"member_pin": "Sarang2026!", "admin_pin": "Admin2026!", "revoke_existing": True},
            headers=a_hdr,
        ).json()
        assert pw_res["ok"] is True and pw_res["is_default_pin"] is False
        a_hdr = {"Authorization": f"Bearer {pw_res['token']}"}

        # User A's old session token is now invalid (401)!
        assert client.get("/api/notebooks", headers=u1_hdr).status_code == 401
        # Logging in with new alphanumeric password succeeds!
        new_login = client.post("/api/auth/login", json={"pin": "Sarang2026!", "label": "김목사"})
        assert new_login.status_code == 200

        # 9. Security audit logs captured events (note: restore rolled back to pre-backup_created snapshot, then logged backup_restored)
        logs = client.get("/api/admin/audit-logs", headers=a_hdr).json()
        event_types = {l["event_type"] for l in logs}
        assert {"login_ok", "doc_upload", "query_instant", "backup_restored", "pin_updated"}.issubset(event_types)


def test_document_update_and_admin_pin_delete_guard(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CHURCH_SEARCH_DATA_DIR", str(tmp_path / "data"))
    app = create_app(db_path=tmp_path / "data" / "upd.db")

    with TestClient(app) as client:
        a_tok = client.post("/api/auth/login", json={"pin": "0000", "label": "관리자"}).json()["token"]
        m_tok = client.post("/api/auth/login", json={"pin": "1234", "label": "팀원"}).json()["token"]
        a_hdr = {"Authorization": f"Bearer {a_tok}"}
        m_hdr = {"Authorization": f"Bearer {m_tok}"}

        # 1. Create custom notebook & upload initial v1 document
        nb = client.post("/api/notebooks", json={"name": "개정 테스트실"}, headers=a_hdr).json()
        nb_id = nb["id"]
        up = client.post(
            f"/api/notebooks/{nb_id}/documents/upload",
            files={"files": ("rules_v1.txt", "제1조 (예산 승인)\n예산 한도는 100만원으로 정한다.\n".encode("utf-8"), "text/plain")},
            headers=a_hdr,
        ).json()
        for _ in range(30):
            j = client.get(f"/api/jobs/{up['job_id']}", headers=a_hdr).json()
            if j["status"] == "done":
                break
            time.sleep(0.1)
        docs = client.get(f"/api/notebooks/{nb_id}/documents", headers=a_hdr).json()
        assert len(docs) == 1
        doc_id = docs[0]["id"]

        # 2. Metadata-only update (title/category/priority)
        meta_res = client.put(
            f"/api/documents/{doc_id}",
            json={"title": "2026년 개정 예산 규정", "category": "재정 규정", "priority": 95},
            headers=a_hdr,
        )
        assert meta_res.status_code == 200
        assert meta_res.json()["title"] == "2026년 개정 예산 규정"
        assert meta_res.json()["priority"] == 95

        # 3. In-place file replacement (v2) preserves doc_id & replaces searchable text!
        rep = client.post(
            f"/api/documents/{doc_id}/replace",
            files={"file": ("rules_v2.txt", "제1조 (예산 승인)\n개정된 예산 한도는 350만원으로 증액한다.\n".encode("utf-8"), "text/plain")},
            data={"title": "2026년 개정 예산 규정 (최종)", "category": "재정 규정", "priority": "95"},
            headers=a_hdr,
        ).json()
        for _ in range(30):
            j = client.get(f"/api/jobs/{rep['job_id']}", headers=a_hdr).json()
            if j["status"] == "done":
                break
            time.sleep(0.1)
        assert j["status"] == "done"

        docs2 = client.get(f"/api/notebooks/{nb_id}/documents", headers=a_hdr).json()
        assert len(docs2) == 1 and docs2[0]["id"] == doc_id
        assert docs2[0]["title"] == "2026년 개정 예산 규정 (최종)"

        # Instant search finds new v2 wording ("350만원") and NOT old v1 wording ("100만원")
        sr = client.post(
            "/api/chat/stream",
            json={"notebook_id": nb_id, "query": "개정된 예산 한도", "instant": True},
            headers=a_hdr,
        )
        assert "350만원" in sr.text and "100만원" not in sr.text

        # 4. Deletion requires BOTH Admin role AND valid Admin PIN (X-Admin-Pin)
        assert client.delete(f"/api/documents/{doc_id}", headers=m_hdr).status_code == 403
        assert client.delete(f"/api/documents/{doc_id}", headers=a_hdr).status_code == 403
        assert client.delete(f"/api/documents/{doc_id}", headers={**a_hdr, "X-Admin-Pin": "1234"}).status_code == 403
        assert client.delete(f"/api/documents/{doc_id}", headers={**a_hdr, "X-Admin-Pin": "9999"}).status_code == 403
        assert client.delete(f"/api/documents/{doc_id}", headers={**a_hdr, "X-Admin-Pin": "0000"}).status_code == 200
        assert client.get(f"/api/notebooks/{nb_id}/documents", headers=a_hdr).json() == []

        # 5. Notebook deletion also requires Admin PIN
        assert client.delete(f"/api/notebooks/{nb_id}", headers=a_hdr).status_code == 403
        assert client.delete(f"/api/notebooks/{nb_id}", headers={**a_hdr, "X-Admin-Pin": "0000"}).status_code == 200
