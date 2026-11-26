from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from server.main import create_app


def _login(client: TestClient, pin: str, label: str, cid: str) -> dict[str, str]:
    r = client.post("/api/auth/login", json={"pin": pin, "label": label, "client_id": cid})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_standardization_full_lifecycle_cross_memory_voting_and_pdf_publish(tmp_path: Path) -> None:
    db_file = tmp_path / "std_e2e.db"
    app = create_app(db_path=db_file)
    with TestClient(app) as client:
        admin_h = _login(client, "0000", "이창범 관리자", "adm_std")
        pastor_a = _login(client, "1234", "김목사", "usr_pastor_a")
        pastor_b = _login(client, "1234", "박목사", "usr_pastor_b")

        # 1. Admin creates Board 1 (예배·의전, anonymous voting, allow vote change)
        b1 = client.post(
            "/api/std/boards",
            headers=admin_h,
            json={
                "title": "예배·의전 표준 매뉴얼",
                "category": "예배·의전",
                "work_type": "규정·서식 표준화",
                "description": "주일예배·장례·세례 의전 행정 표준화",
                "vote_visibility": "anonymous",
                "submission_anonymous": False,
                "allow_vote_change": True,
                "auto_route_enabled": False,
            },
        )
        assert b1.status_code == 200, b1.text
        b1_id = b1.json()["id"]

        # 2. Pastor A uploads a regular worship file; Pastor B uploads a file heavily about 차량 운행·주차 관리!
        s1 = client.post(
            f"/api/std/boards/{b1_id}/submissions",
            headers=pastor_a,
            data={
                "title": "장례예배 의전 지침 A안",
                "notes": "장례예배 순서, 헌금위원 배치, 예배 의전 체크리스트입니다.",
                "use_ai": "false",
            },
            files={"file": ("장례의전A안.txt", "장례예배 의전 표준안\n1. 집례자 배정\n2. 예배 순서 및 성찬 준칙\n".encode("utf-8"), "text/plain")},
        )
        assert s1.status_code == 200, s1.text
        s1_id = s1.json()["submission"]["id"]

        s2 = client.post(
            f"/api/std/boards/{b1_id}/submissions",
            headers=pastor_b,
            data={
                "title": "장례예배 차량 운행 및 주차 지원 지침",
                "notes": "장례 시 교회 차량 버스 운행 신청서와 주차 시설 안전 관리 규정입니다.",
                "use_ai": "false",
            },
            files={"file": ("장례차량주차.txt", "차량 버스 운행 신청서 및 주차 시설 안전 소방 관리 기준\n운행 3일 전 차량 배차 신청\n".encode("utf-8"), "text/plain")},
        )
        assert s2.status_code == 200, s2.text
        s2_id = s2.json()["submission"]["id"]
        # Verify AI Cross-Board Memory recorded a DEFERRED suggestion for 차량·시설·안전!
        mems_after_s2 = s2.json()["analysis"]["memories"]
        assert any(m["action_type"] == "deferred" and "차량" in m["suggested_category"] for m in mems_after_s2), mems_after_s2

        # 3. Later, Admin creates Board 2 (차량·시설 운영 매뉴얼) -> remembered file auto-wakes up!
        b2 = client.post(
            "/api/std/boards",
            headers=admin_h,
            json={
                "title": "차량·시설 운영 매뉴얼",
                "category": "차량·시설·안전",
                "work_type": "매뉴얼 신설",
                "description": "교회 버스 운행 및 시설 대관·주차 표준화",
                "vote_visibility": "named",
                "allow_vote_change": False,
                "auto_route_enabled": True,
            },
        )
        assert b2.status_code == 200, b2.text
        b2_data = b2.json()
        b2_id = b2_data["id"]
        woken = b2_data.get("matched_memories", [])
        assert len(woken) >= 1 and woken[0]["target_board_id"] == b2_id, f"Deferred memory did not wake up: {woken}"
        mem_id = woken[0]["id"]

        # 4. Admin applies 병행 복사(copy) from cross-memory, then verifies Undo(revert), then manual batch Merge!
        r_copy = client.post(
            f"/api/std/cross-memory/{mem_id}/apply",
            headers=admin_h,
            json={"action": "copy", "target_board_id": b2_id},
        )
        assert r_copy.status_code == 200
        b2_detail = client.get(f"/api/std/boards/{b2_id}", headers=admin_h).json()
        assert len(b2_detail["submissions"]) == 1 and b2_detail["submissions"][0]["source_origin"] == "copied"

        # Test 1-click Undo(revert)
        r_rev = client.post(
            f"/api/std/cross-memory/{mem_id}/apply",
            headers=admin_h,
            json={"action": "revert"},
        )
        assert r_rev.status_code == 200
        assert len(client.get(f"/api/std/boards/{b2_id}", headers=admin_h).json()["submissions"]) == 0

        # Test Manual Batch Merge of s1 + s2 into Board 2
        r_merge = client.post(
            "/api/std/submissions/batch-action",
            headers=admin_h,
            json={
                "action": "merge",
                "submission_ids": [s1_id, s2_id],
                "target_board_id": b2_id,
                "merged_title": "장례·차량 통합 지침서",
            },
        )
        assert r_merge.status_code == 200
        b2_subs = client.get(f"/api/std/boards/{b2_id}", headers=admin_h).json()["submissions"]
        assert len(b2_subs) == 1 and b2_subs[0]["source_origin"] == "merged"

        # 5. Generate Voting Proposals (A안 + AI 개선안) & verify 1-person-1-vote + anonymous masking
        r_gen = client.post(f"/api/std/boards/{b1_id}/generate-proposals?use_ai=false", headers=admin_h)
        assert r_gen.status_code == 200 and r_gen.json()["count"] >= 1
        prop = r_gen.json()["created"][0]
        assert any(o["is_ai_improved"] == 1 for o in prop["options"])

        opt_0 = prop["options"][0]["id"]
        opt_ai = next(o["id"] for o in prop["options"] if o["is_ai_improved"] == 1)

        # Pastor A votes opt_0, then changes vote to opt_ai (allowed on Board 1)
        assert client.post(f"/api/std/proposals/{prop['id']}/vote", headers=pastor_a, json={"option_id": opt_0}).status_code == 200
        assert client.post(f"/api/std/proposals/{prop['id']}/vote", headers=pastor_a, json={"option_id": opt_ai}).status_code == 200
        # Pastor B votes opt_ai
        assert client.post(f"/api/std/proposals/{prop['id']}/vote", headers=pastor_b, json={"option_id": opt_ai}).status_code == 200

        b1_after = client.get(f"/api/std/boards/{b1_id}", headers=pastor_a).json()
        p_after = b1_after["proposals"][0]
        assert p_after["total_votes"] == 2
        ai_opt_after = next(o for o in p_after["options"] if o["id"] == opt_ai)
        assert ai_opt_after["vote_count"] == 2
        # Verify anonymous vote masking!
        assert all(v["voter_label"] == "익명" for v in ai_opt_after["voters"])

        # Verify locked 1-time vote policy (allow_vote_change=False) on Board 2!
        p2 = client.post(
            f"/api/std/boards/{b2_id}/proposals",
            headers=admin_h,
            json={
                "cluster_title": "차량 예약 마감 기한",
                "category_tag": "차량·시설",
                "summary": "테스트",
                "options": [
                    {"label": "A안", "title": "3일 전", "content_md": "3일 전"},
                    {"label": "B안", "title": "5일 전", "content_md": "5일 전"},
                ],
            },
        ).json()
        assert client.post(f"/api/std/proposals/{p2['id']}/vote", headers=pastor_a, json={"option_id": p2["options"][0]["id"]}).status_code == 200
        r_change_blocked = client.post(f"/api/std/proposals/{p2['id']}/vote", headers=pastor_a, json={"option_id": p2["options"][1]["id"]})
        assert r_change_blocked.status_code == 400

        # 6. Add improvement comment & compile 4-Role Expert Committee Official PDF + DOCX (mock CLI offline -> deterministic committee)
        assert client.post(
            f"/api/std/boards/{b1_id}/comments",
            headers=pastor_b,
            json={"content": "당회장 결재란을 우측 상단에 고정해 주세요.", "kind": "improvement"},
        ).status_code == 200

        async def _offline_cli(*args, **kwargs):
            raise RuntimeError("offline test mode")
            yield  # pragma: no cover

        with patch("core.std_publisher.stream_cli_with_failover", side_effect=_offline_cli):
            r_comp = client.post(
                f"/api/std/boards/{b1_id}/compile/stream",
                headers=admin_h,
                json={"version_label": "v1.0", "custom_directives": "공식 규정집 포맷"},
            )
        assert r_comp.status_code == 200
        assert "event: stage" in r_comp.text
        assert "event: done" in r_comp.text

        # Extract publication ID from SSE done event
        pub_id = ""
        for blk in r_comp.text.split("\n\n"):
            if blk.startswith("event: done"):
                data_line = [ln for ln in blk.splitlines() if ln.startswith("data:")][0]
                pub_id = json.loads(data_line[5:].strip())["publication"]["id"]
        assert pub_id

        # Verify PDF, DOCX, and HTML preview downloads!
        r_pdf = client.get(f"/api/std/publications/{pub_id}/download/pdf", headers=pastor_a)
        assert r_pdf.status_code == 200 and r_pdf.content[:5] == b"%PDF-"
        r_docx = client.get(f"/api/std/publications/{pub_id}/download/docx", headers=pastor_a)
        assert r_docx.status_code == 200 and r_docx.content[:4] == b"PK\x03\x04"
        r_prev = client.get(f"/api/std/publications/{pub_id}/preview", headers=pastor_a)
        assert r_prev.status_code == 200 and "목포사랑의교회" in r_prev.text

        # 7. 1-Click Publish compiled official PDF into main Q&A notebook!
        r_pub_qa = client.post(
            f"/api/std/publications/{pub_id}/publish-to-qa",
            headers=admin_h,
            json={"title": "예배·의전 표준 규정집 v1.0"},
        )
        assert r_pub_qa.status_code == 200, r_pub_qa.text
        doc_rec = r_pub_qa.json()["document"]
        assert doc_rec["status"] == "ready" and doc_rec["page_count"] >= 2


def test_std_church_taxonomy_approval_lines_and_custom_pdf_cover(tmp_path: Path):
    db_path = tmp_path / "std_cfg.db"
    app = create_app(db_path=db_path)

    with TestClient(app) as client:
        r_admin = client.post("/api/auth/login", json={"pin": "0000", "label": "행정목사"})
        assert r_admin.status_code == 200
        h = {"Authorization": f"Bearer {r_admin.json()['token']}"}

        # 1. Default config reflects 2025 목포사랑의교회 시행세칙 12 categories & delegation approval lines
        cfg = client.get("/api/std/config", headers=h).json()
        cat_names = [c["name"] for c in cfg["categories"]]
        assert len(cat_names) == 12
        assert "예배선교부" in cat_names and "재정부" in cat_names and "차량관리부" in cat_names
        dept_ap = next(p for p in cfg["approval_presets"] if p["id"] == "dept_standard")
        assert dept_ap["slots"] == ["총무", "부장", "지도교역자", "당회장"]
        fin_ap = next(p for p in cfg["approval_presets"] if p["id"] == "finance")
        assert fin_ap["slots"] == ["회계", "원회계", "재정부장", "당회장"]

        # 2. Customize PDF cover header + add custom category + custom approval preset
        cfg["categories"].append(
            {"name": "신혼·청년사역국", "keywords": ["신혼교구", "태영아부", "청년"], "approval_preset_id": "custom_pastor"}
        )
        cfg["approval_presets"].append(
            {"id": "custom_pastor", "name": "교구 맞춤 3단 결재", "slots": ["담당간사", "교구목사", "당회장"], "basis": "교구 실무 기준"}
        )
        cfg["pdf_template"]["denomination_header"] = "대한예수교장로회 · 목포사랑의교회 맞춤형 표준 규정집"
        cfg["pdf_template"]["default_recipient"] = "목포사랑의교회 담임목사(당회장) 귀하"
        r_save = client.put("/api/std/config", headers=h, json=cfg)
        assert r_save.status_code == 200

        # 3. Create board in customized category and compile PDF -> verify custom cover & vertical approval box appear!
        b = client.post(
            "/api/std/boards",
            headers=h,
            json={"title": "신혼교구 심방 규정 표준화", "category": "신혼·청년사역국", "work_type": "부서 업무 매뉴얼"},
        ).json()
        client.post(
            f"/api/std/boards/{b['id']}/submissions",
            headers=h,
            data={"title": "심방 보고서 초안", "notes": "신혼교구 심방 결과 보고 양식", "use_ai": "false"},
        )
        r_comp = client.post(
            f"/api/std/boards/{b['id']}/compile/stream",
            headers=h,
            json={"version_label": "v1.0"},
        )
        assert r_comp.status_code == 200
        pub_id = ""
        for line in r_comp.text.splitlines():
            if line.startswith("data:") and '"publication"' in line:
                pub_obj = json.loads(line[5:].strip())["publication"]
                pub_id = pub_obj["id"]
                assert pub_obj["committee_report"]["approval_slots"] == ["담당간사", "교구목사", "당회장"]
        assert pub_id

        prev_html = client.get(f"/api/std/publications/{pub_id}/preview", headers=h).text
        assert "목포사랑의교회 맞춤형 표준 규정집" in prev_html
        assert "담당간사" in prev_html and "교구목사" in prev_html and "당회장" in prev_html
        assert "결<br/>재" in prev_html
        assert "목포사랑의교회 담임목사(당회장) 귀하" in prev_html

        # 4. Reset restores official 12-department defaults cleanly
        r_rst = client.post("/api/std/config/reset", headers=h)
        assert r_rst.status_code == 200
        assert len(r_rst.json()["categories"]) == 12
