from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from core.database import Database, _KOR_PARTICLES, _WORD_RE

_STOPWORDS = {
    "무엇", "무엇인가", "무엇인가요", "뭐", "뭐야", "뭔가요", "어떻게", "어디", "언제", "누가", "왜",
    "알려줘", "알려주세요", "알려", "설명해줘", "설명", "정리해줘", "정리", "요약해줘", "요약",
    "찾아줘", "찾아주세요", "검색", "보여줘", "보여주세요", "있나요", "있는지", "있어", "인가요",
    "대해", "대해서", "대한", "관련", "관련된", "내용", "규정", "조항", "문서", "자료", "파일",
    "만들어줘", "만들어", "작성해줘", "작성", "채워줘", "다운로드", "추출해줘", "추출", "제공",
    "서식", "양식", "서식지", "표", "좀", "그냥", "혹시", "그리고", "또는", "하는", "되는", "할",
    "수", "것", "등", "및", "내", "중", "시", "때", "후", "전", "위", "아래", "경우", "따라",
    "본", "교회", "목포사랑의교회", "사랑의교회", "총회", "추천", "제안", "개정", "수정", "솔루션",
}
_FORM_INTENT_WORDS = {
    "서식", "양식", "서식지", "신청서", "청원서", "보고서", "지원서",
    "평가서", "언약서", "소원장", "상소장", "표", "전결표", "파일", "다운", "작성", "채워",
}
_CLAUSE_RE = re.compile(r"(제\s*\d+\s*[편장절조](?:\s*의\s*\d+)?|문\s*\d+)")

# Church-law spacing & synonym bridge (bridges 2000 헌법 spaced typography ↔ modern 정관/시행세칙)
_SYNONYM_GROUPS: list[set[str]] = [
    {"위임목사", "담임목사", "당회장"},
    {"시무장로", "치리장로", "장로"},
    {"무임장로", "무임", "협동장로"},
    {"안수집사", "서리집사", "집사"},
    {"시무권사", "권사"},
    {"권찰", "권잘", "권살", "구역심방"},
    {"셀지기", "셀사역자", "셀리더", "지체지기", "교구지기"},
    {"징계", "권징", "책벌", "치리", "시벌"},
    {"전결", "위임전결", "대결", "전결권자"},
    {"휴직", "안식년", "복직", "사임"},
    {"청빙", "위임", "임직", "피택", "취임"},
    {"이명", "이래", "이명증서"},
    {"세례", "학습", "입교", "유아세례", "성례"},
    {"공동의회", "제직회", "당회", "노회"},
    {"유급직원", "부교역자", "취업규칙", "복무"},
]


@dataclass
class RetrievalResult:
    has_evidence: bool
    confidence: float
    query_keywords: list[str]
    clause_refs: list[str]
    wants_form: bool
    chunks: list[dict[str, Any]]
    forms: list[dict[str, Any]]
    searched_doc_titles: list[str]


def _expand_church_synonyms(keywords: list[str]) -> list[str]:
    expanded: list[str] = []
    for k in keywords:
        for grp in _SYNONYM_GROUPS:
            if k in grp:
                for alt in grp:
                    if alt != k and alt not in keywords and alt not in expanded:
                        expanded.append(alt)
    return expanded[:10]


def _extract_query_features(query: str) -> tuple[list[str], list[str], list[str], list[str], bool]:
    """Return (substantive_keywords, expanded_synonyms, all_stems, clause_refs, wants_form)."""
    clause_refs = [re.sub(r"\s+", "", m.group(1)) for m in _CLAUSE_RE.finditer(query)]
    wants_form = any(w in query for w in _FORM_INTENT_WORDS)

    all_stems: list[str] = []
    substantive: list[str] = []
    for raw in _WORD_RE.findall(query):
        w = raw.lower()
        stem = _KOR_PARTICLES.sub("", w) if len(w) >= 3 else w
        if not stem:
            stem = w
        if len(stem) >= 2 and stem not in all_stems:
            all_stems.append(stem)
        if len(stem) >= 2 and stem not in _STOPWORDS and stem not in substantive:
            substantive.append(stem)

    # Also detect adjacent two-word compound forms (e.g. "위임 목사" -> "위임목사")
    words_seq = [w.lower() for w in _WORD_RE.findall(query)]
    for i in range(len(words_seq) - 1):
        comp = words_seq[i] + words_seq[i + 1]
        for grp in _SYNONYM_GROUPS:
            if comp in grp and comp not in substantive:
                substantive.append(comp)

    if not substantive:
        substantive = list(all_stems)
    synonyms = _expand_church_synonyms(substantive)
    return substantive, synonyms, all_stems, clause_refs, wants_form


def _char_bigrams(words: list[str]) -> set[str]:
    out: set[str] = set()
    for w in words:
        kor = "".join(ch for ch in w if "\uac00" <= ch <= "\ud7a3")
        for i in range(len(kor) - 1):
            out.add(kor[i : i + 2])
    return out


def _fts_escape(tok: str) -> str:
    clean = re.sub(r'["\'\*\-\+\^\(\)\:\[\]\{\}]', "", tok).strip()
    return f'"{clean}"' if clean else ""


def _expand_adjacent_context(db: Database, selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """For top hits that are short or appear mid-clause, append adjacent chunk text from the same document."""
    if not selected:
        return selected
    expanded: list[dict[str, Any]] = []
    seen_ids = {c["id"] for c in selected}

    with db.connect() as conn:
        for idx, ch in enumerate(selected):
            item = dict(ch)
            # Expand neighbor for top 4 hits if chunk is short or continues onto next chunk
            if idx < 4 and len(item["content"]) < 720:
                nxt = conn.execute(
                    "SELECT id, doc_id, page_start, page_end, heading, content FROM chunks WHERE id = ? AND doc_id = ?",
                    (item["id"] + 1, item["doc_id"]),
                ).fetchone()
                if nxt and nxt["id"] not in seen_ids:
                    same_section = (not nxt["heading"]) or (nxt["heading"] == item["heading"]) or (
                        nxt["page_start"] <= item["page_end"] + 1
                    )
                    if same_section and len(item["content"]) + len(nxt["content"]) <= 1550:
                        item["content"] = item["content"].rstrip() + "\n" + nxt["content"].lstrip()
                        item["page_end"] = max(item["page_end"], nxt["page_end"])
                        seen_ids.add(nxt["id"])
            expanded.append(item)
    return expanded


def format_instant_search_answer(query: str, retrieval: RetrievalResult) -> str:
    """Format an immediate (<50ms, 100% offline) grounded clause digest without invoking any LLM CLI."""
    if not retrieval.has_evidence or not retrieval.chunks:
        return (
            "제공된 자료에서 해당 정보를 찾을 수 없습니다.\n\n"
            "선택된 문서 범위를 확인하시거나 다른 핵심 단어로 다시 검색해 주세요."
        )

    lines: list[str] = [
        f"## 즉시 원문 검색 결과 ({len(retrieval.chunks)}건)",
        f"> 질의: **{query}** · 검색 대상: {', '.join(retrieval.searched_doc_titles)}",
        "",
    ]
    for idx, c in enumerate(retrieval.chunks[:6], start=1):
        loc = f"p.{c['page_start']}" if c["page_start"] == c["page_end"] else f"p.{c['page_start']}~{c['page_end']}"
        sec = " · ".join(x for x in (c.get("section_path", ""), c.get("heading", "")) if x)
        lines.append(f"### {idx}. [{c['doc_title']}] {sec or '본문'} ({loc})")
        excerpt = c["content"].strip()
        if len(excerpt) > 620:
            excerpt = excerpt[:620].rstrip() + "..."
        # Highlight matched keywords gently with bold
        for kw in sorted(retrieval.query_keywords, key=len, reverse=True)[:5]:
            if len(kw) >= 2:
                excerpt = re.sub(re.escape(kw), f"**{kw}**", excerpt, count=3, flags=re.I)
        lines.append(excerpt)
        lines.append("")

    if retrieval.forms:
        lines.append("### 관련 서식 · 표")
        for f in retrieval.forms:
            lines.append(f"- **{f['title']}** ({f['doc_title']}, p.{f['page_start']})")

    return "\n".join(lines).strip()


def retrieve(
    db: Database,
    notebook_id: str,
    query: str,
    doc_ids: list[str] | None = None,
    top_k: int = 8,
) -> RetrievalResult:
    docs = db.list_documents(notebook_id)
    ready_docs = [d for d in docs if d["status"] == "ready"]
    if doc_ids:
        selected_set = set(doc_ids)
        ready_docs = [d for d in ready_docs if d["id"] in selected_set]

    searched_titles = [d["title"] for d in ready_docs]
    if not ready_docs or not query.strip():
        return RetrievalResult(
            has_evidence=False,
            confidence=0.0,
            query_keywords=[],
            clause_refs=[],
            wants_form=False,
            chunks=[],
            forms=[],
            searched_doc_titles=searched_titles,
        )

    doc_map = {d["id"]: d for d in ready_docs}
    allowed_doc_ids = list(doc_map.keys())
    substantive, synonyms, all_stems, clause_refs, wants_form = _extract_query_features(query)
    q_bigrams = _char_bigrams(substantive or all_stems)
    syn_bigrams = _char_bigrams(synonyms)

    # Build FTS5 MATCH expression combining clause refs, stems, synonyms, and Korean bigrams
    fts_terms: list[str] = []
    for c in clause_refs:
        e = _fts_escape(c)
        if e:
            fts_terms.append(e)
    for k in (substantive or all_stems)[:10]:
        e = _fts_escape(k)
        if e:
            fts_terms.append(e)
    for s in synonyms[:6]:
        e = _fts_escape(s)
        if e:
            fts_terms.append(e)
    for bg in list(q_bigrams | syn_bigrams)[:18]:
        fts_terms.append(_fts_escape("bg_" + bg))

    candidates: dict[int, dict[str, Any]] = {}
    if fts_terms:
        match_expr = " OR ".join(dict.fromkeys(fts_terms))
        placeholders = ",".join("?" for _ in allowed_doc_ids)
        sql = f"""
            SELECT c.id, c.doc_id, c.page_start, c.page_end, c.heading, c.section_path, c.content,
                   bm25(chunks_fts) AS raw_bm25
            FROM chunks_fts
            JOIN chunks c ON c.id = chunks_fts.chunk_id
            WHERE chunks_fts MATCH ?
              AND c.notebook_id = ?
              AND c.doc_id IN ({placeholders})
            ORDER BY raw_bm25 ASC
            LIMIT 160
        """
        with db.connect() as conn:
            rows = conn.execute(sql, [match_expr, notebook_id, *allowed_doc_ids]).fetchall()
            for r in rows:
                d = dict(r)
                candidates[d["id"]] = d

    # Direct LIKE lookup for exact clause refs (e.g., 제25조) and spaced compounds (e.g. "위임목사" -> "위임%목사")
    with db.connect() as conn:
        placeholders = ",".join("?" for _ in allowed_doc_ids)
        for ref in clause_refs[:3]:
            rows = conn.execute(
                f"""
                SELECT id, doc_id, page_start, page_end, heading, section_path, content, -10.0 AS raw_bm25
                FROM chunks
                WHERE notebook_id = ? AND doc_id IN ({placeholders})
                  AND (heading LIKE ? OR content LIKE ?)
                LIMIT 25
                """,
                [notebook_id, *allowed_doc_ids, f"%{ref}%", f"%{ref}%"],
            ).fetchall()
            for r in rows:
                d = dict(r)
                candidates.setdefault(d["id"], d)

        # Space-bridging fallback for 4+ char Korean compound terms (e.g., 위임목사 -> 위임%목사)
        for kw in substantive[:4]:
            if len(kw) == 4 and all("\uac00" <= ch <= "\ud7a3" for ch in kw):
                spaced_pat = f"%{kw[:2]} {kw[2:]}%"
                rows = conn.execute(
                    f"""
                    SELECT id, doc_id, page_start, page_end, heading, section_path, content, -8.0 AS raw_bm25
                    FROM chunks
                    WHERE notebook_id = ? AND doc_id IN ({placeholders})
                      AND (heading LIKE ? OR content LIKE ?)
                    LIMIT 20
                    """,
                    [notebook_id, *allowed_doc_ids, spaced_pat, spaced_pat],
                ).fetchall()
                for r in rows:
                    d = dict(r)
                    candidates.setdefault(d["id"], d)

    # Re-score candidates with space-insensitive + synonym-aware Korean legal relevance
    scored: list[dict[str, Any]] = []
    kw_list = substantive or all_stems
    for cid, cand in candidates.items():
        text_full = f"{cand['heading']} {cand['section_path']} {cand['content']}"
        text_lower = text_full.lower()
        text_nospace = re.sub(r"\s+", "", text_lower)
        heading_nospace = re.sub(r"\s+", "", cand["heading"].lower())
        doc_info = doc_map[cand["doc_id"]]

        bm25_pos = max(0.0, -float(cand["raw_bm25"]))
        bm25_norm = min(bm25_pos / 12.0, 2.0)

        # Space-insensitive keyword match (catches "위임 목사" when user asks "위임목사"!)
        matched_kws = [k for k in kw_list if (k in text_lower or k in text_nospace)]
        matched_syns = [s for s in synonyms if (s in text_lower or s in text_nospace)]

        kw_cov = len(matched_kws) / max(1, len(kw_list))
        syn_bonus = min(len(matched_syns), 2) * 0.75

        heading_hits = sum(1 for k in kw_list if k in heading_nospace)
        clause_hit = any(ref in text_nospace for ref in clause_refs)

        bg_hits = sum(1 for bg in q_bigrams if bg in text_nospace)
        bg_cov = bg_hits / max(1, len(q_bigrams)) if q_bigrams else 0.0

        score = (
            bm25_norm * 1.35
            + kw_cov * 4.4
            + len(matched_kws) * 0.65
            + syn_bonus
            + heading_hits * 0.95
            + (3.4 if clause_hit else 0.0)
            + bg_cov * 1.65
            + (doc_info["priority"] / 100.0) * 0.15
        )
        if text_full.count("···") >= 3 or text_full.count("...") >= 4:
            score *= 0.25

        cand["score"] = round(score, 4)
        cand["matched_keywords"] = matched_kws
        cand["matched_synonyms"] = matched_syns
        cand["kw_coverage"] = round(kw_cov, 4)
        cand["bg_coverage"] = round(bg_cov, 4)
        cand["clause_hit"] = clause_hit
        cand["doc_title"] = doc_info["title"]
        cand["doc_category"] = doc_info["category"]
        cand["doc_priority"] = doc_info["priority"]
        scored.append(cand)

    scored.sort(key=lambda x: x["score"], reverse=True)

    # Select diverse top-K
    selected: list[dict[str, Any]] = []
    per_doc_count: dict[str, int] = {}
    max_per_doc = 4 if len(allowed_doc_ids) > 1 else top_k
    for item in scored:
        if len(selected) >= top_k:
            break
        if item["score"] < 1.15:
            continue
        did = item["doc_id"]
        if per_doc_count.get(did, 0) >= max_per_doc:
            continue
        selected.append(item)
        per_doc_count[did] = per_doc_count.get(did, 0) + 1

    # Adjacent-chunk context expansion for multi-paragraph clause integrity
    selected = _expand_adjacent_context(db, selected)

    # Match relevant forms/tables
    all_forms = db.list_forms(notebook_id, doc_ids=allowed_doc_ids)
    cited_pages = {(c["doc_id"], p) for c in selected for p in range(c["page_start"], c["page_end"] + 1)}
    scored_forms: list[tuple[float, dict[str, Any]]] = []
    for f in all_forms:
        ftext = re.sub(r"\s+", "", f"{f['title']} {f['category']} {f['sample_text'][:400]}".lower())
        ftitle = re.sub(r"\s+", "", f["title"].lower())
        f_score = 0.0
        for k in kw_list:
            if k in ftitle:
                f_score += 3.5
            elif k in ftext:
                f_score += 1.0
        for pno in range(f["page_start"], f["page_end"] + 1):
            if (f["doc_id"], pno) in cited_pages:
                f_score += 2.2
        if f_score >= (1.5 if wants_form else 2.5):
            scored_forms.append((f_score, f))
    scored_forms.sort(key=lambda x: x[0], reverse=True)
    matched_forms = [f for _, f in scored_forms[:4]]

    if not selected and not matched_forms:
        return RetrievalResult(
            has_evidence=False,
            confidence=0.0,
            query_keywords=kw_list,
            clause_refs=clause_refs,
            wants_form=wants_form,
            chunks=[],
            forms=[],
            searched_doc_titles=searched_titles,
        )

    best = selected[0] if selected else None
    best_kw_cnt = len(best["matched_keywords"]) if best else 0
    best_syn_cnt = len(best.get("matched_synonyms", [])) if best else 0
    best_kw_cov = best["kw_coverage"] if best else 0.0
    best_bg_cov = best["bg_coverage"] if best else 0.0
    best_score = best["score"] if best else 0.0

    has_evidence = True
    if not selected and matched_forms:
        has_evidence = True
        confidence = 0.65
    elif best is not None:
        if best["clause_hit"]:
            has_evidence = True
        elif best_kw_cnt == 0 and best_syn_cnt == 0 and best_bg_cov < 0.45:
            has_evidence = False
        elif len(kw_list) >= 2 and best_kw_cov < 0.34 and best_syn_cnt == 0 and best_bg_cov < 0.50:
            has_evidence = False
        elif best_score < 1.85 and not matched_forms:
            has_evidence = False
        confidence = min(1.0, round(best_score / 6.5, 2))
    else:
        has_evidence = False
        confidence = 0.0

    return RetrievalResult(
        has_evidence=has_evidence,
        confidence=confidence if has_evidence else 0.0,
        query_keywords=kw_list,
        clause_refs=clause_refs,
        wants_form=wants_form,
        chunks=selected if has_evidence else [],
        forms=matched_forms if has_evidence else [],
        searched_doc_titles=searched_titles,
    )
