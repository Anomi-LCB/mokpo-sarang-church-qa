from __future__ import annotations

import re
from typing import Any

from core.retriever import RetrievalResult

_CITE_ARTICLE_RE = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")
_CITE_PAGE_RE = re.compile(r"(?:p\.?|P\.?|쪽)\s*(\d{1,3})")


def verify_citations(answer: str, retrieval: RetrievalResult) -> dict[str, Any]:
    """Deterministically verify cited clause numbers & page numbers against retrieved RAG chunks."""
    if not answer or not retrieval.has_evidence or not retrieval.chunks:
        return {
            "status": "no_evidence",
            "verified_count": 0,
            "unverified_refs": [],
            "checked_refs": [],
            "summary": "근거 미발견 차단 응답",
        }

    # Build ground-truth sets from retrieved evidence chunks
    corpus_text = "\n".join(
        f"{c['doc_title']} {c.get('section_path', '')} {c.get('heading', '')} {c['content']}"
        for c in retrieval.chunks
    )
    corpus_nospace = re.sub(r"\s+", "", corpus_text)
    valid_pages: set[int] = set()
    for c in retrieval.chunks:
        for p in range(int(c["page_start"]), int(c["page_end"]) + 1):
            valid_pages.add(p)
            # Also tolerate +/-1 printed page offset vs PDF page number
            valid_pages.add(max(1, p - 1))
            valid_pages.add(p + 1)
    for f in retrieval.forms:
        for p in range(int(f["page_start"]), int(f["page_end"]) + 1):
            valid_pages.add(p)

    # For advisory mode, prioritize verifying Section 1 (원본 근거 규정) & 참고 출처, not hypothetical drafts
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

    if not checked_refs:
        # Answer did not list explicit article/page numbers; check doc title mention
        doc_mentioned = any(c["doc_title"][:6] in answer for c in retrieval.chunks)
        return {
            "status": "verified" if doc_mentioned else "partial",
            "verified_count": 1 if doc_mentioned else 0,
            "unverified_refs": [],
            "checked_refs": [],
            "summary": "원문 근거 기반 검증 완료" if doc_mentioned else "세부 조항·쪽수 표기 확인 권장",
        }

    if not unverified_refs:
        status = "verified"
        summary = f"인용 조항·쪽수 {len(verified_refs)}건 원문 대조 완료"
    elif len(verified_refs) >= len(unverified_refs):
        status = "partial"
        summary = f"{len(verified_refs)}건 일치 · {len(unverified_refs)}건 원문 재확인 권장"
    else:
        status = "unverified"
        summary = f"미확인 인용 {len(unverified_refs)}건 감지 — 하단 원문 확인 필요"

    return {
        "status": status,
        "verified_count": len(verified_refs),
        "unverified_refs": unverified_refs[:8],
        "checked_refs": checked_refs[:12],
        "summary": summary,
    }


def build_double_verify_prompt(query: str, draft_answer: str, retrieval: RetrievalResult) -> str:
    """Build a concise 2nd-pass verification prompt so the CLI audits every number/clause against raw RAG chunks."""
    evidence_blocks: list[str] = []
    for idx, ch in enumerate(retrieval.chunks, start=1):
        loc = f"p.{ch['page_start']}" if ch["page_start"] == ch["page_end"] else f"p.{ch['page_start']}~{ch['page_end']}"
        evidence_blocks.append(f"[원본 {idx}] {ch['doc_title']} ({ch.get('heading', '')}, {loc})\n{ch['content']}")

    return f"""당신은 교회 법규 원문 감수 전문가입니다.
아래 [초안 답변]의 모든 조항 번호, 숫자(나이·임기·정족수·일수), 쪽수, 사실 진술을 [원본 근거 자료]와 1:1로 엄격히 대조하세요.

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
