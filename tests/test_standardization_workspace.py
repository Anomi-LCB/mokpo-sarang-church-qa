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
        async def _offline_cli(*args, **kwargs):
            raise RuntimeError("offline test mode")
            yield  # pragma: no cover

        with patch("core.std_publisher.stream_cli_with_failover", side_effect=_offline_cli):
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


def test_std_v42_images_pptx_group_leader_hwpx_diff_and_forms_vault(tmp_path: Path) -> None:
    import io
    import zipfile
    from PIL import Image
    from pptx import Presentation

    db_path = tmp_path / "std_v42.db"
    app = create_app(db_path=db_path)

    # Build real PNG image bytes
    img_buf = io.BytesIO()
    Image.new("RGB", (320, 180), color=(240, 245, 250)).save(img_buf, format="PNG")
    png_bytes = img_buf.getvalue()

    # Build real PPTX bytes (2 slides: title+bullets+table+notes)
    prs = Presentation()
    s1 = prs.slides.add_slide(prs.slide_layouts[1])
    s1.shapes.title.text = "2026 청년부 수련회 행정 표준안"
    s1.placeholders[1].text = "1. 출발 7일 전 차량 배차 신청\n2. 부장 및 지도교역자 결재 완료"
    s1.notes_slide.notes_text_frame.text = "발표자 노트: 당회장 최종 전결 사항 확인 필수"

    s2 = prs.slides.add_slide(prs.slide_layouts[5])
    s2.shapes.title.text = "예산 집행 기준표"
    tbl_shape = s2.shapes.add_table(2, 3, 500000, 1500000, 6000000, 1200000)
    tbl = tbl_shape.table
    for ci, val in enumerate(["항목", "한도", "결재권자"]):
        tbl.cell(0, ci).text = val
    for ci, val in enumerate(["간식비", "50만원", "재정부장"]):
        tbl.cell(1, ci).text = val
    pptx_buf = io.BytesIO()
    prs.save(pptx_buf)
    pptx_bytes = pptx_buf.getvalue()

    with TestClient(app) as client:
        admin_h = _login(client, "0000", "행정관리자", "adm_v42")
        leader_h = _login(client, "1234", "청년부그룹장", "usr_leader_v42")
        outsider_h = _login(client, "1234", "타부서교역자", "usr_outsider_v42")

        # Delegate group creation permission to leader & create private group
        leader_owner = client.get("/api/auth/me", headers=leader_h).json()["owner_id"]
        assert client.patch(
            f"/api/admin/members/{leader_owner}/permissions",
            headers=admin_h,
            json={"can_create_group": True},
        ).status_code == 200
        grp = client.post(
            "/api/groups",
            headers=leader_h,
            json={"name": "청년부 표준화팀", "description": "청년부 전용"},
        ).json()
        gid = grp["id"]

        # 1. Group Leader creates a group standardization board & manages full lifecycle!
        b = client.post(
            "/api/std/boards",
            headers=leader_h,
            json={
                "title": "청년부 수련회 행정 표준화",
                "category": "교육선교부",
                "work_type": "부서 업무 매뉴얼",
                "group_id": gid,
                "quorum_target": 5,
            },
        )
        assert b.status_code == 200, b.text
        bid = b.json()["id"]
        assert b.json().get("can_manage") is True

        # Group leader can PATCH board status directly (Pass-1 fix!)
        assert client.patch(f"/api/std/boards/{bid}", headers=leader_h, json={"status": "voting"}).status_code == 200
        assert client.patch(f"/api/std/boards/{bid}", headers=leader_h, json={"status": "collecting"}).status_code == 200

        # 2. Upload PNG image (plus duplicate check) and PPTX file!
        r_img = client.post(
            f"/api/std/boards/{bid}/submissions",
            headers=leader_h,
            data={"title": "현장 서식 촬영본", "notes": "기존 종이 양식 사진", "use_ai": "false"},
            files={"file": ("양식사진.png", png_bytes, "image/png")},
        )
        assert r_img.status_code == 200, r_img.text
        sub_img = r_img.json()["submission"]
        assert sub_img["meta"]["is_image"] is True
        assert sub_img["meta"]["width"] == 320 and sub_img["meta"]["height"] == 180
        assert r_img.json()["duplicate_of"] is None

        # Duplicate image upload warns with duplicate_of
        r_img_dup = client.post(
            f"/api/std/boards/{bid}/submissions",
            headers=leader_h,
            data={"title": "중복 사진 테스트", "notes": "", "use_ai": "false"},
            files={"file": ("양식사진2.png", png_bytes, "image/png")},
        )
        assert r_img_dup.status_code == 200
        assert r_img_dup.json()["duplicate_of"]["id"] == sub_img["id"]

        # Upload PPTX -> extracts slides, Markdown table, and speaker notes!
        r_pptx = client.post(
            f"/api/std/boards/{bid}/submissions",
            headers=leader_h,
            data={"title": "수련회 행정 발표자료", "notes": "청년부 수련회 안내", "use_ai": "false"},
            files={
                "file": (
                    "수련회안내.pptx",
                    pptx_bytes,
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                )
            },
        )
        assert r_pptx.status_code == 200, r_pptx.text
        sub_pptx = r_pptx.json()["submission"]
        assert sub_pptx["meta"]["is_pptx"] is True
        assert sub_pptx["meta"]["slide_count"] == 2
        assert sub_pptx["meta"]["table_count"] == 1
        assert "2026 청년부 수련회 행정 표준안" in sub_pptx["extracted_text"]
        assert "| 항목 | 한도 | 결재권자 |" in sub_pptx["extracted_text"]
        assert "발표자 노트: 당회장 최종 전결" in sub_pptx["extracted_text"]

        # Original file inline view & download work for member, blocked (403) for outsider!
        r_dl_img = client.get(f"/api/std/submissions/{sub_img['id']}/file", headers=leader_h)
        assert r_dl_img.status_code == 200 and r_dl_img.content[:4] == b"\x89PNG"
        r_dl_pptx = client.get(f"/api/std/submissions/{sub_pptx['id']}/file?download=1", headers=leader_h)
        assert r_dl_pptx.status_code == 200 and r_dl_pptx.content[:4] == b"PK\x03\x04"
        assert client.get(f"/api/std/submissions/{sub_img['id']}/file", headers=outsider_h).status_code == 403

        # Private group cross-memory isolation: outsider sees ZERO memories from Group G!
        outsider_mems = client.get("/api/std/cross-memory", headers=outsider_h).json()
        assert all(m["source_board_id"] != bid for m in outsider_mems)

        # 3. Edit submission cluster key + generate proposals + incremental enrichment + option polish + vote rationale!
        assert client.patch(
            f"/api/std/submissions/{sub_pptx['id']}",
            headers=leader_h,
            json={"ai_cluster_key": "수련회 행정 규격"},
        ).status_code == 200

        r_gen1 = client.post(f"/api/std/boards/{bid}/generate-proposals?use_ai=false", headers=leader_h)
        assert r_gen1.status_code == 200 and r_gen1.json()["count"] >= 1
        prop = next(p for p in r_gen1.json()["created"] if p["cluster_title"] == "수련회 행정 규격")
        opt_count_before = len(prop["options"])

        # Add another submission to the SAME cluster -> re-running generate-proposals appends it cleanly!
        s_extra = client.post(
            f"/api/std/boards/{bid}/submissions",
            headers=leader_h,
            data={"title": "수련회 안전 점검 추가안", "notes": "비상 연락망 포함", "use_ai": "false"},
        ).json()["submission"]
        client.patch(f"/api/std/submissions/{s_extra['id']}", headers=leader_h, json={"ai_cluster_key": "수련회 행정 규격"})
        r_gen2 = client.post(f"/api/std/boards/{bid}/generate-proposals?use_ai=false", headers=leader_h)
        assert r_gen2.status_code == 200 and r_gen2.json()["count"] >= 1
        prop_enriched = next(p for p in r_gen2.json()["created"] if p["id"] == prop["id"])
        assert len(prop_enriched["options"]) == opt_count_before + 1

        # Group leader polishes option wording inline & casts vote with rationale comment
        first_opt = prop_enriched["options"][0]
        r_opt_edit = client.patch(
            f"/api/std/proposal-options/{first_opt['id']}",
            headers=leader_h,
            json={"title": "수련회 행정 표준안 (현장 다듬기 완료)", "content_md": "보완된 수련회 절차 기준입니다."},
        )
        assert r_opt_edit.status_code == 200
        assert "현장 다듬기 완료" in r_opt_edit.json()["option"]["title"]

        r_vote = client.post(
            f"/api/std/proposals/{prop['id']}/vote",
            headers=leader_h,
            json={"option_id": first_opt["id"], "comment": "실무 적용이 가장 깔끔합니다"},
        )
        assert r_vote.status_code == 200
        voted_opt = next(o for o in r_vote.json()["proposal"]["options"] if o["id"] == first_opt["id"])
        assert any(v["comment"] == "실무 적용이 가장 깔끔합니다" for v in voted_opt["voters"])

        # 4. 2-Stage Draft -> Edit -> Finalize (v1.0 & v1.1) -> Verify PDF, DOCX, HWPX, Image Appendix, & 신·구조문 대조표!
        async def _offline_cli(*args, **kwargs):
            raise RuntimeError("offline test mode")
            yield  # pragma: no cover

        with patch("core.std_publisher.stream_cli_with_failover", side_effect=_offline_cli):
            r_draft = client.post(
                f"/api/std/boards/{bid}/compile/draft-stream",
                headers=leader_h,
                json={"version_label": "v1.0", "include_images": True},
            )
        assert r_draft.status_code == 200 and "event: draft" in r_draft.text
        draft_data = None
        for blk in r_draft.text.split("\n\n"):
            if blk.startswith("event: draft"):
                dl = [ln for ln in blk.splitlines() if ln.startswith("data:")][0]
                draft_data = json.loads(dl[5:].strip())
        assert draft_data and draft_data["manuscript"]["chapters"]

        # Finalize v1.0 as Group Leader!
        r_fin1 = client.post(
            f"/api/std/boards/{bid}/compile/finalize",
            headers=leader_h,
            json={
                "version_label": "v1.0",
                "manuscript": draft_data["manuscript"],
                "law_audit": draft_data["law_audit"],
                "vote_summary": draft_data["vote_summary"],
                "include_images": True,
            },
        )
        assert r_fin1.status_code == 200, r_fin1.text
        pub1 = r_fin1.json()["publication"]
        assert pub1["committee_report"]["has_hwpx"] is True
        assert pub1["committee_report"]["image_count"] >= 1

        # Modify Article 1 and finalize v1.1 -> generates 신·구조문 대조표!
        edited_ms = json.loads(json.dumps(draft_data["manuscript"]))
        edited_ms["chapters"][0]["articles"][0]["body"] = "본 규정은 2026년 청년부 수련회의 안전·예산·차량 기준을 개정하여 통일함을 목적으로 한다."
        r_fin2 = client.post(
            f"/api/std/boards/{bid}/compile/finalize",
            headers=leader_h,
            json={
                "version_label": "v1.1",
                "manuscript": edited_ms,
                "law_audit": draft_data["law_audit"],
                "vote_summary": draft_data["vote_summary"],
                "include_images": True,
            },
        )
        assert r_fin2.status_code == 200, r_fin2.text
        pub2 = r_fin2.json()["publication"]
        assert pub2["committee_report"]["diff_change_count"] >= 1

        # Verify HWPX download is a valid KS X 6101 ZIP with 신·구조문 대조표 inside section0.xml!
        r_hwpx = client.get(f"/api/std/publications/{pub2['id']}/download/hwpx", headers=leader_h)
        assert r_hwpx.status_code == 200 and r_hwpx.content[:4] == b"PK\x03\x04"
        with zipfile.ZipFile(io.BytesIO(r_hwpx.content)) as zf:
            assert zf.read("mimetype").decode("utf-8") == "application/hwp+zip"
            sec0 = zf.read("Contents/section0.xml").decode("utf-8")
            assert "신·구조문 대조표" in sec0
            assert "2026년 청년부 수련회의 안전·예산·차량 기준을 개정" in sec0

        # Verify /diff endpoint
        r_diff = client.get(f"/api/std/publications/{pub2['id']}/diff", headers=leader_h).json()
        assert r_diff["diff_report"]["modified_count"] >= 1
        assert any(r["status"] == "개정" for r in r_diff["diff_report"]["rows"])

        # 5. Admin 1-Click Register Standard Forms into Right-Side Forms Vault!
        r_reg = client.post(
            f"/api/std/publications/{pub2['id']}/register-forms",
            headers=admin_h,
            json={"notebook_id": "mokpo-sarang-church"},
        )
        assert r_reg.status_code == 200, r_reg.text
        assert r_reg.json()["registered_count"] >= 1
        forms_list = client.get("/api/notebooks/mokpo-sarang-church/forms", headers=admin_h).json()
        std_forms = [f for f in forms_list if f["id"].startswith("std_frm_")]
        assert len(std_forms) >= 1
        # Verify downloaded HWPX & PDF from Forms Vault for the newly registered standard form!
        fid = std_forms[0]["id"]
        assert client.get(f"/api/forms/{fid}/download/pdf", headers=admin_h).status_code == 200
        assert client.get(f"/api/forms/{fid}/download/hwpx", headers=admin_h).status_code == 200

        # 6. Expired deadline blocks new vote cleanly
        assert client.patch(f"/api/std/boards/{bid}", headers=leader_h, json={"deadline": "2020-01-01"}).status_code == 200
        r_exp = client.post(
            f"/api/std/proposals/{prop['id']}/vote",
            headers=leader_h,
            json={"option_id": first_opt["id"]},
        )
        assert r_exp.status_code == 400 and "마감일" in r_exp.json()["detail"]

        # 7. Deleting board cleans up uploaded/published disk directories!
        up_dir = Path(sub_img["stored_path"]).parent
        pub_dir = Path(pub2["pdf_path"]).parent
        assert up_dir.exists() and pub_dir.exists()
        assert client.delete(f"/api/std/boards/{bid}", headers=leader_h).status_code == 200
        assert not up_dir.exists() and not pub_dir.exists()
