from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from core.database import Database
from core.korean_nlp import (
    STOPWORDS,
    _KOR_PARTICLES,
    _WORD_RE,
    decompose_compound_query,
    expand_colloquial_and_synonyms,
    resolve_followup_query,
    tokenize_korean_morphemes,
)
from core.neural_engine import neural_engine

_FORM_INTENT_WORDS = {
    "서식", "양식", "서식지", "신청서", "청원서", "보고서", "지원서",
    "평가서", "언약서", "소원장", "상소장", "표", "전결표", "파일", "다운", "작성", "채워",
}
_CLAUSE_RE = re.compile(r"(제\s*\d+\s*[편장절조](?:\s*의\s*\d+)?|별표\s*\d*|부칙|문\s*\d+)")
_RRF_K = 60.0
_MUST_MATCH_SPECIFIC_TERMS: dict[str, tuple[str, ...]] = {
    "요금": ("요금", "주차료", "사용료", "이용료", "부담금"),
    "주차료": ("주차료", "요금", "사용료"),
    "가격": ("가격", "단가", "시세", "매매가"),
    "출시일": ("출시일", "출시", "발매일"),
    "우승팀": ("우승팀", "우승"),
    "날씨": ("날씨", "기온", "강수"),
    "주가": ("주가", "시세"),
    "비트코인": ("비트코인", "암호화폐"),
    "대통령": ("대통령",),
}


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
    effective_query: str = ""
    followup_rewritten: bool = False
    sub_queries: list[str] = field(default_factory=list)
    used_neural_dense: bool = False
    used_reranker: bool = False
    xref_hops: int = 0
    elapsed_ms: float = 0.0


def _extract_query_features(query: str) -> tuple[list[str], list[str], list[str], list[str], bool]:
    """Return (substantive_keywords, expanded_synonyms, all_stems, clause_refs, wants_form)."""
    clause_refs = [re.sub(r"\s+", "", m.group(1)) for m in _CLAUSE_RE.finditer(query)]
    wants_form = any(w in query for w in _FORM_INTENT_WORDS)

    morphs = tokenize_korean_morphemes(query)
    all_stems: list[str] = []
    substantive: list[str] = []
    for tok in morphs:
        if len(tok) >= 2 and tok not in all_stems:
            all_stems.append(tok)
        if len(tok) >= 2 and tok not in STOPWORDS and tok not in substantive:
            substantive.append(tok)

    # Also detect adjacent two-word compound forms (e.g. "위임 목사" -> "위임목사")
    words_seq = [w.lower() for w in _WORD_RE.findall(query)]
    for i in range(len(words_seq) - 1):
        comp = words_seq[i] + words_seq[i + 1]
        if len(comp) >= 4 and comp not in substantive:
            stem_c = _KOR_PARTICLES.sub("", comp)
            if stem_c and stem_c not in STOPWORDS and len(stem_c) >= 3:
                for cand_c in (comp, stem_c):
                    if cand_c in (
                        "위임목사", "담임목사", "시무장로", "무임장로", "안수집사",
                        "서리집사", "시무권사", "위임전결", "전결권자", "지출결의",
                        "유급직원", "이명증서", "학습세례", "유아세례", "재정부장",
                    ) and cand_c not in substantive:
                        substantive.append(cand_c)

    if not substantive:
        substantive = list(all_stems)

    extra_primary, synonyms = expand_colloquial_and_synonyms(substantive, query)
    # Keep user query stems clean in `substantive` (for accurate coverage gating),
    # and prepend high-precision colloquial intent terms to `synonyms` for strong recall boost.
    merged_syns: list[str] = []
    for t in [*extra_primary, *synonyms]:
        if t not in substantive and t not in merged_syns:
            merged_syns.append(t)

    return substantive, merged_syns[:18], all_stems, clause_refs, wants_form


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


def _lexical_candidates_for_subquery(
    db: Database,
    notebook_id: str,
    sub_query: str,
    allowed_doc_ids: list[str],
    doc_map: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str], list[str], list[str], bool]:
    """Run Kiwi-tokenized FTS5 BM25 + exact clause & space-bridged lookup for a single subquery."""
    substantive, synonyms, all_stems, clause_refs, wants_form = _extract_query_features(sub_query)
    q_bigrams = _char_bigrams(substantive or all_stems)
    syn_bigrams = _char_bigrams(synonyms)

    fts_terms: list[str] = []
    for c in clause_refs:
        e = _fts_escape(c)
        if e:
            fts_terms.append(e)
    for k in (substantive or all_stems)[:12]:
        e = _fts_escape(k)
        if e:
            fts_terms.append(e)
    for s in synonyms[:8]:
        e = _fts_escape(s)
        if e:
            fts_terms.append(e)
    for bg in list(q_bigrams | syn_bigrams)[:20]:
        fts_terms.append(_fts_escape("bg_" + bg))

    candidates: dict[int, dict[str, Any]] = {}
    placeholders = ",".join("?" for _ in allowed_doc_ids)

    with db.connect() as conn:
        if fts_terms:
            match_expr = " OR ".join(dict.fromkeys(fts_terms))
            sql = f"""
                SELECT c.id, c.doc_id, c.page_start, c.page_end, c.heading, c.section_path, c.content,
                       c.parent_key, c.context_header, c.parent_content, c.chunk_type,
                       bm25(chunks_fts) AS raw_bm25
                FROM chunks_fts
                JOIN chunks c ON c.id = chunks_fts.chunk_id
                WHERE chunks_fts MATCH ?
                  AND c.notebook_id = ?
                  AND c.doc_id IN ({placeholders})
                ORDER BY raw_bm25 ASC
                LIMIT 140
            """
            for r in conn.execute(sql, [match_expr, notebook_id, *allowed_doc_ids]).fetchall():
                d = dict(r)
                candidates[d["id"]] = d

        # Direct LIKE lookup for exact clause refs (제124조, 별표1, 부칙)
        for ref in clause_refs[:4]:
            rows = conn.execute(
                f"""
                SELECT id, doc_id, page_start, page_end, heading, section_path, content,
                       parent_key, context_header, parent_content, chunk_type, -11.0 AS raw_bm25
                FROM chunks
                WHERE notebook_id = ? AND doc_id IN ({placeholders})
                  AND (heading LIKE ? OR context_header LIKE ? OR content LIKE ?)
                LIMIT 25
                """,
                [notebook_id, *allowed_doc_ids, f"%{ref}%", f"%{ref}%", f"%{ref}%"],
            ).fetchall()
            for r in rows:
                d = dict(r)
                candidates.setdefault(d["id"], d)

        # Space-bridging fallback for 4-char Korean compounds (e.g., 위임목사 -> 위임%목사)
        for kw in substantive[:4]:
            if len(kw) == 4 and all("\uac00" <= ch <= "\ud7a3" for ch in kw):
                spaced_pat = f"%{kw[:2]} {kw[2:]}%"
                rows = conn.execute(
                    f"""
                    SELECT id, doc_id, page_start, page_end, heading, section_path, content,
                           parent_key, context_header, parent_content, chunk_type, -8.0 AS raw_bm25
                    FROM chunks
                    WHERE notebook_id = ? AND doc_id IN ({placeholders})
                      AND (heading LIKE ? OR content LIKE ?)
                    LIMIT 16
                    """,
                    [notebook_id, *allowed_doc_ids, spaced_pat, spaced_pat],
                ).fetchall()
                for r in rows:
                    d = dict(r)
                    candidates.setdefault(d["id"], d)

    kw_list = substantive or all_stems
    scored: list[dict[str, Any]] = []
    for cid, cand in candidates.items():
        ctx_hdr = cand.get("context_header") or ""
        text_full = f"{ctx_hdr} {cand['heading']} {cand['section_path']} {cand['content']}"
        text_lower = text_full.lower()
        text_nospace = re.sub(r"\s+", "", text_lower)
        heading_nospace = re.sub(r"\s+", "", f"{ctx_hdr} {cand['heading']}".lower())
        doc_info = doc_map[cand["doc_id"]]

        bm25_pos = max(0.0, -float(cand.get("raw_bm25") or 0.0))
        bm25_norm = min(bm25_pos / 12.0, 2.2)

        matched_kws = [k for k in kw_list if (k in text_lower or k in text_nospace)]
        matched_syns = [s for s in synonyms if (s in text_lower or s in text_nospace)]

        kw_cov = len(matched_kws) / max(1, len(kw_list))
        syn_bonus = min(len(matched_syns), 4) * 1.15

        heading_hits = sum(1 for k in kw_list if k in heading_nospace) + sum(
            0.7 for s in synonyms[:6] if s in heading_nospace
        )
        clause_hit = any(ref in text_nospace for ref in clause_refs)

        bg_hits = sum(1 for bg in q_bigrams if bg in text_nospace)
        bg_cov = bg_hits / max(1, len(q_bigrams)) if q_bigrams else 0.0

        # Structured Markdown table boost when query asks about tables/criteria/approval matrices
        table_bonus = 0.65 if (cand.get("chunk_type") == "table" and any(w in sub_query for w in ("표", "기준", "전결", "결재", "편성", "과정"))) else 0.0

        score = (
            bm25_norm * 1.35
            + kw_cov * 4.4
            + len(matched_kws) * 0.65
            + syn_bonus
            + heading_hits * 1.05
            + (3.6 if clause_hit else 0.0)
            + bg_cov * 1.65
            + table_bonus
            + (doc_info["priority"] / 100.0) * 0.22
        )
        # Penalize noisy Table of Contents dot-leaders
        if text_full.count("···") >= 3 or text_full.count("...") >= 4:
            score *= 0.22

        cand["lex_score"] = round(score, 4)
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

    scored.sort(key=lambda x: x["lex_score"], reverse=True)
    return scored, kw_list, synonyms, clause_refs, wants_form


def _expand_cross_references(
    db: Database,
    notebook_id: str,
    selected: list[dict[str, Any]],
    allowed_doc_ids: list[str],
    doc_map: dict[str, dict[str, Any]],
    max_hops: int = 2,
) -> tuple[list[dict[str, Any]], int]:
    """
    Follow outgoing legal cross-references (e.g., 제124조 -> 별표, 정관 제15조 준용)
    from top-3 retrieved clauses and append referenced target clauses/tables cleanly.
    """
    if not selected or max_hops <= 0:
        return selected, 0

    top_ids = [int(c["id"]) for c in selected[:3]]
    refs = db.get_chunk_refs_for_sources(top_ids)
    if not refs:
        return selected, 0

    seen_ids = {int(c["id"]) for c in selected}
    seen_parent_keys = {(c["doc_id"], c.get("parent_key") or "") for c in selected if c.get("parent_key")}
    added: list[dict[str, Any]] = []
    placeholders = ",".join("?" for _ in allowed_doc_ids)

    with db.connect() as conn:
        for ref in refs:
            if len(added) >= max_hops:
                break
            target = ref["ref_target"]
            hint = ref.get("target_doc_hint") or ""
            src_doc_id = ref["doc_id"]

            # Prefer hinted document (e.g. 정관 제15조), otherwise same document first
            target_doc_ids = list(allowed_doc_ids)
            if hint:
                hinted = [did for did in allowed_doc_ids if hint in doc_map[did]["title"]]
                if hinted:
                    target_doc_ids = hinted
            else:
                target_doc_ids = [src_doc_id] if src_doc_id in doc_map else allowed_doc_ids

            t_ph = ",".join("?" for _ in target_doc_ids)
            row = conn.execute(
                f"""
                SELECT id, doc_id, page_start, page_end, heading, section_path, content,
                       parent_key, context_header, parent_content, chunk_type
                FROM chunks
                WHERE notebook_id = ? AND doc_id IN ({t_ph})
                  AND (parent_key = ? OR heading LIKE ? OR context_header LIKE ?)
                ORDER BY CASE WHEN parent_key = ? THEN 0 ELSE 1 END, id ASC
                LIMIT 1
                """,
                [notebook_id, *target_doc_ids, target, f"%{target}%", f"%{target}%", target],
            ).fetchone()
            if not row:
                continue
            d = dict(row)
            if d["id"] in seen_ids:
                continue
            pk = (d["doc_id"], d.get("parent_key") or "")
            if pk[1] and pk in seen_parent_keys:
                continue
            doc_info = doc_map[d["doc_id"]]
            d["doc_title"] = doc_info["title"]
            d["doc_category"] = doc_info["category"]
            d["doc_priority"] = doc_info["priority"]
            d["score"] = round(max(1.5, selected[-1]["score"] * 0.92), 4)
            d["matched_keywords"] = []
            d["matched_synonyms"] = []
            d["kw_coverage"] = 0.0
            d["bg_coverage"] = 0.0
            d["clause_hit"] = True
            d["via_xref"] = f"교차참조({target})"
            seen_ids.add(d["id"])
            if pk[1]:
                seen_parent_keys.add(pk)
            added.append(d)

    return [*selected, *added], len(added)


def _expand_parent_and_adjacent_context(db: Database, selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Parent-Child (Small-to-Big) expansion:
    - If a chunk belongs to a larger parent article (`parent_content`), promote the complete parent article
      (including all sub-items ①②③ and `다만,` exception provisos) while keeping total length clean.
    - Otherwise fall back to adjacent-chunk stitch for short chunks.
    """
    if not selected:
        return selected
    expanded: list[dict[str, Any]] = []
    seen_ids = {int(c["id"]) for c in selected}

    with db.connect() as conn:
        for idx, ch in enumerate(selected):
            item = dict(ch)
            p_content = (item.get("parent_content") or "").strip()
            if idx < 6 and p_content and len(p_content) > len(item["content"]) + 60 and len(p_content) <= 2200:
                item["content"] = p_content
            elif idx < 4 and len(item["content"]) < 720:
                nxt = conn.execute(
                    "SELECT id, doc_id, page_start, page_end, heading, content FROM chunks WHERE id = ? AND doc_id = ?",
                    (item["id"] + 1, item["doc_id"]),
                ).fetchone()
                if nxt and nxt["id"] not in seen_ids:
                    same_section = (not nxt["heading"]) or (nxt["heading"] == item["heading"]) or (
                        nxt["page_start"] <= item["page_end"] + 1
                    )
                    if same_section and len(item["content"]) + len(nxt["content"]) <= 1650:
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

    engine_tags = ["Kiwi 형태소"]
    if retrieval.used_neural_dense:
        engine_tags.append("로컬 신경망 벡터")
    if retrieval.used_reranker:
        engine_tags.append("Cross-Encoder 리랭킹")
    if retrieval.xref_hops > 0:
        engine_tags.append(f"교차참조 {retrieval.xref_hops}건")

    lines: list[str] = [
        f"## 즉시 원문 검색 결과 ({len(retrieval.chunks)}건)",
        f"> 질의: **{query}** · 검색 엔진: {' + '.join(engine_tags)} ({retrieval.elapsed_ms:.0f}ms)",
        "",
    ]
    if retrieval.followup_rewritten and retrieval.effective_query:
        lines.append(f"> 문맥 보강 검색어: `{retrieval.effective_query}`")
        lines.append("")

    for idx, c in enumerate(retrieval.chunks[:6], start=1):
        loc = f"p.{c['page_start']}" if c["page_start"] == c["page_end"] else f"p.{c['page_start']}~{c['page_end']}"
        sec = " · ".join(x for x in (c.get("section_path", ""), c.get("heading", "")) if x)
        xref_badge = f" · `{c['via_xref']}`" if c.get("via_xref") else ""
        lines.append(f"### {idx}. [{c['doc_title']}] {sec or '본문'} ({loc}){xref_badge}")
        excerpt = c["content"].strip()
        if len(excerpt) > 680:
            excerpt = excerpt[:680].rstrip() + "..."
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
    history: list[dict[str, Any]] | None = None,
) -> RetrievalResult:
    """
    Engine v4.0 SOTA Hybrid Korean Legal-Administrative Retrieval Pipeline:
    1. Multi-turn follow-up query resolution (`resolve_followup_query`)
    2. Compound multi-subject query decomposition (`decompose_compound_query`)
    3. Per-subquery Kiwi BM25 + Phrase/Synonym Expansion + Clause Lookup
    4. Optional local ONNX Dense Vector Search (`multilingual-e5-small`)
    5. Reciprocal Rank Fusion (RRF, k=60) + Parent-Article Deduplication
    6. Optional local ONNX Cross-Encoder Reranking (`jina-reranker-v2-multilingual`)
    7. Legal Cross-Reference Graph Hop (`제N조`, `별표`, `정관 준용`)
    8. Parent-Child (Small-to-Big) Full Clause Expansion + Grounding Gate
    """
    t0 = time.perf_counter()
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
            elapsed_ms=round((time.perf_counter() - t0) * 1000.0, 1),
        )

    doc_map = {d["id"]: d for d in ready_docs}
    allowed_doc_ids = list(doc_map.keys())

    # Step 1: Multi-turn follow-up resolution
    effective_query, followup_rewritten = resolve_followup_query(query, history)

    # Step 2: Multi-part query decomposition
    sub_queries = decompose_compound_query(effective_query)

    # Step 3 & 4: Run Lexical + Optional Dense retrieval across full query + sub-queries, fuse with RRF
    fused_candidates: dict[int, dict[str, Any]] = {}
    rrf_scores: dict[int, float] = {}
    all_kw_list: list[str] = []
    all_synonyms: list[str] = []
    all_clause_refs: list[str] = []
    wants_form = False
    used_dense = False

    query_runs = [effective_query] + ([sq for sq in sub_queries if sq != effective_query] if len(sub_queries) > 1 else [])

    for run_idx, q_text in enumerate(query_runs):
        weight = 1.0 if run_idx == 0 else 0.92
        lex_list, kws, syns, crefs, wf = _lexical_candidates_for_subquery(
            db, notebook_id, q_text, allowed_doc_ids, doc_map
        )
        if wf:
            wants_form = True
        for k in kws:
            if k not in all_kw_list:
                all_kw_list.append(k)
        for s in syns:
            if s not in all_synonyms:
                all_synonyms.append(s)
        for cr in crefs:
            if cr not in all_clause_refs:
                all_clause_refs.append(cr)

        for rank, item in enumerate([x for x in lex_list[:45] if x["lex_score"] >= 0.85], start=1):
            cid = int(item["id"])
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + weight * (1.0 / (_RRF_K + rank))
            if cid not in fused_candidates or item["lex_score"] > fused_candidates[cid].get("lex_score", 0.0):
                fused_candidates[cid] = item

        # Optional local ONNX Dense Vector channel (only on main query + sub-queries)
        if neural_engine.is_embed_installed():
            dense_hits = neural_engine.search_dense(db, notebook_id, q_text, allowed_doc_ids, top_n=35)
            if dense_hits:
                used_dense = True
                missing_ids = [cid for cid, _ in dense_hits if cid not in fused_candidates]
                if missing_ids:
                    for row in db.get_chunks_by_ids(missing_ids):
                        did = row["doc_id"]
                        if did not in doc_map:
                            continue
                        doc_info = doc_map[did]
                        row["doc_title"] = doc_info["title"]
                        row["doc_category"] = doc_info["category"]
                        row["doc_priority"] = doc_info["priority"]
                        row["lex_score"] = 0.0
                        row["score"] = 0.0
                        row["matched_keywords"] = []
                        row["matched_synonyms"] = []
                        row["kw_coverage"] = 0.0
                        row["bg_coverage"] = 0.0
                        row["clause_hit"] = False
                        fused_candidates[int(row["id"])] = row

                for rank, (cid, cos_sim) in enumerate(dense_hits, start=1):
                    if cid in fused_candidates and cos_sim >= 0.72:
                        rrf_scores[cid] = rrf_scores.get(cid, 0.0) + weight * 0.95 * (1.0 / (_RRF_K + rank))
                        fused_candidates[cid]["dense_sim"] = max(
                            float(fused_candidates[cid].get("dense_sim") or 0.0), round(cos_sim, 4)
                        )

    # Combine lexical relevance + normalized RRF fusion score
    ranked_pool: list[dict[str, Any]] = []
    max_rrf = max(rrf_scores.values()) if rrf_scores else 1.0
    for cid, cand in fused_candidates.items():
        rrf_norm = (rrf_scores.get(cid, 0.0) / max(1e-9, max_rrf)) * 4.5
        dense_boost = max(0.0, (float(cand.get("dense_sim") or 0.0) - 0.74) * 14.0)
        combined = float(cand.get("lex_score") or 0.0) * 0.72 + rrf_norm + dense_boost
        cand["score"] = round(combined, 4)
        ranked_pool.append(cand)

    ranked_pool.sort(key=lambda x: x["score"], reverse=True)

    # Step 6: Optional local ONNX Cross-Encoder Reranking over top-16 candidates
    used_reranker = False
    if neural_engine.is_rerank_installed() and len(ranked_pool) >= 2:
        top_n = ranked_pool[:16]
        passages = [f"{c.get('context_header') or ''} {c.get('heading') or ''}\n{c['content']}" for c in top_n]
        rerank_probs = neural_engine.rerank(effective_query, passages)
        if rerank_probs and len(rerank_probs) == len(top_n):
            used_reranker = True
            for item, prob in zip(top_n, rerank_probs):
                item["rerank_prob"] = round(prob, 4)
                item["score"] = round(item["score"] * 0.55 + prob * 6.5, 4)
            ranked_pool[:16] = sorted(top_n, key=lambda x: x["score"], reverse=True)

    # Select diverse top-K (deduplicating multiple child chunks of the same parent article!)
    selected: list[dict[str, Any]] = []
    per_doc_count: dict[str, int] = {}
    seen_parents: set[tuple[str, str]] = set()
    max_per_doc = 4 if len(allowed_doc_ids) > 1 else top_k
    base_k = max(1, top_k - 1) if len(ranked_pool) >= 3 else top_k

    for item in ranked_pool:
        if len(selected) >= base_k:
            break
        if item["score"] < 1.20:
            continue
        did = item["doc_id"]
        pk = (did, item.get("parent_key") or "")
        if pk[1] and pk in seen_parents:
            continue
        if per_doc_count.get(did, 0) >= max_per_doc:
            continue
        selected.append(item)
        per_doc_count[did] = per_doc_count.get(did, 0) + 1
        if pk[1]:
            seen_parents.add(pk)

    # Step 7: Legal Cross-Reference Graph Hop (brings in referenced 별표 / 제N조 / 정관)
    selected, xref_hops = _expand_cross_references(
        db, notebook_id, selected, allowed_doc_ids, doc_map, max_hops=min(2, max(0, top_k - len(selected) + 1))
    )

    # Step 8: Parent-Child (Small-to-Big) Full Clause Expansion
    selected = _expand_parent_and_adjacent_context(db, selected)

    # Match relevant forms/tables
    all_forms = db.list_forms(notebook_id, doc_ids=allowed_doc_ids)
    cited_pages = {(c["doc_id"], p) for c in selected for p in range(c["page_start"], c["page_end"] + 1)}
    scored_forms: list[tuple[float, dict[str, Any]]] = []
    for f in all_forms:
        ftext = re.sub(r"\s+", "", f"{f['title']} {f['category']} {f['sample_text'][:400]}".lower())
        ftitle = re.sub(r"\s+", "", f["title"].lower())
        f_score = 0.0
        for k in all_kw_list:
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

    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)

    if not selected and not matched_forms:
        return RetrievalResult(
            has_evidence=False,
            confidence=0.0,
            query_keywords=all_kw_list,
            clause_refs=all_clause_refs,
            wants_form=wants_form,
            chunks=[],
            forms=[],
            searched_doc_titles=searched_titles,
            effective_query=effective_query,
            followup_rewritten=followup_rewritten,
            sub_queries=sub_queries,
            used_neural_dense=used_dense,
            used_reranker=used_reranker,
            xref_hops=xref_hops,
            elapsed_ms=elapsed_ms,
        )

    best = selected[0] if selected else None
    best_kw_cnt = len(best.get("matched_keywords", [])) if best else 0
    best_syn_cnt = len(best.get("matched_synonyms", [])) if best else 0
    best_kw_cov = float(best.get("kw_coverage") or 0.0) if best else 0.0
    best_bg_cov = float(best.get("bg_coverage") or 0.0) if best else 0.0
    best_lex = float(best.get("lex_score") or 0.0) if best else 0.0
    best_dense = float(best.get("dense_sim") or 0.0) if best else 0.0
    best_rerank = float(best.get("rerank_prob") or 0.0) if best else 0.0
    best_score = float(best.get("score") or 0.0) if best else 0.0

    # Strict Grounding Gate: blocks out-of-corpus hallucinations cleanly even with dense embeddings
    has_evidence = True
    if not selected and matched_forms:
        has_evidence = True
        confidence = 0.65
    elif best is not None:
        neural_strong = (best_rerank >= 0.62 and best_dense >= 0.80) or (best_dense >= 0.85 and best_kw_cnt >= 1)
        if best.get("clause_hit") or neural_strong:
            has_evidence = True
        elif best_kw_cnt == 0 and best_syn_cnt == 0 and best_bg_cov < 0.45:
            has_evidence = False
        elif len(all_kw_list) >= 2 and best_kw_cov < 0.38 and best_syn_cnt == 0 and best_bg_cov < 0.50:
            has_evidence = False
        elif best_lex < 1.85 and not neural_strong and not matched_forms:
            has_evidence = False

        # Core transactional/external entity check: if user asks about specific fee/weather/stock/release
        # terms, at least one alias must genuinely exist in the top retrieved evidence!
        if has_evidence and selected:
            top_joined = re.sub(
                r"\s+",
                "",
                " ".join(
                    f"{c.get('heading', '')} {c.get('content', '')} {c.get('parent_content') or ''}"
                    for c in selected[:3]
                ).lower(),
            )
            for req_term, aliases in _MUST_MATCH_SPECIFIC_TERMS.items():
                if req_term in all_kw_list or req_term in effective_query:
                    if not any(a in top_joined for a in aliases):
                        has_evidence = False
                        break

        confidence = min(1.0, round(best_score / 7.5, 2))
    else:
        has_evidence = False
        confidence = 0.0

    return RetrievalResult(
        has_evidence=has_evidence,
        confidence=confidence if has_evidence else 0.0,
        query_keywords=all_kw_list,
        clause_refs=all_clause_refs,
        wants_form=wants_form,
        chunks=selected[:top_k] if has_evidence else [],
        forms=matched_forms if has_evidence else [],
        searched_doc_titles=searched_titles,
        effective_query=effective_query,
        followup_rewritten=followup_rewritten,
        sub_queries=sub_queries,
        used_neural_dense=used_dense,
        used_reranker=used_reranker,
        xref_hops=xref_hops,
        elapsed_ms=elapsed_ms,
    )
