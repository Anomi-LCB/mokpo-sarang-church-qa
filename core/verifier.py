from __future__ import annotations

import re
from typing import Any

from core.retriever import RetrievalResult

_CITE_ARTICLE_RE = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")
_CITE_PAGE_RE = re.compile(r"(?:p\.?|P\.?|쪽)\s*(\d{1,3})")

# Deterministic factual quantity extractor (ages, durations, quorums, percentages, KRW amounts)
_FACT_QTY_RE = re.compile(
    r"(만\s*\d+\s*세|\d+\s*세\s*(?:이상|이하|미만)|"
    r"\d+\s*분의\s*\d+|"
    r"\d+\s*(?:년|개월|주일|일간|일\s*이내|일\s*전)|"
    r"\d+(?:,\d{3})*\s*만?\s*원|"
    r"\d+\s*%)"
)

_KOR_FRACTION_ALIASES: dict[str, list[str]] = {
    "3분의2": ["2/3", "삼분의이", "3분의2"],
    "2분의1": ["1/2", "과반수", "이분의일", "2분의1"],
    "3분의1": ["1/3", "삼분의일", "3분의1"],
    "4분의3": ["3/4", "사분의삼", "4분의3"],
}


def detect_hierarchy_notes(retrieval: RetrievalResult) -> list[str]:
    """
    Detect when retrieved evidence spans multiple church-law authority tiers
    (총회헌법 > 목포사랑의교회 정관 > 2025년 사랑의교회 시행세칙 > 총회헌법해설서)
    so both the AI prompt and UI clearly preserve hierarchy precedence.
    """
    if not retrieval.chunks:
        return []
    titles = list(dict.fromkeys(c.get("doc_title", "") for c in retrieval.chunks))
    if len(titles) < 2:
        return []

    has_const = any("헌법" in t and "해설" not in t for t in titles)
    has_bylaw = any("정관" in t for t in titles)
    has_rule = any("시행세칙" in t for t in titles)

    notes: list[str] = []
    if has_bylaw and has_rule:
        notes.append(
            "개교회 최고 자치법규인 [목포사랑의교회 정관]과 세부 규정인 [시행세칙]이 함께 검색되었습니다. "
            "두 규정의 기준(임기·정족수·절차)이 다를 경우 정관 규정이 최우선 적용됩니다."
        )
    if has_const and (has_bylaw or has_rule):
        notes.append(
            "교단 최상위 [대한예수교장로회 총회헌법]과 개교회 규정이 함께 검색되었습니다. "
            "교단 헌법 원칙과 개교회 위임·세부 규정의 위계 차이를 구분하여 안내하세요."
        )
    return notes


def _number_exists_in_corpus(raw_qty: str, corpus_nospace: str) -> bool:
    norm = re.sub(r"\s+", "", raw_qty)
    if norm in corpus_nospace:
        return True
    # Check fraction aliases (e.g., 3분의2 <-> 2/3)
    for k, aliases in _KOR_FRACTION_ALIASES.items():
        if norm == k and any(a in corpus_nospace for a in aliases):
            return True
    # Check bare digits + unit root (e.g. "만40세" -> "40세")
    stripped = norm.lstrip("만")
    if stripped and stripped in corpus_nospace:
        return True
    m_num = re.search(r"\d+(?:,\d{3})*", norm)
    if m_num:
        digits = m_num.group(0).replace(",", "")
        unit_m = re.search(r"(세|년|개월|일|원|%|분)", norm)
        if unit_m:
            u = unit_m.group(1)
            if f"{digits}{u}" in corpus_nospace:
                return True
    return False


def verify_citations(answer: str, retrieval: RetrievalResult) -> dict[str, Any]:
    """
    Deterministically verify:
    1) Cited article numbers (제N조)
    2) Cited page numbers (p.N)
    3) Concrete factual quantities (age, term, quorum, days, money, %) against retrieved RAG chunks
    4) Legal hierarchy overlap notices (헌법 ↔ 정관 ↔ 시행세칙)
    """
    if not answer or not retrieval.has_evidence or not retrieval.chunks:
        return {
            "status": "no_evidence",
            "verified_count": 0,
            "unverified_refs": [],
            "checked_refs": [],
            "unverified_numbers": [],
            "hierarchy_notes": [],
            "summary": "근거 미발견 차단 응답",
        }

    # Build ground-truth corpus from retrieved chunks (including full parent_content when present)
    corpus_parts: list[str] = []
    for c in retrieval.chunks:
        corpus_parts.append(
            f"{c['doc_title']} {c.get('section_path', '')} {c.get('heading', '')} "
            f"{c.get('parent_content') or ''} {c['content']}"
        )
    corpus_text = "\n".join(corpus_parts)
    corpus_nospace = re.sub(r"\s+", "", corpus_text)

    valid_pages: set[int] = set()
    for c in retrieval.chunks:
        for p in range(int(c["page_start"]), int(c["page_end"]) + 1):
            valid_pages.add(p)
            valid_pages.add(max(1, p - 1))
            valid_pages.add(p + 1)
    for f in retrieval.forms:
        for p in range(int(f["page_start"]), int(f["page_end"]) + 1):
            valid_pages.add(p)

    # For advisory mode, focus strict checks on grounded sections rather than speculative draft clauses
    check_text = answer
    m_draft = re.search(r"###\s*3\.\s*규정\s*개정|###\s*3\.\s*개정", answer)
    if m_draft:
        before_draft = answer[: m_draft.start()]
        m_refs = re.search(r"###\s*참고\s*출처[\s\S]*$", answer)
        check_text = before_draft + ("\n" + m_refs.group(0) if m_refs else "")

    checked_refs: list[str] = []
    verified_refs: list[str] = []
    unverified_refs: list[str] = []

    # 1. Verify cited articles (제N조)
    seen_art: set[str] = set()
    for m in _CITE_ARTICLE_RE.finditer(check_text):
        art_label = f"제{m.group(1)}조" + (f"의{m.group(2)}" if m.group(2) else "")
        if art_label in seen_art:
            continue
        seen_art.add(art_label)
        checked_refs.append(art_label)
        if art_label in corpus_nospace:
            verified_refs.append(art_label)
        else:
            unverified_refs.append(art_label)

    # 2. Verify cited page numbers (p.N)
    seen_pg: set[int] = set()
    for m in _CITE_PAGE_RE.finditer(check_text):
        pno = int(m.group(1))
        if pno in seen_pg or pno == 0:
            continue
        seen_pg.add(pno)
        label = f"p.{pno}"
        checked_refs.append(label)
        if pno in valid_pages or f"-{pno}-" in corpus_nospace or f"•{pno}" in corpus_nospace:
            verified_refs.append(label)
        else:
            unverified_refs.append(label)

    # 3. Verify concrete factual quantities (ages, durations, quorums, money, %)
    verified_numbers: list[str] = []
    unverified_numbers: list[str] = []
    seen_qty: set[str] = set()
    for m in _FACT_QTY_RE.finditer(check_text):
        q_raw = re.sub(r"\s+", " ", m.group(1)).strip()
        if q_raw in seen_qty:
            continue
        # Skip document year numbers like "2025년", "2000년", "2012년"
        if re.match(r"^(19|20)\d{2}\s*년$", q_raw):
            continue
        seen_qty.add(q_raw)
        if _number_exists_in_corpus(q_raw, corpus_nospace):
            verified_numbers.append(q_raw)
        else:
            unverified_numbers.append(q_raw)

    hierarchy_notes = detect_hierarchy_notes(retrieval)

    if not checked_refs and not verified_numbers:
        doc_mentioned = any(c["doc_title"][:6] in answer for c in retrieval.chunks)
        return {
            "status": "verified" if doc_mentioned and not unverified_numbers else "partial",
            "verified_count": 1 if doc_mentioned else 0,
            "unverified_refs": [],
            "checked_refs": [],
            "unverified_numbers": unverified_numbers[:6],
            "hierarchy_notes": hierarchy_notes,
            "summary": (
                f"원문 근거 기반 검증 완료 (미확인 수치 {len(unverified_numbers)}건)"
                if unverified_numbers
                else ("원문 근거 기반 검증 완료" if doc_mentioned else "세부 조항·쪽수 표기 확인 권장")
            ),
        }

    total_verified = len(verified_refs) + len(verified_numbers)
    total_unverified = len(unverified_refs) + len(unverified_numbers)

    if total_unverified == 0:
        status = "verified"
        num_suffix = f" · 수치 {len(verified_numbers)}건 일치" if verified_numbers else ""
        summary = f"인용 조항·쪽수 {len(verified_refs)}건 원문 대조 완료{num_suffix}"
    elif total_verified >= total_unverified:
        status = "partial"
        summary = f"{total_verified}건 일치 · {total_unverified}건 원문 재확인 권장"
    else:
        status = "unverified"
        summary = f"미확인 인용·수치 {total_unverified}건 감지 — 하단 원문 확인 필요"

    return {
        "status": status,
        "verified_count": total_verified,
        "unverified_refs": unverified_refs[:8],
        "checked_refs": checked_refs[:12],
        "unverified_numbers": unverified_numbers[:6],
        "hierarchy_notes": hierarchy_notes,
        "summary": summary,
    }


def build_double_verify_prompt(query: str, draft_answer: str, retrieval: RetrievalResult) -> str:
    """Build a concise 2nd-pass verification prompt so the CLI/API audits every number/clause against raw RAG chunks."""
    evidence_blocks: list[str] = []
    for idx, ch in enumerate(retrieval.chunks, start=1):
        loc = f"p.{ch['page_start']}" if ch["page_start"] == ch["page_end"] else f"p.{ch['page_start']}~{ch['page_end']}"
        body = ch.get("parent_content") or ch["content"]
        evidence_blocks.append(f"[원본 {idx}] {ch['doc_title']} ({ch.get('heading', '')}, {loc})\n{body}")

    h_notes = detect_hierarchy_notes(retrieval)
    h_block = ("\n[법규 위계 유의]\n- " + "\n- ".join(h_notes) + "\n") if h_notes else ""

    return f"""당신은 교회 법규 원문 감수 전문가입니다.
아래 [초안 답변]의 모든 조항 번호, 숫자(나이·임기·정족수·일수·금액), 쪽수, 단서 예외 조항을 [원본 근거 자료]와 1:1로 엄격히 대조하세요.
{h_block}
[감수 규칙]
1. [원본 근거 자료]에 없는 숫자·조항·조건이 초안에 섞여 있다면 즉시 삭제하거나 "제공된 자료에서 확인되지 않습니다"로 수정하세요.
2. 조항 번호나 쪽수가 원본과 다르면 원본 기준으로 정확히 교정하세요.
3. 초안이 '적용·개정 제안' 모드여서 '개정 초안/제안' 섹션이 있다면, 그 제안이 원본 조항과 혼동되지 않도록 명확히 구분되어 있는지 확인하세요.
4. 메타 해설("검수 결과...")을 붙이지 말고, 최종 교정된 완성 답변 본문만 깔끔하게 출력하세요.

[사용자 질문]
{query}

[원본 근거 자료]
{"\n\n---\n\n".join(evidence_blocks)}

[초안 답변]
{draft_answer}
"""
