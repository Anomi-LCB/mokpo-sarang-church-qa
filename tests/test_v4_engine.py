from __future__ import annotations

import numpy as np
from fastapi.testclient import TestClient

from core.answer_cache import TwoLayerAnswerCache
from core.database import Database
from core.ingest import chunk_pages
from core.korean_nlp import (
    decompose_compound_query,
    extract_legal_references,
    is_kiwi_available,
    resolve_followup_query,
    tokenize_korean_morphemes,
)
from core.retriever import RetrievalResult, retrieve
from core.verifier import detect_hierarchy_notes, verify_citations
from server.main import create_app


def test_kiwi_morphology_and_church_dictionary():
    assert is_kiwi_available() is True
    toks = tokenize_korean_morphemes("목포사랑의교회 시무장로의 안식년과 위임전결규정")
    assert "시무장로" in toks
    assert "장로" in toks
    assert "위임전결" in toks
    assert "전결" in toks
    assert "안식년" in toks


def test_followup_and_compound_query_intelligence():
    history = [
        {"role": "user", "content": "장로 후보자 추천 자격이 무엇인가요?"},
        {"role": "assistant", "content": "만 40세 이상 세례교인 중..."},
    ]
    rewritten, changed = resolve_followup_query("그럼 임기는 몇 년이야?", history)
    assert changed is True
    assert "장로" in rewritten
    assert "임기" in rewritten

    # Standalone query should NOT be rewritten
    plain, plain_changed = resolve_followup_query("목포사랑의교회 정관의 공동의회 소집 절차를 알려줘", history)
    assert plain_changed is False
    assert plain == "목포사랑의교회 정관의 공동의회 소집 절차를 알려줘"

    # Compound multi-subject decomposition
    subs = decompose_compound_query("장로 후보자 나이와 유급직원 휴가 규정을 함께 비교 정리해줘")
    assert len(subs) == 2
    assert any("장로" in s for s in subs)
    assert any("유급직원" in s for s in subs)


def test_legal_cross_reference_graph_and_parent_child_retrieval(tmp_path):
    db = Database(db_path=tmp_path / "v4_graph.db")
    db.ensure_default_notebook()
    pages = [
        {
            "page_no": 1,
            "text": (
                "제1장 재정 및 결재\n"
                "제10조 (지출 승인)\n"
                "① 모든 지출 결의는 제25조의 전결 한도에 따른다.\n"
                "② 긴급 예산은 재정부장 경유 후 담임목사 승인을 받는다.\n"
                "다만, 500만원 이상 특별지출은 반드시 당회 의결을 거쳐야 한다.\n"
            ),
            "is_ocr": 0,
            "has_table": 0,
        },
        {
            "page_no": 2,
            "text": (
                "제2장 별첨\n"
                "제25조 (갑을 분류 기준)\n"
                "갑종 항목은 위원회 의결, 을종 항목은 대표 확인으로 처리한다.\n"
            ),
            "is_ocr": 0,
            "has_table": 0,
        },
    ]
    chunks = chunk_pages(pages, doc_title="2025년 사랑의교회 시행세칙", doc_category="행정·실무 규정")
    assert any(c.get("parent_key") == "제10조" for c in chunks)
    assert any(c.get("parent_key") == "제25조" for c in chunks)
    assert all(c.get("context_header", "").startswith("[2025년 사랑의교회 시행세칙") for c in chunks)

    refs = extract_legal_references(pages[0]["text"], self_article="제10조")
    assert any(r["ref_target"] == "제25조" for r in refs)

    db.upsert_document(
        {
            "id": "doc_rule_v4",
            "notebook_id": "mokpo-sarang-church",
            "title": "2025년 사랑의교회 시행세칙",
            "original_filename": "rules.pdf",
            "stored_path": str(tmp_path / "rules.pdf"),
            "file_type": "pdf",
            "category": "행정·실무 규정",
            "priority": 80,
            "page_count": 2,
            "ocr_pages": 0,
            "total_chars": sum(len(p["text"]) for p in pages),
            "status": "ready",
        }
    )
    db.replace_document_content("doc_rule_v4", "mokpo-sarang-church", pages, chunks)

    res = retrieve(db, "mokpo-sarang-church", "지출 승인 절차 제10조")
    assert res.has_evidence is True
    assert res.xref_hops >= 1
    assert any(c.get("via_xref") == "교차참조(제25조)" for c in res.chunks)
    # Out-of-corpus trap must be blocked
    trap = retrieve(db, "mokpo-sarang-church", "목포사랑의교회 주차장 시간당 요금이 얼마인가요?")
    assert trap.has_evidence is False
    db.close_pooled_connections()


def test_deterministic_numeric_verifier_and_hierarchy_detector():
    retrieval = RetrievalResult(
        has_evidence=True,
        confidence=0.95,
        query_keywords=["장로", "나이"],
        clause_refs=["제15조"],
        wants_form=False,
        chunks=[
            {
                "id": 1,
                "doc_id": "d1",
                "doc_title": "목포사랑의교회 정관",
                "doc_category": "개교회 정관",
                "heading": "제15조 (장로 자격)",
                "section_path": "제3장 직원",
                "page_start": 5,
                "page_end": 5,
                "content": "제15조 장로 후보자는 만 40세 이상 세례교인으로 재적 3분의 2 찬성을 얻어야 한다.",
                "parent_content": "제15조 장로 후보자는 만 40세 이상 세례교인으로 재적 3분의 2 찬성을 얻어야 한다.",
                "score": 8.0,
            },
            {
                "id": 2,
                "doc_id": "d2",
                "doc_title": "2025년 사랑의교회 시행세칙",
                "doc_category": "행정·실무 규정",
                "heading": "제8조 (임직 절차)",
                "section_path": "제2장 인사",
                "page_start": 12,
                "page_end": 12,
                "content": "제8조 추천 후 6개월 교육 과정을 수료한다.",
                "parent_content": "제8조 추천 후 6개월 교육 과정을 수료한다.",
                "score": 6.5,
            },
        ],
        forms=[],
        searched_doc_titles=["목포사랑의교회 정관", "2025년 사랑의교회 시행세칙"],
    )

    notes = detect_hierarchy_notes(retrieval)
    assert len(notes) >= 1 and "정관" in notes[0]

    good = verify_citations("제15조(p.5)에 따라 만 40세 이상이며 3분의 2 찬성과 6개월 교육이 필요합니다.", retrieval)
    assert good["status"] == "verified"
    assert good["unverified_numbers"] == []
    assert len(good["hierarchy_notes"]) >= 1

    hallucinated = verify_citations("제15조(p.5)에 따라 만 55세 이상이며 99% 찬성이 필요합니다.", retrieval)
    assert "만 55세" in hallucinated["unverified_numbers"]
    assert "99%" in hallucinated["unverified_numbers"]
    assert hallucinated["status"] in ("partial", "unverified")


def test_two_layer_answer_cache_exact_and_semantic():
    cache = TwoLayerAnswerCache(max_entries=16, ttl_sec=600)
    v1 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    v_near = np.array([0.995, 0.0998, 0.0], dtype=np.float32)
    v_near = v_near / np.linalg.norm(v_near)
    v_far = np.array([0.0, 1.0, 0.0], dtype=np.float32)

    cache.put("nb1", "fp1", None, "auto", False, "장로 후보자 나이 기준?", {"text": "만 40세 이상"}, query_vec=v1)

    # Exact normalized match (ignores trailing punctuation & extra spaces)
    hit1 = cache.get("nb1", "fp1", None, "auto", False, "장로  후보자   나이 기준")
    assert hit1 is not None and hit1["text"] == "만 40세 이상"

    # Semantic near-duplicate hit (>= 0.955 cosine)
    hit2 = cache.get("nb1", "fp1", None, "auto", False, "장로가 되려면 몇 살 이상이어야 하나요", query_vec=v_near)
    assert hit2 is not None and hit2.get("semantic_hit", 0.0) >= 0.955

    # Unrelated vector misses
    assert cache.get("nb1", "fp1", None, "auto", False, "완전히 다른 질문", query_vec=v_far) is None

    # Corpus fingerprint change invalidates automatically!
    assert cache.get("nb1", "fp2", None, "auto", False, "장로 후보자 나이 기준?") is None


def test_engine_status_and_cache_clear_endpoints(tmp_path):
    app = create_app(db_path=tmp_path / "v4_api.db", port=18991)
    with TestClient(app) as client:
        r_login = client.post("/api/auth/login", json={"pin": "0000", "label": "관리자"})
        assert r_login.status_code == 200
        tok = r_login.json()["token"]
        hdrs = {"Authorization": f"Bearer {tok}"}

        r_st = client.get("/api/engine/status", headers=hdrs)
        assert r_st.status_code == 200
        data = r_st.json()
        assert data["version"].startswith("4.")
        assert data["kiwi_active"] is True
        assert "stats" in data and "neural" in data and "cache" in data

        r_clr = client.post("/api/admin/engine/cache/clear", headers=hdrs)
        assert r_clr.status_code == 200 and r_clr.json()["ok"] is True


def test_cli_quota_limit_detection():
    from server.cli_providers import _CLI_QUOTA_ERROR_RE

    assert _CLI_QUOTA_ERROR_RE.search("You've hit your weekly limit · resets Nov 28, 7pm (Asia/Seoul)")
    assert _CLI_QUOTA_ERROR_RE.search("Rate limit exceeded. Please try again later.")
    assert not _CLI_QUOTA_ERROR_RE.search("목포사랑의교회 정관 제15조에 따르면 장로 후보자는 만 40세 이상입니다.")
