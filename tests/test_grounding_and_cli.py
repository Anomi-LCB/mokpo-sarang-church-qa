from __future__ import annotations

import asyncio

import pytest

from core.config import DEFAULT_NOTEBOOK_ID
from core.database import Database
from core.retriever import retrieve
from server.cli_providers import build_grounded_prompt, detect_cli_providers, stream_cli_response


@pytest.mark.parametrize(
    "off_topic_query",
    [
        "목포사랑의교회 주차장 시간당 요금이 얼마인가요?",
        "2026년 월드컵 우승팀은 어느 나라인가요?",
        "삼성전자 오늘 주식 가격 알려줘",
        "아이폰 18 출시일이 언제인가요?",
        "서울시 강남구 아파트 평균 매매가 알려줘",
    ],
)
def test_grounding_gate_blocks_out_of_corpus_queries(off_topic_query: str):
    db = Database()
    res = retrieve(db, DEFAULT_NOTEBOOK_ID, off_topic_query, top_k=8)
    assert res.has_evidence is False, f"Should block off-topic query '{off_topic_query}', got chunks: {[c['heading'] for c in res.chunks]}"


def test_real_claude_cli_grounded_streaming():
    providers = {p.id: p for p in detect_cli_providers()}
    if not providers["claude"].available:
        pytest.skip("Claude Code CLI not installed")

    db = Database()
    nb = db.ensure_default_notebook()
    query = "무임 장로의 제직회 참여와 성찬 예식 규정을 근거를 들어 간단히 정리해줘"
    res = retrieve(db, DEFAULT_NOTEBOOK_ID, query, top_k=5)
    assert res.has_evidence is True

    prompt = build_grounded_prompt(nb, query, res, mode="practical")

    async def _run() -> str:
        parts = []
        async for chunk in stream_cli_response("claude", prompt, timeout_sec=90):
            parts.append(chunk)
        return "".join(parts).strip()

    answer = asyncio.run(_run())
    assert len(answer) > 30
    assert "[source]" not in answer
    assert any(k in answer for k in ["무임", "장로", "당회", "제직회", "성찬"])
