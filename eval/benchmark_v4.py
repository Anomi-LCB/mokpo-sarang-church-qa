from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import DEFAULT_NOTEBOOK_ID, get_db_path
from core.database import Database
from core.retriever import retrieve

# 28 real-world Mokpo Sarang Church legal/admin test queries spanning:
# - direct lookup, colloquial paraphrases, cross-references, table lookups,
# - multi-part compound queries, multi-turn follow-ups, and out-of-corpus traps
BENCHMARK_CASES: list[dict] = [
    # Direct legal lookup
    {"id": "Q01", "kind": "direct", "query": "장로 후보자 추천 나이와 자격 요건", "expect_doc": "시행세칙", "expect_terms": ["장로", "세"]},
    {"id": "Q02", "kind": "direct", "query": "무임 장로 제직회 참여 규정", "expect_doc": "헌법", "expect_terms": ["무임", "장로"]},
    {"id": "Q03", "kind": "direct", "query": "권찰 임기와 구역 심방 임무", "expect_doc": "헌법", "expect_terms": ["권찰"]},
    {"id": "Q04", "kind": "direct", "query": "교인의 구분 원입교인 학습교인 세례교인", "expect_doc": "정관", "expect_terms": ["원입교인", "학습"]},
    {"id": "Q05", "kind": "direct", "query": "유급직원의 조건과 복무 휴가 규정", "expect_doc": "시행세칙", "expect_terms": ["유급직원"]},
    {"id": "Q06", "kind": "direct", "query": "셀지기 자격 조건과 사역", "expect_doc": "시행세칙", "expect_terms": ["셀지기"]},
    {"id": "Q07", "kind": "direct", "query": "학습세례 신청서 양식과 제출 안내", "expect_doc": "시행세칙", "expect_terms": ["세례"]},
    {"id": "Q08", "kind": "direct", "query": "재심 청원서 권징 서식", "expect_doc": "해설서", "expect_terms": ["재심"]},
    # Colloquial / semantic paraphrase queries (harder for pure lexical BM25!)
    {"id": "Q09", "kind": "paraphrase", "query": "사정이 생겨 잠깐 쉬었다가 다시 복귀하려면 어떤 절차를 밟나요?", "expect_doc": "시행세칙", "expect_terms": ["휴직", "복직"]},
    {"id": "Q10", "kind": "paraphrase", "query": "교회 돈을 지출할 때 누가 최종 결재를 하나요?", "expect_doc": "시행세칙", "expect_terms": ["전결", "결재", "재정"]},
    {"id": "Q11", "kind": "paraphrase", "query": "담임목사가 자리를 비웠을 때 대신 결재하는 기준", "expect_doc": "시행세칙", "expect_terms": ["대결", "전결"]},
    {"id": "Q12", "kind": "paraphrase", "query": "다른 교회로 옮겨갈 때 필요한 증명서 발급 방법", "expect_doc": "헌법", "expect_terms": ["이명"]},
    {"id": "Q13", "kind": "paraphrase", "query": "교회 재산을 팔거나 처분할 때 어느 회의에서 결의해야 하나요?", "expect_doc": "정관", "expect_terms": ["재산", "공동의회"]},
    {"id": "Q14", "kind": "paraphrase", "query": "교회 버스나 승합차를 부서에서 빌려 쓰려면 어떻게 신청하나요?", "expect_doc": "시행세칙", "expect_terms": ["차량"]},
    {"id": "Q15", "kind": "paraphrase", "query": "교사들이 받아야 하는 훈련 과정과 지원 방법", "expect_doc": "시행세칙", "expect_terms": ["교사"]},
    {"id": "Q16", "kind": "paraphrase", "query": "징계를 받았을 때 억울해서 다시 판단해 달라고 올리는 절차", "expect_doc": "해설서", "expect_terms": ["상소", "재심", "권징"]},
    # Cross-reference & table-heavy legal queries
    {"id": "Q17", "kind": "table_xref", "query": "위임전결규정 제124조 별표 전결권자표", "expect_doc": "시행세칙", "expect_terms": ["전결"]},
    {"id": "Q18", "kind": "table_xref", "query": "감사 시행세칙 기준표와 감사 시기", "expect_doc": "시행세칙", "expect_terms": ["감사"]},
    {"id": "Q19", "kind": "table_xref", "query": "교구 편성 기준표와 교구 구성", "expect_doc": "시행세칙", "expect_terms": ["교구"]},
    {"id": "Q20", "kind": "table_xref", "query": "시행세칙 제53조 부서 조직", "expect_doc": "시행세칙", "expect_terms": ["예배선교부", "재정부", "제53조"]},
    # Multi-part compound queries (need BOTH topics!)
    {"id": "Q21", "kind": "compound", "query": "장로 후보자 나이와 유급직원 휴가 규정을 함께 비교 정리해줘", "expect_doc": "시행세칙", "expect_terms": ["장로", "유급직원"]},
    {"id": "Q22", "kind": "compound", "query": "휴직 청원서와 복직 청원서 절차 차이 알려줘", "expect_doc": "시행세칙", "expect_terms": ["휴직", "복직"]},
    # Multi-turn follow-up queries (depends on history!)
    {
        "id": "Q23",
        "kind": "followup",
        "query": "그럼 임기는 몇 년이야?",
        "history": [{"role": "user", "content": "권찰의 역할과 구역 심방 임무를 알려줘"}],
        "expect_doc": "헌법",
        "expect_terms": ["권찰"],
    },
    {
        "id": "Q24",
        "kind": "followup",
        "query": "그 서식은 어디에 있어?",
        "history": [{"role": "user", "content": "휴직 청원 절차 알려줘"}],
        "expect_doc": "시행세칙",
        "expect_terms": ["휴직"],
    },
    # Out-of-corpus hallucination traps (MUST block with has_evidence=False!)
    {"id": "T01", "kind": "trap", "query": "목포사랑의교회 주차장 시간당 요금이 얼마인가요?", "expect_evidence": False},
    {"id": "T02", "kind": "trap", "query": "2026년 월드컵 우승팀은 어느 나라인가요?", "expect_evidence": False},
    {"id": "T03", "kind": "trap", "query": "삼성전자 오늘 주식 가격 알려줘", "expect_evidence": False},
    {"id": "T04", "kind": "trap", "query": "아이폰 18 출시일과 가격 알려줘", "expect_evidence": False},
]


def run_benchmark(label: str = "baseline") -> dict:
    db = Database(get_db_path())
    pos_cases = [c for c in BENCHMARK_CASES if c["kind"] != "trap"]
    trap_cases = [c for c in BENCHMARK_CASES if c["kind"] == "trap"]

    latencies_ms: list[float] = []
    recall5 = 0
    mrr5_sum = 0.0
    term_hit_full = 0
    per_kind: dict[str, list[bool]] = {}
    details: list[dict] = []

    for c in pos_cases:
        t0 = time.perf_counter()
        # Pass history if retrieve supports it (v4.0+), else plain v3.1 call
        try:
            res = retrieve(db, DEFAULT_NOTEBOOK_ID, c["query"], top_k=8, history=c.get("history"))
        except TypeError:
            res = retrieve(db, DEFAULT_NOTEBOOK_ID, c["query"], top_k=8)
        dt = (time.perf_counter() - t0) * 1000.0
        latencies_ms.append(dt)

        top5 = res.chunks[:5]
        first_rank = 0
        combined_top5 = "\n".join(
            f"{ch.get('doc_title','')} {ch.get('section_path','')} {ch.get('heading','')} {ch.get('content','')}"
            for ch in top5
        )
        for rank, ch in enumerate(top5, start=1):
            blob = f"{ch.get('doc_title','')} {ch.get('section_path','')} {ch.get('heading','')} {ch.get('content','')}"
            if c["expect_doc"] in ch.get("doc_title", "") and any(t in blob for t in c["expect_terms"]):
                first_rank = rank
                break

        hit = first_rank > 0 and res.has_evidence
        if hit:
            recall5 += 1
            mrr5_sum += 1.0 / first_rank
        all_terms_ok = res.has_evidence and all(t in combined_top5 for t in c["expect_terms"])
        if all_terms_ok:
            term_hit_full += 1

        per_kind.setdefault(c["kind"], []).append(hit and all_terms_ok)
        details.append(
            {
                "id": c["id"],
                "kind": c["kind"],
                "rank": first_rank,
                "all_terms_ok": all_terms_ok,
                "has_evidence": res.has_evidence,
                "ms": round(dt, 1),
                "top1": top5[0]["doc_title"] + " " + top5[0].get("heading", "") if top5 else "(none)",
            }
        )

    trap_blocked = 0
    for c in trap_cases:
        t0 = time.perf_counter()
        res = retrieve(db, DEFAULT_NOTEBOOK_ID, c["query"], top_k=8)
        latencies_ms.append((time.perf_counter() - t0) * 1000.0)
        if not res.has_evidence:
            trap_blocked += 1
        details.append({"id": c["id"], "kind": "trap", "blocked": not res.has_evidence})

    latencies_ms.sort()
    p50 = latencies_ms[len(latencies_ms) // 2]
    p95 = latencies_ms[int(len(latencies_ms) * 0.95)]
    summary = {
        "label": label,
        "recall_at_5": round(recall5 / len(pos_cases) * 100, 1),
        "mrr_at_5": round(mrr5_sum / len(pos_cases), 3),
        "all_terms_in_top5_pct": round(term_hit_full / len(pos_cases) * 100, 1),
        "trap_block_pct": round(trap_blocked / len(trap_cases) * 100, 1),
        "latency_p50_ms": round(p50, 1),
        "latency_p95_ms": round(p95, 1),
        "by_kind_pct": {
            k: round(sum(v) / len(v) * 100, 1) for k, v in per_kind.items()
        },
        "misses": [d for d in details if d.get("kind") != "trap" and (d["rank"] == 0 or not d["all_terms_ok"])],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    run_benchmark(sys.argv[1] if len(sys.argv) > 1 else "baseline")
