from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import io
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator
from xml.sax.saxutils import escape as xml_escape

import docx
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Cm, Pt, RGBColor
import pymupdf

from core.config import DEFAULT_NOTEBOOK_ID
from core.database import Database
from core.forms import _hwpx_para, _hwpx_table
from core.ingest import ingest_file
from core.retriever import retrieve
from core.std_config import DEFAULT_PDF_TEMPLATE, load_std_config, resolve_approval_preset
from core.std_engine import IMAGE_EXTENSIONS
from core.std_store import StandardizationStore, get_std_publications_dir
from server.cli_providers import load_ai_config, stream_cli_with_failover


def _find_headless_browser() -> str:
    candidates = [
        shutil.which("msedge"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        shutil.which("chrome"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return ""


def _esc(val: Any) -> str:
    return html.escape(str(val or ""), quote=True)


def _build_approval_table_html(slots: list[str], compact: bool = False) -> str:
    safe_slots = [s for s in (slots or ["총무", "부장", "지도교역자", "당회장"]) if str(s).strip()]
    ths = "".join(f"<th>{_esc(s)}</th>" for s in safe_slots)
    h_px = "34px" if compact else "42px"
    tds = "".join(f'<td style="height:{h_px};"></td>' for _ in safe_slots)
    cls = "approval-box" if compact else "approval-box cover-approval-box"
    return (
        f'<table class="{cls}">'
        f'<tr><th rowspan="2" class="approval-label">결<br/>재</th>{ths}</tr>'
        f"<tr>{tds}</tr>"
        f"</table>"
    )


def _collect_board_image_attachments(submissions: list[dict[str, Any]], max_images: int = 8) -> list[dict[str, Any]]:
    """Prepare resized image previews (data URI + path) for inclusion in publication PDF/DOCX appendices."""
    attachments: list[dict[str, Any]] = []
    try:
        from PIL import Image, ImageOps
    except Exception:
        return attachments

    for s in submissions:
        if len(attachments) >= max_images:
            break
        sp = (s.get("stored_path") or "").strip()
        if not sp:
            continue
        p = Path(sp)
        if not p.exists() or p.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        try:
            with Image.open(str(p)) as im:
                im = ImageOps.exif_transpose(im)
                if getattr(im, "is_animated", False):
                    im.seek(0)
                rgb = im.convert("RGB")
                w, h = rgb.size
                if w > 1200:
                    nh = max(1, int(h * (1200.0 / float(w))))
                    rgb = rgb.resize((1200, nh), Image.Resampling.LANCZOS)
                buf = io.BytesIO()
                rgb.save(buf, format="JPEG", quality=84, optimize=True)
                b64 = base64.b64encode(buf.getvalue()).decode("ascii")
                attachments.append(
                    {
                        "title": s.get("title") or p.name,
                        "file_name": s.get("file_name") or p.name,
                        "author_label": s.get("author_label") or "",
                        "summary": s.get("ai_summary") or "",
                        "path": str(p),
                        "data_uri": f"data:image/jpeg;base64,{b64}",
                    }
                )
        except Exception:
            continue
    return attachments


def _flatten_manuscript_articles(manuscript: dict[str, Any] | None) -> list[dict[str, str]]:
    if not isinstance(manuscript, dict):
        return []
    out: list[dict[str, str]] = []
    for ch in manuscript.get("chapters") or []:
        ch_title = str(ch.get("title") or "")
        for art in ch.get("articles") or []:
            num = str(art.get("number") or "").strip()
            title = str(art.get("title") or "").strip()
            body = str(art.get("body") or "").strip()
            pts = [str(x).strip() for x in (art.get("points") or []) if str(x).strip()]
            full_text = body + ("\n" + "\n".join(f"· {x}" for x in pts) if pts else "")
            key = re.sub(r"\s+", "", title).lower() or re.sub(r"\s+", "", num).lower()
            out.append(
                {
                    "key": key,
                    "chapter": ch_title,
                    "label": f"{num} ({title})" if (num and title) else (num or title or "조항"),
                    "text": full_text.strip(),
                }
            )
    return out


def build_manuscript_diff_report(
    prev_manuscript: dict[str, Any] | None,
    curr_manuscript: dict[str, Any],
    prev_version: str = "",
    curr_version: str = "",
) -> dict[str, Any]:
    """Generate a Korean 신·구조문 대조표 (before vs after comparison table) across manuscript revisions."""
    if not prev_manuscript or not prev_manuscript.get("chapters"):
        return {}
    prev_items = _flatten_manuscript_articles(prev_manuscript)
    curr_items = _flatten_manuscript_articles(curr_manuscript)
    prev_map = {x["key"]: x for x in prev_items if x["key"]}
    curr_map = {x["key"]: x for x in curr_items if x["key"]}

    rows: list[dict[str, str]] = []
    added = modified = removed = unchanged = 0

    for item in curr_items:
        k = item["key"]
        if k not in prev_map:
            added += 1
            rows.append({"article": item["label"], "status": "신설", "before": "(신설)", "after": item["text"]})
        else:
            old = prev_map[k]
            norm_old = re.sub(r"\s+", " ", old["text"]).strip()
            norm_new = re.sub(r"\s+", " ", item["text"]).strip()
            if norm_old == norm_new:
                unchanged += 1
            else:
                modified += 1
                rows.append({"article": item["label"], "status": "개정", "before": old["text"], "after": item["text"]})

    for item in prev_items:
        if item["key"] and item["key"] not in curr_map:
            removed += 1
            rows.append({"article": item["label"], "status": "삭제", "before": item["text"], "after": "(삭제)"})

    return {
        "prev_version": prev_version,
        "curr_version": curr_version,
        "added_count": added,
        "modified_count": modified,
        "removed_count": removed,
        "unchanged_count": unchanged,
        "rows": rows[:60],
    }


_NUM_RULE_RE = re.compile(r"(\d+(?:,\d{3})*(?:\.\d+)?\s*(?:만\s*원|억\s*원|원|일|개월|년|주|%|명|호|회)|2/3|3분의\s*2|과반수|만장일치)")
_AUTH_TERMS = ("당회장", "당회", "제직회", "공동의회", "노회", "총회", "재정부장", "재정부", "위원장", "부서장", "지도교역자", "위임전결")


def run_v4_law_conflict_audit(
    db: Database,
    board: dict[str, Any],
    submissions: list[dict[str, Any]],
    vote_summary: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Cross-audit draft materials against superior church laws (총회헌법 > 정관 > 시행세칙) using Engine v4.0."""
    query_seed = (
        f"{board['title']} {board['category']} "
        + " ".join(v["cluster_title"] for v in vote_summary[:3])
        + " "
        + " ".join(s["title"] for s in submissions[:4])
    ).strip()
    law_retrieval = retrieve(db, DEFAULT_NOTEBOOK_ID, query_seed, None, 7)

    draft_blob = "\n".join(
        [board.get("title", ""), board.get("description", "")]
        + [v.get("adopted_content", "") for v in vote_summary]
        + [(s.get("notes") or "") + "\n" + (s.get("extracted_text") or "")[:1200] for s in submissions[:8]]
    )
    draft_nums = {re.sub(r"\s+", "", m.group(0)) for m in _NUM_RULE_RE.finditer(draft_blob)}
    draft_auths = {t for t in _AUTH_TERMS if t in draft_blob}

    law_audit: list[dict[str, Any]] = []
    for ch in law_retrieval.chunks[:6]:
        loc = f"p.{ch['page_start']}"
        sec = " / ".join(x for x in (ch.get("section_path", ""), ch.get("heading", "")) if x)
        law_text = ch.get("parent_content") or ch.get("content") or ""
        law_nums = {re.sub(r"\s+", "", m.group(0)) for m in _NUM_RULE_RE.finditer(law_text)}
        law_auths = {t for t in _AUTH_TERMS if t in law_text}

        status = "정합 확인"
        reasons: list[str] = []

        # Compare concrete numeric rules sharing same unit (e.g., 7일 vs 3일, 2/3 vs 과반수)
        if law_nums and draft_nums:
            for unit in ("일", "개월", "년", "만원", "원", "%"):
                l_u = {n for n in law_nums if n.endswith(unit)}
                d_u = {n for n in draft_nums if n.endswith(unit)}
                if l_u and d_u and not (l_u & d_u):
                    status = "충돌 주의"
                    reasons.append(
                        f"수치·기한 차이 감지 — 상위 법규({', '.join(sorted(l_u)[:2])}) vs 초안({', '.join(sorted(d_u)[:2])})"
                    )
                    break
            quorum_l = {n for n in law_nums if n in ("2/3", "3분의2", "과반수", "만장일치")}
            quorum_d = {n for n in draft_nums if n in ("2/3", "3분의2", "과반수", "만장일치")}
            if quorum_l and quorum_d and not (quorum_l & quorum_d):
                status = "충돌 주의"
                reasons.append(f"의결 정족수 차이 감지 — 상위 법규({', '.join(quorum_l)}) vs 초안({', '.join(quorum_d)})")

        # Check whether superior law requires higher authority (당회/제직회/공동의회/노회) not referenced in draft
        critical_auths = {"공동의회", "노회", "당회", "제직회", "당회장"}
        missing_auths = (law_auths & critical_auths) - draft_auths
        if status == "정합 확인" and missing_auths and draft_blob.strip():
            status = "보완 권고"
            reasons.append(f"상위 조항의 의결·결재 주체({', '.join(sorted(missing_auths)[:2])}) 명시 권장")

        snippet = ch["content"][:140].replace("\n", " ").strip()
        note_head = " · ".join(reasons) + " | " if reasons else ""
        law_audit.append(
            {
                "source": f"{ch['doc_title']} ({loc})",
                "status": status,
                "note": f"{note_head}[{sec or '관련 조항'}] {snippet}...",
            }
        )
    return law_audit


def _render_publication_html(
    board: dict[str, Any],
    manuscript: dict[str, Any],
    law_audit: list[dict[str, Any]],
    vote_summary: list[dict[str, Any]],
    version_label: str,
    created_by: str,
    pdf_template: dict[str, Any] | None = None,
    approval_preset: dict[str, Any] | None = None,
    image_attachments: list[dict[str, Any]] | None = None,
    diff_report: dict[str, Any] | None = None,
    comments_summary: list[dict[str, Any]] | None = None,
) -> str:
    tpl = {**DEFAULT_PDF_TEMPLATE, **(pdf_template or {})}
    ap_preset = approval_preset or {
        "name": "부서 기본 결재선 (위임전결규정 별표)",
        "slots": ["총무", "부장", "지도교역자", "당회장"],
        "basis": "시행세칙 제11장 위임전결규정 제124조·제127조 [별표]",
    }
    approval_slots: list[str] = list(ap_preset.get("slots") or ["총무", "부장", "지도교역자", "당회장"])
    approval_chain_text = " → ".join(approval_slots)
    accent = str(tpl.get("accent_color") or "#0f4c81")
    church_name = str(tpl.get("church_name") or "목포사랑의교회")
    denom_header = str(tpl.get("denomination_header") or "대한예수교장로회 · 목포사랑의교회 공식 행정 표준 규정집")
    committee_label = str(tpl.get("committee_label") or "행정표준화위원회")
    footer_left = str(tpl.get("footer_left") or f"{church_name} {committee_label}")
    footer_right = str(tpl.get("footer_right") or "공식 정규 행정 문서 (위임전결규정 준용)")
    default_recipient = str(tpl.get("default_recipient") or f"{church_name} 당회장 귀하")
    default_stmt = str(tpl.get("default_submit_statement") or "위와 같이 제출(신청)하오니 허락하여 주시기 바랍니다.")
    show_cover_approval = bool(tpl.get("show_cover_approval_box", True))
    show_deleg_note = bool(tpl.get("show_delegation_footnote", True))
    deleg_note = str(tpl.get("delegation_footnote") or "")

    today_str = datetime.now().strftime("%Y년 %m월 %d일")
    doc_title = manuscript.get("title") or board["title"]
    subtitle = manuscript.get("subtitle") or f"{board['category']} · {board['work_type']}"
    exec_summary = manuscript.get("executive_summary") or board.get("description") or ""
    chapters = manuscript.get("chapters") or []
    std_forms = manuscript.get("standard_forms") or []
    checklists = manuscript.get("checklists") or []

    # Build Table of Contents items
    toc_rows = []
    for idx, ch in enumerate(chapters, start=1):
        toc_rows.append(
            f'<tr><td class="toc-num">제{idx}장</td><td class="toc-title">{_esc(ch.get("title", ""))}</td>'
            f'<td class="toc-note">{len(ch.get("articles") or [])}개 조항</td></tr>'
        )
    if std_forms:
        toc_rows.append(
            f'<tr><td class="toc-num">부록 1</td><td class="toc-title">표준 행정 서식 및 결재 양식</td>'
            f'<td class="toc-note">{len(std_forms)}종</td></tr>'
        )
    if checklists:
        toc_rows.append(
            f'<tr><td class="toc-num">부록 2</td><td class="toc-title">실무 절차 점검표 (체크리스트)</td>'
            f'<td class="toc-note">{len(checklists)}개 영역</td></tr>'
        )
    toc_rows.append(
        '<tr><td class="toc-num">부록 3</td><td class="toc-title">교회 법규 위계 검수 결과 및 투표 합의 이력</td>'
        f'<td class="toc-note">{len(vote_summary)}건 합의</td></tr>'
    )
    img_list = image_attachments or []
    if img_list:
        toc_rows.append(
            f'<tr><td class="toc-num">부록 4</td><td class="toc-title">현장 참고 이미지 및 제출 서식 사본</td>'
            f'<td class="toc-note">{len(img_list)}장</td></tr>'
        )
    diff_rows = (diff_report or {}).get("rows") or []
    if diff_rows:
        toc_rows.append(
            f'<tr><td class="toc-num">부록 {5 if img_list else 4}</td><td class="toc-title">신·구조문 대조표 ({_esc(diff_report.get("prev_version", ""))} → {_esc(version_label)})</td>'
            f'<td class="toc-note">{len(diff_rows)}건 변경</td></tr>'
        )

    # Build Law Hierarchy Audit Rows
    audit_html_rows = []
    for item in law_audit:
        st = item.get("status", "정합")
        if "충돌" in st:
            badge_cls = "badge-conflict"
        elif "정합" in st or "적합" in st:
            badge_cls = "badge-ok"
        else:
            badge_cls = "badge-warn"
        audit_html_rows.append(
            f"<tr>"
            f'<td style="width:24%;font-weight:600;">{_esc(item.get("source", "관련 법규"))}</td>'
            f'<td style="width:14%;text-align:center;"><span class="{badge_cls}">{_esc(st)}</span></td>'
            f'<td>{_esc(item.get("note", ""))}</td>'
            f"</tr>"
        )
    if not audit_html_rows:
        audit_html_rows.append(
            '<tr><td>총회헌법 · 정관 · 시행세칙</td><td style="text-align:center;"><span class="badge-ok">정합</span></td>'
            '<td>상위 교단 헌법 및 개교회 정관과 직접 충돌하는 조항이 발견되지 않았습니다.</td></tr>'
        )

    # Build Chapters HTML
    chapters_html: list[str] = []
    for ch_idx, ch in enumerate(chapters, start=1):
        ch_title = ch.get("title") or f"제{ch_idx}장"
        if not ch_title.startswith("제"):
            ch_title = f"제{ch_idx}장 {ch_title}"
        intro = ch.get("summary") or ""
        art_blocks: list[str] = []
        for a_idx, art in enumerate(ch.get("articles") or [], start=1):
            a_no = art.get("number") or f"제{a_idx}조"
            a_title = art.get("title") or ""
            a_body = art.get("body") or ""
            a_points = art.get("points") or []
            pts_html = ""
            if a_points:
                pts_html = "<ol class='art-list'>" + "".join(f"<li>{_esc(p)}</li>" for p in a_points) + "</ol>"
            note_html = ""
            if art.get("practical_tip"):
                note_html = f'<div class="tip-box"><strong>실무 적용 가이드:</strong> {_esc(art["practical_tip"])}</div>'
            art_blocks.append(
                f'<div class="article">'
                f'<div class="article-head"><span class="art-no">{_esc(a_no)}</span> '
                f'<span class="art-title">{_esc(a_title)}</span></div>'
                f'{f"<p class=art-body>{_esc(a_body)}</p>" if a_body else ""}'
                f"{pts_html}{note_html}"
                f"</div>"
            )
        # Optional chapter table
        tbl_html = ""
        if ch.get("table") and ch["table"].get("headers"):
            headers = ch["table"]["headers"]
            rows = ch["table"].get("rows") or []
            th = "".join(f"<th>{_esc(h)}</th>" for h in headers)
            tr = "".join(
                "<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in r) + "</tr>"
                for r in rows
            )
            tbl_html = f'<table class="data-table"><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>'

        chapters_html.append(
            f'<section class="chapter">'
            f'<div class="chapter-header"><span class="chapter-num">CHAPTER {ch_idx:02d}</span><h2>{_esc(ch_title)}</h2></div>'
            f'{f"<p class=chapter-intro>{_esc(intro)}</p>" if intro else ""}'
            f'{"".join(art_blocks)}{tbl_html}'
            f"</section>"
        )

    # Build Standard Forms HTML (each crisp printable A4 form box with church approval line)
    form_approval_html = _build_approval_table_html(approval_slots, compact=True)
    deleg_html = f'<p class="deleg-note">{_esc(deleg_note)}</p>' if (show_deleg_note and deleg_note) else ""
    forms_html: list[str] = []
    for f_idx, fm in enumerate(std_forms, start=1):
        f_title = fm.get("title") or f"표준 서식 제{f_idx}호"
        f_purpose = fm.get("purpose") or ""
        f_fields = fm.get("fields") or ["성명", "직분", "소속 부서", "연락처", "내용 및 사유"]
        f_rows = "".join(
            f'<tr><th style="width:28%;">{_esc(fld)}</th><td style="height:26px;"></td></tr>'
            for fld in f_fields
        )
        forms_html.append(
            f'<div class="form-sheet">'
            f'<div class="form-top">'
            f'  <div class="form-head-left"><div class="form-code">표준 서식 제{f_idx}호</div><h3>{_esc(f_title)}</h3>'
            f'  {f"<p class=form-purpose>{_esc(f_purpose)}</p>" if f_purpose else ""}</div>'
            f'  {form_approval_html}'
            f"</div>"
            f'<table class="form-grid"><tbody>{f_rows}</tbody></table>'
            f"{deleg_html}"
            f'<div class="form-footer">'
            f'  <p class="form-stmt">{_esc(default_stmt)}</p>'
            f'  <p class="form-date">20    년      월      일</p>'
            f'  <p class="form-sign">신청인(작성자): ____________________ (인)</p>'
            f'  <p class="form-recipient">{_esc(default_recipient)}</p>'
            f"</div>"
            f"</div>"
        )

    # Build Checklists HTML
    checklists_html = ""
    if checklists:
        chk_blocks = []
        for ck in checklists:
            items = "".join(f'<li><span class="chk-box"></span> {_esc(it)}</li>' for it in (ck.get("items") or []))
            chk_blocks.append(
                f'<div class="chk-card"><h4>{_esc(ck.get("title", "실무 점검 항목"))}</h4><ul class="chk-list">{items}</ul></div>'
            )
        checklists_html = (
            '<section class="chapter page-break">'
            '<div class="chapter-header"><span class="chapter-num">APPENDIX 02</span><h2>부록 2. 실무 절차 점검표 (체크리스트)</h2></div>'
            + "".join(chk_blocks)
            + "</section>"
        )

    # Build Voting Consensus Appendix
    vote_rows_html = []
    for vs in vote_summary:
        vote_rows_html.append(
            f"<tr>"
            f'<td style="font-weight:600;">{_esc(vs.get("cluster_title", ""))}</td>'
            f'<td>{_esc(vs.get("adopted_title", ""))}</td>'
            f'<td style="text-align:center;">{_esc(vs.get("votes", 0))}표 / 총 {_esc(vs.get("total_votes", 0))}표</td>'
            f"</tr>"
        )
    if not vote_rows_html:
        vote_rows_html.append('<tr><td colspan="3" style="text-align:center;color:#71717a;">수집된 원안 및 개선 의견을 종합하여 편찬함</td></tr>')

    # Build Reference Images Appendix HTML
    images_html = ""
    if img_list:
        cards = []
        for i_idx, img in enumerate(img_list, start=1):
            note_html = f'<p class="ref-img-note">{_esc(img["summary"])}</p>' if img.get("summary") else ""
            cards.append(
                f'<div class="ref-img-card">'
                f'<div class="ref-img-cap"><strong>참고 자료 {i_idx}. {_esc(img["title"])}</strong>'
                f' <span>({_esc(img["file_name"])})</span></div>'
                f'<img src="{img["data_uri"]}" alt="{_esc(img["title"])}" />'
                f"{note_html}"
                f"</div>"
            )
        images_html = (
            '<section class="chapter page-break">'
            '<div class="chapter-header"><span class="chapter-num">APPENDIX 04</span><h2>부록 4. 현장 참고 이미지 및 제출 서식 사본</h2></div>'
            + "".join(cards)
            + "</section>"
        )

    # Build Revision Comparison (신·구조문 대조표) HTML
    diff_html = ""
    if diff_rows:
        d_app_no = 5 if img_list else 4
        d_trs = []
        for dr in diff_rows:
            st = dr.get("status", "개정")
            bcls = "badge-ok" if st == "신설" else ("badge-conflict" if st == "삭제" else "badge-warn")
            d_trs.append(
                f"<tr>"
                f'<td style="width:18%;font-weight:600;">{_esc(dr.get("article", ""))}<br/><span class="{bcls}" style="margin-top:4px;">{_esc(st)}</span></td>'
                f'<td style="width:41%;white-space:pre-line;color:#52525b;">{_esc(dr.get("before", ""))}</td>'
                f'<td style="width:41%;white-space:pre-line;color:#18181b;">{_esc(dr.get("after", ""))}</td>'
                f"</tr>"
            )
        diff_html = (
            '<section class="chapter page-break">'
            f'<div class="chapter-header"><span class="chapter-num">APPENDIX 0{d_app_no}</span>'
            f'<h2>부록 {d_app_no}. 신·구조문 대조표 ({_esc(diff_report.get("prev_version", "이전 판본"))} → {_esc(version_label)})</h2></div>'
            f'<p class="chapter-intro">당회·제직회 보고용 개정 비교표 — 신설 {diff_report.get("added_count", 0)}건 · 개정 {diff_report.get("modified_count", 0)}건 · 삭제 {diff_report.get("removed_count", 0)}건 · 현행 유지 {diff_report.get("unchanged_count", 0)}건</p>'
            f'<table class="data-table"><thead><tr><th>조항 / 구분</th><th>현행 ({_esc(diff_report.get("prev_version", "이전"))})</th><th>개정안 ({_esc(version_label)})</th></tr></thead>'
            f'<tbody>{"".join(d_trs)}</tbody></table>'
            "</section>"
        )

    # Build Improvement Comments Summary Rows for Session Report
    cmt_rows_html = ""
    if comments_summary:
        c_trs = "".join(
            f'<tr><td style="width:16%;">{_esc(c.get("kind", "개선"))}</td>'
            f'<td style="width:18%;">{_esc(c.get("author_label", ""))}</td>'
            f'<td>{_esc(c.get("content", ""))}</td></tr>'
            for c in comments_summary[:15]
        )
        cmt_rows_html = (
            '<h3 style="font-size:11pt;margin:18px 0 6px 0;">교역자 현장 개선 의견 반영 내역</h3>'
            '<table class="data-table"><thead><tr><th>유형</th><th>작성자</th><th>의견 내용</th></tr></thead>'
            f"<tbody>{c_trs}</tbody></table>"
        )

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="UTF-8" />
<title>{_esc(doc_title)} ({_esc(version_label)})</title>
<style>
  @page {{
    size: A4;
    margin: 20mm 18mm 20mm 18mm;
  }}
  @page :first {{
    margin: 0;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 0;
    font-family: "Pretendard", "Malgun Gothic", "Apple SD Gothic Neo", sans-serif;
    color: #18181b;
    font-size: 10.2pt;
    line-height: 1.68;
    word-break: keep-all;
    overflow-wrap: break-word;
    background: #ffffff;
  }}
  .cover {{
    height: 296mm;
    padding: 26mm 24mm 22mm 24mm;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    page-break-after: always;
    background: linear-gradient(180deg, #fafaf9 0%, #ffffff 38%, #ffffff 100%);
    border-left: 7mm solid {accent};
  }}
  .cover-top {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid #d4d4d8;
    padding-bottom: 12px;
    font-size: 9.5pt;
    color: #52525b;
    letter-spacing: 0.04em;
  }}
  .cover-ver {{
    background: #18181b;
    color: #fff;
    padding: 3px 10px;
    border-radius: 4px;
    font-weight: 700;
    font-size: 9pt;
  }}
  .cover-main {{
    margin: auto 0;
    padding: 12mm 0;
  }}
  .cover-kicker {{
    color: {accent};
    font-size: 10.5pt;
    font-weight: 700;
    letter-spacing: 0.1em;
    margin-bottom: 10px;
  }}
  .cover-title {{
    font-size: 27pt;
    font-weight: 800;
    line-height: 1.28;
    letter-spacing: -0.02em;
    color: #18181b;
    margin: 0 0 12px 0;
  }}
  .cover-sub {{
    font-size: 12.5pt;
    color: #52525b;
    margin: 0 0 20px 0;
  }}
  .cover-summary {{
    border-left: 3px solid {accent};
    background: #f7f7f5;
    padding: 14px 18px;
    font-size: 10.2pt;
    color: #3f3f46;
    line-height: 1.72;
  }}
  .cover-approval-wrap {{
    display: flex;
    justify-content: flex-end;
    margin-top: 18px;
  }}
  .cover-approval-box th, .cover-approval-box td {{
    min-width: 56px;
    padding: 4px 10px;
  }}
  .cover-meta {{
    width: 100%;
    border-collapse: collapse;
    margin-top: 22px;
    font-size: 9.5pt;
  }}
  .cover-meta th {{
    width: 22%;
    text-align: left;
    padding: 8px 10px;
    background: #f7f7f5;
    border: 1px solid #e4e4e7;
    color: #52525b;
    font-weight: 600;
  }}
  .cover-meta td {{
    padding: 8px 10px;
    border: 1px solid #e4e4e7;
    color: #18181b;
  }}
  .cover-bottom {{
    border-top: 2px solid #18181b;
    padding-top: 12px;
    display: flex;
    justify-content: space-between;
    font-size: 9.5pt;
    font-weight: 600;
    color: #27272a;
  }}
  .page-break {{ page-break-before: always; }}
  .running-bar {{
    display: flex;
    justify-content: space-between;
    border-bottom: 1px solid #e4e4e7;
    padding-bottom: 6px;
    margin-bottom: 18px;
    font-size: 8.5pt;
    color: #71717a;
  }}
  .section-h {{
    font-size: 15pt;
    font-weight: 700;
    color: #18181b;
    border-bottom: 2px solid #18181b;
    padding-bottom: 6px;
    margin: 0 0 14px 0;
  }}
  .toc-table, .data-table {{
    width: 100%;
    border-collapse: collapse;
    margin: 10px 0 22px 0;
    font-size: 9.5pt;
  }}
  .toc-table td {{
    padding: 8px 10px;
    border-bottom: 1px solid #e4e4e7;
  }}
  .toc-num {{ width: 16%; font-weight: 700; color: #0f4c81; }}
  .toc-title {{ font-weight: 600; color: #18181b; }}
  .toc-note {{ width: 18%; text-align: right; color: #71717a; font-size: 8.8pt; }}
  .data-table th {{
    background: #f4f4f2;
    border: 1px solid #d4d4d8;
    padding: 7px 9px;
    text-align: left;
    font-weight: 700;
    color: #18181b;
  }}
  .data-table td {{
    border: 1px solid #d4d4d8;
    padding: 7px 9px;
    vertical-align: top;
  }}
  .badge-ok {{
    display: inline-block; background: #ecfdf5; color: #065f46;
    border: 1px solid #a7f3d0; border-radius: 4px; padding: 1px 7px; font-size: 8.5pt; font-weight: 700;
  }}
  .badge-warn {{
    display: inline-block; background: #fffbeb; color: #92400e;
    border: 1px solid #fde68a; border-radius: 4px; padding: 1px 7px; font-size: 8.5pt; font-weight: 700;
  }}
  .badge-conflict {{
    display: inline-block; background: #fef2f2; color: #991b1b;
    border: 1px solid #fecaca; border-radius: 4px; padding: 1px 7px; font-size: 8.5pt; font-weight: 700;
  }}
  .ref-img-card {{
    border: 1px solid #d4d4d8; border-radius: 6px; padding: 10px 12px; margin-bottom: 16px;
    page-break-inside: avoid; background: #fafaf9;
  }}
  .ref-img-cap {{ font-size: 9.2pt; color: #18181b; margin-bottom: 8px; }}
  .ref-img-cap span {{ color: #71717a; font-size: 8.4pt; }}
  .ref-img-card img {{ display: block; max-width: 100%; max-height: 180mm; margin: 0 auto; border: 1px solid #e4e4e7; background: #fff; }}
  .ref-img-note {{ margin: 8px 0 0 0; font-size: 8.5pt; color: #52525b; }}
  .chapter {{ margin-bottom: 24px; }}
  .chapter-header {{
    border-bottom: 1.5px solid #0f4c81;
    padding-bottom: 6px;
    margin: 22px 0 12px 0;
    page-break-after: avoid;
  }}
  .chapter-num {{
    display: block;
    font-size: 8pt;
    font-weight: 700;
    letter-spacing: 0.08em;
    color: #0f4c81;
  }}
  .chapter-header h2 {{
    margin: 2px 0 0 0;
    font-size: 14pt;
    font-weight: 700;
    color: #18181b;
  }}
  .chapter-intro {{
    background: #fafaf9;
    border: 1px solid #e4e4e7;
    padding: 10px 13px;
    border-radius: 6px;
    font-size: 9.6pt;
    color: #3f3f46;
    margin: 0 0 14px 0;
  }}
  .article {{
    margin-bottom: 13px;
    page-break-inside: avoid;
  }}
  .article-head {{
    font-size: 10.6pt;
    font-weight: 700;
    color: #18181b;
    margin-bottom: 4px;
  }}
  .art-no {{ color: #0f4c81; margin-right: 4px; }}
  .art-body {{ margin: 0 0 5px 0; padding-left: 8px; color: #27272a; }}
  .art-list {{ margin: 4px 0 6px 0; padding-left: 22px; color: #27272a; }}
  .art-list li {{ margin-bottom: 3px; }}
  .tip-box {{
    margin-top: 6px;
    background: #f8fafc;
    border-left: 2.5px solid #0f4c81;
    padding: 6px 10px;
    font-size: 9.2pt;
    color: #334155;
  }}
  .form-sheet {{
    border: 1.5px solid #18181b;
    padding: 16px 18px;
    margin: 14px 0 22px 0;
    page-break-inside: avoid;
    background: #fff;
  }}
  .form-top {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 12px;
    border-bottom: 2px solid #18181b;
    padding-bottom: 10px;
    margin-bottom: 14px;
  }}
  .form-head-left {{ flex: 1; min-width: 0; }}
  .form-code {{ font-size: 8.5pt; font-weight: 700; color: {accent}; }}
  .form-top h3 {{ margin: 2px 0 4px 0; font-size: 14.5pt; font-weight: 800; letter-spacing: 0.04em; }}
  .form-purpose {{ margin: 0; font-size: 8.8pt; color: #52525b; }}
  .approval-box {{ border-collapse: collapse; font-size: 8.2pt; flex-shrink: 0; }}
  .approval-box th, .approval-box td {{ border: 1px solid #3f3f46; text-align: center; padding: 3px 7px; min-width: 44px; }}
  .approval-box th {{ background: #f4f4f2; font-weight: 600; }}
  .approval-box th.approval-label {{ width: 22px; min-width: 22px; background: #ecece9; line-height: 1.35; font-weight: 700; padding: 3px 4px; }}
  .deleg-note {{ margin: 7px 0 0 0; font-size: 8pt; color: #52525b; line-height: 1.45; }}
  .form-grid {{ width: 100%; border-collapse: collapse; font-size: 9.5pt; }}
  .form-grid th {{
    background: #f7f7f5; border: 1px solid #3f3f46; padding: 7px 10px; text-align: left; font-weight: 600;
  }}
  .form-grid td {{ border: 1px solid #3f3f46; padding: 7px 10px; }}
  .form-footer {{ margin-top: 16px; }}
  .form-stmt {{ text-align: center; font-size: 9.8pt; margin: 10px 0; }}
  .form-date {{ text-align: center; font-size: 9.8pt; margin: 12px 0; }}
  .form-sign {{ text-align: right; font-size: 10pt; font-weight: 600; margin: 10px 0; }}
  .form-recipient {{ text-align: center; font-size: 12pt; font-weight: 800; margin: 16px 0 4px 0; }}
  .chk-card {{
    border: 1px solid #e4e4e7; border-radius: 6px; padding: 12px 14px; margin-bottom: 12px; page-break-inside: avoid;
  }}
  .chk-card h4 {{ margin: 0 0 8px 0; font-size: 10.5pt; color: #0f4c81; }}
  .chk-list {{ list-style: none; padding: 0; margin: 0; }}
  .chk-list li {{ display: flex; align-items: center; gap: 8px; margin-bottom: 5px; font-size: 9.5pt; }}
  .chk-box {{ display: inline-block; width: 11px; height: 11px; border: 1.2px solid #3f3f46; border-radius: 2px; flex-shrink: 0; }}
</style>
</head>
<body>
  <!-- COVER PAGE -->
  <div class="cover">
    <div class="cover-top">
      <span>{_esc(denom_header)}</span>
      <span class="cover-ver">{_esc(version_label)}</span>
    </div>
    <div class="cover-main">
      <div class="cover-kicker">{_esc(board['category'])} · {_esc(board['work_type'])}</div>
      <h1 class="cover-title">{_esc(doc_title)}</h1>
      <p class="cover-sub">{_esc(subtitle)}</p>
      {f'<div class="cover-summary">{_esc(exec_summary)}</div>' if exec_summary else ''}
      {f'<div class="cover-approval-wrap">{_build_approval_table_html(approval_slots, compact=False)}</div>' if show_cover_approval else ''}
      <table class="cover-meta">
        <tr><th>시행 · 편찬일</th><td>{_esc(today_str)}</td><th>판본</th><td>{_esc(version_label)}</td></tr>
        <tr><th>적용 부서·분류</th><td>{_esc(board['category'])}</td><th>편찬 주관</th><td>{_esc(created_by)} ({_esc(committee_label)})</td></tr>
        <tr><th>적용 결재선</th><td colspan="3">{_esc(approval_chain_text)} ({_esc(ap_preset.get('basis') or ap_preset.get('name', ''))})</td></tr>
        <tr><th>반영 범위</th><td colspan="3">교역자 제출 행정자료 · 투표 채택안 {len(vote_summary)}건 · 상위 법규(총회헌법·정관·시행세칙) 위계 검수 완료</td></tr>
      </table>
      {f'<p class="deleg-note" style="margin-top:8px;">{_esc(deleg_note)}</p>' if (show_deleg_note and deleg_note) else ''}
    </div>
    <div class="cover-bottom">
      <span>{_esc(footer_left)}</span>
      <span>{_esc(footer_right)}</span>
    </div>
  </div>

  <!-- TOC & LAW AUDIT -->
  <div>
    <div class="running-bar">
      <span>{_esc(church_name)} 행정Q&amp;A · {_esc(doc_title)}</span>
      <span>{_esc(version_label)} · {_esc(today_str)}</span>
    </div>
    <h2 class="section-h">목 차 (Table of Contents)</h2>
    <table class="toc-table"><tbody>{"".join(toc_rows)}</tbody></table>

    <h2 class="section-h" style="margin-top:24px;">상위 법규 위계 검수 결과 (총회헌법 &gt; 정관 &gt; 시행세칙)</h2>
    <table class="data-table">
      <thead><tr><th>참조 상위 법규</th><th style="text-align:center;">검수 판정</th><th>검수 의견 및 반영 사항</th></tr></thead>
      <tbody>{"".join(audit_html_rows)}</tbody>
    </table>
  </div>

  <!-- MAIN CHAPTERS -->
  <div class="page-break">
    <div class="running-bar">
      <span>{_esc(church_name)} 공식 행정 표준 규정</span>
      <span>{_esc(doc_title)}</span>
    </div>
    {"".join(chapters_html)}
  </div>

  <!-- APPENDIX 1: STANDARD FORMS -->
  {f'<section class="chapter page-break"><div class="chapter-header"><span class="chapter-num">APPENDIX 01</span><h2>부록 1. 표준 행정 서식 및 결재 양식</h2></div>{"".join(forms_html)}</section>' if forms_html else ''}

  <!-- APPENDIX 2: CHECKLISTS -->
  {checklists_html}

  <!-- APPENDIX 3: VOTING CONSENSUS & REVISION HISTORY -->
  <section class="chapter page-break">
    <div class="chapter-header"><span class="chapter-num">APPENDIX 03</span><h2>부록 3. 교역자 투표 합의 요약 및 개정 이력</h2></div>
    <table class="data-table">
      <thead><tr><th style="width:28%;">표준화 안건</th><th>최종 채택 규격</th><th style="width:20%;text-align:center;">득표 결과</th></tr></thead>
      <tbody>{"".join(vote_rows_html)}</tbody>
    </table>
    <h3 style="font-size:11pt;margin:18px 0 6px 0;">개정 · 편찬 이력</h3>
    <table class="data-table">
      <thead><tr><th style="width:14%;">판본</th><th style="width:22%;">편찬일</th><th style="width:20%;">담당</th><th>주요 변경 및 편찬 사유</th></tr></thead>
      <tbody>
        <tr><td>{_esc(version_label)}</td><td>{_esc(today_str)}</td><td>{_esc(created_by)}</td><td>교역자 행정 파일 수집·투표 합의·4역할 전문가 위원회 검수를 거쳐 정규 PDF·Word·HWPX 편찬</td></tr>
      </tbody>
    </table>
    {cmt_rows_html}
  </section>

  {images_html}
  {diff_html}
</body>
</html>
"""


def _render_html_to_pdf(html_content: str, out_pdf: Path) -> str:
    """Render HTML to crisp vector A4 PDF via Microsoft Edge/Chrome Headless, with pure-Python PyMuPDF Story fallback."""
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    browser = _find_headless_browser()
    if browser:
        with tempfile.TemporaryDirectory(prefix="church_pdf_") as td:
            html_file = Path(td) / "manuscript.html"
            html_file.write_text(html_content, encoding="utf-8")
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            for headless_flag in ("--headless=new", "--headless"):
                cmd = [
                    browser,
                    headless_flag,
                    "--disable-gpu",
                    "--no-sandbox",
                    "--no-pdf-header-footer",
                    f"--print-to-pdf={out_pdf}",
                    html_file.as_uri(),
                ]
                try:
                    subprocess.run(cmd, capture_output=True, timeout=45, creationflags=creationflags)
                    if out_pdf.exists() and out_pdf.stat().st_size > 2000:
                        return "edge-chromium-headless"
                except Exception:
                    continue

    # Pure-Python fallback via PyMuPDF Story (100% offline guaranteed)
    story = pymupdf.Story(html=html_content)
    writer = pymupdf.DocumentWriter(str(out_pdf))
    mediabox = pymupdf.paper_rect("a4")
    where = mediabox + (42, 42, -42, -42)
    more = 1
    while more:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()
    return "pymupdf-story-fallback"


def _set_cell_border(cell: Any, color: str = "444444") -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = OxmlElement("w:tcBorders")
    for side in ("top", "left", "bottom", "right"):
        b = OxmlElement(f"w:{side}")
        b.set(qn("w:val"), "single")
        b.set(qn("w:sz"), "4")
        b.set(qn("w:space"), "0")
        b.set(qn("w:color"), color)
        borders.append(b)
    tc_pr.append(borders)


def _render_manuscript_docx(
    board: dict[str, Any],
    manuscript: dict[str, Any],
    law_audit: list[dict[str, Any]],
    vote_summary: list[dict[str, Any]],
    version_label: str,
    out_docx: Path,
    pdf_template: dict[str, Any] | None = None,
    approval_preset: dict[str, Any] | None = None,
    image_attachments: list[dict[str, Any]] | None = None,
    diff_report: dict[str, Any] | None = None,
) -> Path:
    tpl = {**DEFAULT_PDF_TEMPLATE, **(pdf_template or {})}
    ap_slots = list((approval_preset or {}).get("slots") or ["총무", "부장", "지도교역자", "당회장"])
    denom_header = str(tpl.get("denomination_header") or "대한예수교장로회 · 목포사랑의교회 공식 행정 표준 규정집")
    default_stmt = str(tpl.get("default_submit_statement") or "위와 같이 제출(신청)하오니 허락하여 주시기 바랍니다.")
    default_recipient = str(tpl.get("default_recipient") or "목포사랑의교회 당회장 귀하")
    deleg_note = str(tpl.get("delegation_footnote") or "")
    show_deleg_note = bool(tpl.get("show_delegation_footnote", True))

    d = docx.Document()
    for sec in d.sections:
        sec.top_margin = Cm(2.0)
        sec.bottom_margin = Cm(2.0)
        sec.left_margin = Cm(2.0)
        sec.right_margin = Cm(2.0)

    normal = d.styles["Normal"]
    normal.font.name = "맑은 고딕"
    normal.font.size = Pt(10)

    # Title
    p_k = d.add_paragraph()
    p_k.alignment = WD_ALIGN_PARAGRAPH.CENTER
    rk = p_k.add_run(f"{denom_header} ({version_label})")
    rk.font.name = "맑은 고딕"
    rk.font.size = Pt(10)
    rk.font.color.rgb = RGBColor(15, 76, 129)

    p_t = d.add_paragraph()
    p_t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    rt = p_t.add_run(manuscript.get("title") or board["title"])
    rt.font.name = "맑은 고딕"
    rt.font.size = Pt(18)
    rt.bold = True

    p_ap = d.add_paragraph()
    p_ap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    rap = p_ap.add_run(f"적용 결재선: {' → '.join(ap_slots)}")
    rap.font.name = "맑은 고딕"
    rap.font.size = Pt(9.5)
    rap.font.color.rgb = RGBColor(82, 82, 91)

    if manuscript.get("executive_summary"):
        p_s = d.add_paragraph(manuscript["executive_summary"])
        p_s.paragraph_format.space_after = Pt(10)

    # Chapters
    for idx, ch in enumerate(manuscript.get("chapters") or [], start=1):
        h = d.add_heading(ch.get("title") or f"제{idx}장", level=1)
        for r in h.runs:
            r.font.name = "맑은 고딕"
        if ch.get("summary"):
            d.add_paragraph(ch["summary"])
        for a_idx, art in enumerate(ch.get("articles") or [], start=1):
            p = d.add_paragraph()
            r1 = p.add_run(f"{art.get('number') or f'제{a_idx}조'} ({art.get('title', '')}) ")
            r1.bold = True
            r1.font.name = "맑은 고딕"
            r2 = p.add_run(art.get("body", ""))
            r2.font.name = "맑은 고딕"
            for pt_item in art.get("points") or []:
                pl = d.add_paragraph(f"  - {pt_item}")
                pl.paragraph_format.space_after = Pt(2)
            if art.get("practical_tip"):
                ptip = d.add_paragraph(f"  [실무 가이드] {art['practical_tip']}")
                ptip.paragraph_format.space_after = Pt(4)

    # Standard Forms with Real Church Approval Line Box
    for f_idx, fm in enumerate(manuscript.get("standard_forms") or [], start=1):
        d.add_page_break()
        fh = d.add_heading(f"표준 서식 제{f_idx}호: {fm.get('title', '')}", level=1)
        for r in fh.runs:
            r.font.name = "맑은 고딕"

        # Approval line table
        ap_tbl = d.add_table(rows=2, cols=len(ap_slots) + 1)
        ap_tbl.alignment = WD_TABLE_ALIGNMENT.RIGHT
        lbl_cell = ap_tbl.cell(0, 0).merge(ap_tbl.cell(1, 0))
        lbl_cell.text = "결재"
        lbl_cell.width = Cm(1.1)
        lbl_cell._tc.get_or_add_tcPr().append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="ECECE9"/>'))
        _set_cell_border(lbl_cell)
        for ci, slot in enumerate(ap_slots, start=1):
            c_top = ap_tbl.cell(0, ci)
            c_bot = ap_tbl.cell(1, ci)
            c_top.text = str(slot)
            c_bot.text = "\n"
            c_top.width = Cm(2.1)
            c_bot.width = Cm(2.1)
            c_top._tc.get_or_add_tcPr().append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="F4F4F2"/>'))
            _set_cell_border(c_top)
            _set_cell_border(c_bot)
        d.add_paragraph("")

        fields = fm.get("fields") or ["성명", "직분", "소속", "연락처", "내용"]
        tbl = d.add_table(rows=len(fields), cols=2)
        tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        for i, fld in enumerate(fields):
            c0, c1 = tbl.rows[i].cells[0], tbl.rows[i].cells[1]
            c0.width = Cm(4.8)
            c1.width = Cm(12.0)
            c0.text = str(fld)
            c1.text = ""
            shading = parse_xml(f'<w:shd {nsdecls("w")} w:fill="F4F4F2"/>')
            c0._tc.get_or_add_tcPr().append(shading)
            _set_cell_border(c0)
            _set_cell_border(c1)

        if show_deleg_note and deleg_note:
            p_dn = d.add_paragraph(deleg_note)
            p_dn.runs[0].font.size = Pt(8.5)
            p_dn.runs[0].font.color.rgb = RGBColor(82, 82, 91)

        d.add_paragraph(f"\n{default_stmt}").alignment = WD_ALIGN_PARAGRAPH.CENTER
        d.add_paragraph("20    년      월      일").alignment = WD_ALIGN_PARAGRAPH.CENTER
        d.add_paragraph("신청인(작성자):                  (인)").alignment = WD_ALIGN_PARAGRAPH.RIGHT
        pr = d.add_paragraph()
        pr.alignment = WD_ALIGN_PARAGRAPH.CENTER
        rr = pr.add_run(default_recipient)
        rr.bold = True
        rr.font.size = Pt(12)

    # Reference Images Appendix in DOCX
    if image_attachments:
        d.add_page_break()
        ih = d.add_heading("부록: 현장 참고 이미지 및 제출 서식 사본", level=1)
        for r in ih.runs:
            r.font.name = "맑은 고딕"
        for i_idx, img in enumerate(image_attachments, start=1):
            p_cap = d.add_paragraph(f"참고 자료 {i_idx}. {img['title']} ({img['file_name']})")
            if p_cap.runs:
                p_cap.runs[0].bold = True
                p_cap.runs[0].font.name = "맑은 고딕"
            try:
                if Path(img["path"]).exists():
                    d.add_picture(img["path"], width=Cm(14.0))
            except Exception:
                pass

    # 신·구조문 대조표 in DOCX
    diff_rows = (diff_report or {}).get("rows") or []
    if diff_rows:
        d.add_page_break()
        dh = d.add_heading(f"신·구조문 대조표 ({diff_report.get('prev_version', '이전')} → {version_label})", level=1)
        for r in dh.runs:
            r.font.name = "맑은 고딕"
        dtbl = d.add_table(rows=len(diff_rows) + 1, cols=3)
        dtbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        headers = ["조항 / 구분", f"현행 ({diff_report.get('prev_version', '이전')})", f"개정안 ({version_label})"]
        for ci, h_txt in enumerate(headers):
            c = dtbl.rows[0].cells[ci]
            c.text = h_txt
            c._tc.get_or_add_tcPr().append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="ECECE9"/>'))
            _set_cell_border(c)
        for ri, dr in enumerate(diff_rows, start=1):
            dtbl.rows[ri].cells[0].text = f"{dr.get('article', '')}\n[{dr.get('status', '')}]"
            dtbl.rows[ri].cells[1].text = dr.get("before", "")
            dtbl.rows[ri].cells[2].text = dr.get("after", "")
            for ci in range(3):
                _set_cell_border(dtbl.rows[ri].cells[ci])

    out_docx.parent.mkdir(parents=True, exist_ok=True)
    d.save(str(out_docx))
    return out_docx


def _render_manuscript_hwpx(
    board: dict[str, Any],
    manuscript: dict[str, Any],
    law_audit: list[dict[str, Any]],
    vote_summary: list[dict[str, Any]],
    version_label: str,
    out_hwpx: Path,
    pdf_template: dict[str, Any] | None = None,
    approval_preset: dict[str, Any] | None = None,
    diff_report: dict[str, Any] | None = None,
) -> Path:
    """Create a standards-compliant KS X 6101 Hancom Hangul (.hwpx) full regulation manual."""
    tpl = {**DEFAULT_PDF_TEMPLATE, **(pdf_template or {})}
    ap_slots = list((approval_preset or {}).get("slots") or ["총무", "부장", "지도교역자", "당회장"])
    denom_header = str(tpl.get("denomination_header") or "대한예수교장로회 · 목포사랑의교회 공식 행정 표준 규정집")
    default_stmt = str(tpl.get("default_submit_statement") or "위와 같이 제출(신청)하오니 허락하여 주시기 바랍니다.")
    default_recipient = str(tpl.get("default_recipient") or "목포사랑의교회 당회장 귀하")
    doc_title = str(manuscript.get("title") or board["title"])
    today_str = datetime.now().strftime("%Y년 %m월 %d일")

    sec_pr_xml = (
        '<hp:secPr id="" textDirection="HORIZONTAL" spaceColumns="1134" tabStop="8000" '
        'outlineShapeIDRef="1" memoShapeIDRef="0" textVerticalWidthHead="0" masterPageCnt="0">'
        '<hp:grid lineGrid="0" charGrid="0" wonggojiFormat="0"/>'
        '<hp:startNum pageStartsOn="BOTH" page="0" pic="0" tbl="0" equation="0"/>'
        '<hp:visibility hideFirstHeader="0" hideFirstFooter="0" hideFirstMasterPage="0" border="SHOW_ALL" fill="SHOW_ALL" hideFirstPageNum="0" hideFirstEmptyLine="0" showLineNumber="0"/>'
        '<hp:pagePr landscape="WIDELY" width="59528" height="84188" gutterType="LEFT_ONLY">'
        '<hp:margin header="4252" footer="4252" gutter="0" left="8504" right="8504" top="5668" bottom="4252"/>'
        "</hp:pagePr></hp:secPr>"
    )

    body_blocks: list[str] = [
        '<hp:p id="0" paraPrIDRef="1" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
        f'<hp:run charPrIDRef="0">{sec_pr_xml}<hp:t>{xml_escape(doc_title)}</hp:t></hp:run></hp:p>',
        _hwpx_para(f"{denom_header} · {version_label} ({today_str})", para_pr_id=1, char_pr_id=1),
        _hwpx_para(f"적용 부서: {board['category']} | 적용 결재선: {' → '.join(ap_slots)}", para_pr_id=1, char_pr_id=1),
        _hwpx_para("", para_pr_id=0, char_pr_id=2),
    ]

    if manuscript.get("executive_summary"):
        body_blocks.append(_hwpx_para("[편찬 요약]", para_pr_id=0, char_pr_id=3))
        body_blocks.append(_hwpx_para(str(manuscript["executive_summary"]), para_pr_id=0, char_pr_id=2))
        body_blocks.append(_hwpx_para("", para_pr_id=0, char_pr_id=2))

    # Law Audit Table
    if law_audit:
        body_blocks.append(_hwpx_para("[상위 법규 위계 검수 결과]", para_pr_id=0, char_pr_id=3))
        law_rows = [["참조 상위 법규", "검수 판정", "검수 의견"]] + [
            [str(a.get("source", "")), str(a.get("status", "정합 확인")), str(a.get("note", ""))]
            for a in law_audit
        ]
        body_blocks.append(_hwpx_table(law_rows, header_row=True))
        body_blocks.append(_hwpx_para("", para_pr_id=0, char_pr_id=2))

    # Main Chapters
    for c_idx, ch in enumerate(manuscript.get("chapters") or [], start=1):
        ch_title = str(ch.get("title") or f"제{c_idx}장")
        body_blocks.append(_hwpx_para(ch_title, para_pr_id=0, char_pr_id=0))
        if ch.get("summary"):
            body_blocks.append(_hwpx_para(str(ch["summary"]), para_pr_id=0, char_pr_id=1))
        for a_idx, art in enumerate(ch.get("articles") or [], start=1):
            head = f"{art.get('number') or f'제{a_idx}조'} ({art.get('title', '')})"
            body_blocks.append(_hwpx_para(head, para_pr_id=0, char_pr_id=3))
            if art.get("body"):
                body_blocks.append(_hwpx_para(str(art["body"]), para_pr_id=0, char_pr_id=2))
            for pt in art.get("points") or []:
                body_blocks.append(_hwpx_para(f"  · {pt}", para_pr_id=0, char_pr_id=2))
            if art.get("practical_tip"):
                body_blocks.append(_hwpx_para(f"  [실무 가이드] {art['practical_tip']}", para_pr_id=0, char_pr_id=4))
        if ch.get("table") and ch["table"].get("headers"):
            t_rows = [list(ch["table"]["headers"])] + [list(r) for r in (ch["table"].get("rows") or [])]
            body_blocks.append(_hwpx_table(t_rows, header_row=True))
        body_blocks.append(_hwpx_para("", para_pr_id=0, char_pr_id=2))

    # Standard Forms
    for f_idx, fm in enumerate(manuscript.get("standard_forms") or [], start=1):
        body_blocks.append(_hwpx_para(f"[부록 1] 표준 서식 제{f_idx}호: {fm.get('title', '')}", para_pr_id=0, char_pr_id=0))
        if fm.get("purpose"):
            body_blocks.append(_hwpx_para(str(fm["purpose"]), para_pr_id=0, char_pr_id=1))
        ap_rows = [["결재"] + [str(s) for s in ap_slots], [""] + ["" for _ in ap_slots]]
        body_blocks.append(_hwpx_table(ap_rows, header_row=True))
        f_rows = [["항목", "기입 내용"]] + [[str(fld), ""] for fld in (fm.get("fields") or ["성명", "직분", "소속", "내용"])]
        body_blocks.append(_hwpx_table(f_rows, header_row=True))
        body_blocks.append(_hwpx_para(default_stmt, para_pr_id=1, char_pr_id=2))
        body_blocks.append(_hwpx_para("20    년      월      일", para_pr_id=1, char_pr_id=2))
        body_blocks.append(_hwpx_para("신청인(작성자):                    (인)", para_pr_id=2, char_pr_id=2))
        body_blocks.append(_hwpx_para(default_recipient, para_pr_id=1, char_pr_id=3))
        body_blocks.append(_hwpx_para("", para_pr_id=0, char_pr_id=2))

    # Checklists
    for ck in manuscript.get("checklists") or []:
        body_blocks.append(_hwpx_para(f"[부록 2] {ck.get('title', '실무 점검표')}", para_pr_id=0, char_pr_id=3))
        for it in ck.get("items") or []:
            body_blocks.append(_hwpx_para(f"  □ {it}", para_pr_id=0, char_pr_id=2))
        body_blocks.append(_hwpx_para("", para_pr_id=0, char_pr_id=2))

    # Voting Consensus Summary
    if vote_summary:
        body_blocks.append(_hwpx_para("[부록 3] 교역자 투표 합의 요약", para_pr_id=0, char_pr_id=3))
        v_rows = [["안건", "최종 채택안", "득표"]] + [
            [str(v.get("cluster_title", "")), str(v.get("adopted_title", "")), f"{v.get('votes', 0)}/{v.get('total_votes', 0)}표"]
            for v in vote_summary
        ]
        body_blocks.append(_hwpx_table(v_rows, header_row=True))
        body_blocks.append(_hwpx_para("", para_pr_id=0, char_pr_id=2))

    # 신·구조문 대조표
    diff_rows = (diff_report or {}).get("rows") or []
    if diff_rows:
        body_blocks.append(_hwpx_para(f"[부록] 신·구조문 대조표 ({diff_report.get('prev_version', '이전')} → {version_label})", para_pr_id=0, char_pr_id=3))
        d_rows = [["조항 / 구분", "현행", "개정안"]] + [
            [f"{dr.get('article', '')} [{dr.get('status', '')}]", str(dr.get("before", "")), str(dr.get("after", ""))]
            for dr in diff_rows
        ]
        body_blocks.append(_hwpx_table(d_rows, header_row=True))

    version_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<hv:HCFVersion xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version" '
        'tagetApplication="WORDPROCESSOR" major="5" minor="1" micro="1" buildNumber="0" os="1" xmlVersion="1.4" application="Hancom Office Hangul"/>'
    )
    container_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<ocf:container xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container" '
        'xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf">'
        '<ocf:rootfiles><ocf:rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/></ocf:rootfiles></ocf:container>'
    )
    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<odf:manifest xmlns:odf="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>'
    )
    content_hpf = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<opf:package xmlns:opf="http://www.idpf.org/2007/opf/" version="" unique-identifier="" id="">'
        f"<opf:metadata><opf:title>{xml_escape(doc_title)}</opf:title><opf:language>ko</opf:language></opf:metadata>"
        '<opf:manifest><opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>'
        '<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/></opf:manifest>'
        '<opf:spine><opf:itemref idref="header" linear="yes"/><opf:itemref idref="section0" linear="yes"/></opf:spine></opf:package>'
    )
    header_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" '
        'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" version="1.4" secCnt="1">'
        '<hh:beginNum page="1" footnote="1" endnote="1" pic="1" tbl="1" equation="1"/>'
        '<hh:refList><hh:fontfaces itemCnt="1"><hh:fontface lang="HANGUL" fontCnt="1">'
        '<hh:font id="0" face="맑은 고딕" type="TTF" isEmbedded="0"/></hh:fontface></hh:fontfaces>'
        '<hh:borderFills itemCnt="4">'
        '<hh:borderFill id="1" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0">'
        '<hh:leftBorder type="NONE" width="0.1 mm" color="#000000"/><hh:rightBorder type="NONE" width="0.1 mm" color="#000000"/>'
        '<hh:topBorder type="NONE" width="0.1 mm" color="#000000"/><hh:bottomBorder type="NONE" width="0.1 mm" color="#000000"/></hh:borderFill>'
        '<hh:borderFill id="2" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0">'
        '<hh:leftBorder type="NONE" width="0.1 mm" color="#000000"/><hh:rightBorder type="NONE" width="0.1 mm" color="#000000"/>'
        '<hh:topBorder type="NONE" width="0.1 mm" color="#000000"/><hh:bottomBorder type="NONE" width="0.1 mm" color="#000000"/></hh:borderFill>'
        '<hh:borderFill id="3" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0">'
        '<hh:leftBorder type="SOLID" width="0.12 mm" color="#94A3B8"/><hh:rightBorder type="SOLID" width="0.12 mm" color="#94A3B8"/>'
        '<hh:topBorder type="SOLID" width="0.12 mm" color="#94A3B8"/><hh:bottomBorder type="SOLID" width="0.12 mm" color="#94A3B8"/>'
        '<hc:fillBrush><hc:winBrush faceColor="#FFFFFF" hatchColor="#999999" alpha="0"/></hc:fillBrush></hh:borderFill>'
        '<hh:borderFill id="4" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0">'
        '<hh:leftBorder type="SOLID" width="0.12 mm" color="#94A3B8"/><hh:rightBorder type="SOLID" width="0.12 mm" color="#94A3B8"/>'
        '<hh:topBorder type="SOLID" width="0.12 mm" color="#94A3B8"/><hh:bottomBorder type="SOLID" width="0.12 mm" color="#94A3B8"/>'
        '<hc:fillBrush><hc:winBrush faceColor="#EEF2F7" hatchColor="#999999" alpha="0"/></hc:fillBrush></hh:borderFill>'
        '</hh:borderFills>'
        '<hh:charProperties itemCnt="5">'
        '<hh:charPr id="0" height="1450" textColor="#0F172A" shadeColor="none" useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="2"><hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/><hh:bold/></hh:charPr>'
        '<hh:charPr id="1" height="850" textColor="#64748B" shadeColor="none" useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="2"><hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/></hh:charPr>'
        '<hh:charPr id="2" height="1000" textColor="#1E293B" shadeColor="none" useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="2"><hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/></hh:charPr>'
        '<hh:charPr id="3" height="1050" textColor="#0F172A" shadeColor="none" useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="2"><hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/><hh:bold/></hh:charPr>'
        '<hh:charPr id="4" height="920" textColor="#0F4C81" shadeColor="none" useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="2"><hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/></hh:charPr>'
        '</hh:charProperties>'
        '<hh:paraProperties itemCnt="3">'
        '<hh:paraPr id="0" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="1" suppressLineNumbers="0" checked="0"><hh:align horizontal="LEFT" vertical="BASELINE"/><hh:lineSpacing type="PERCENT" value="150" unit="HWPUNIT"/></hh:paraPr>'
        '<hh:paraPr id="1" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="1" suppressLineNumbers="0" checked="0"><hh:align horizontal="CENTER" vertical="BASELINE"/><hh:lineSpacing type="PERCENT" value="160" unit="HWPUNIT"/></hh:paraPr>'
        '<hh:paraPr id="2" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="1" suppressLineNumbers="0" checked="0"><hh:align horizontal="RIGHT" vertical="BASELINE"/><hh:lineSpacing type="PERCENT" value="150" unit="HWPUNIT"/></hh:paraPr>'
        '</hh:paraProperties>'
        '<hh:styles itemCnt="1"><hh:style id="0" type="PARA" name="바탕글" engName="Normal" paraPrIDRef="0" charPrIDRef="2" nextStyleIDRef="0" langID="1042" lockForm="0"/></hh:styles>'
        "</hh:refList></hh:head>"
    )
    section0_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
        'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
        'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core">'
        + "".join(body_blocks)
        + "</hs:sec>"
    )

    out_hwpx.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(out_hwpx), "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("version.xml", version_xml.encode("utf-8"))
        zf.writestr("META-INF/container.xml", container_xml.encode("utf-8"))
        zf.writestr("META-INF/manifest.xml", manifest_xml.encode("utf-8"))
        zf.writestr("Contents/content.hpf", content_hpf.encode("utf-8"))
        zf.writestr("Contents/header.xml", header_xml.encode("utf-8"))
        zf.writestr("Contents/section0.xml", section0_xml.encode("utf-8"))
    return out_hwpx


def _build_offline_manuscript(
    board: dict[str, Any],
    submissions: list[dict[str, Any]],
    proposals: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    law_audit: list[dict[str, Any]],
) -> dict[str, Any]:
    """Deterministic expert-grade fallback structure when CLI/internet is unavailable."""
    chapters: list[dict[str, Any]] = [
        {
            "title": f"제1장 총칙 및 {board['category']} 기본 원칙",
            "summary": board.get("description") or f"목포사랑의교회 {board['category']} 업무의 통일된 기준과 절차를 규정합니다.",
            "articles": [
                {
                    "number": "제1조",
                    "title": "목적",
                    "body": f"본 규정은 목포사랑의교회 '{board['title']}' 영역의 실무 기준과 표준 행정 서식을 통일하여 사역의 일관성과 투명성을 확보함을 목적으로 한다.",
                    "points": [],
                    "practical_tip": "모든 부서와 교역자는 본 표준 규정집의 최신 판본을 기준으로 행정을 처리합니다.",
                },
                {
                    "number": "제2조",
                    "title": "적용 범위 및 법규 위계",
                    "body": "본 규정은 대한예수교장로회 총회헌법, 목포사랑의교회 정관 및 2025년 사랑의교회 시행세칙의 범위 안에서 효력을 가진다.",
                    "points": [
                        "상위 법규(총회헌법 > 교회 정관 > 시행세칙)와 충돌 시 상위 법규를 우선 적용한다.",
                        "본 규정에 명시되지 않은 사항은 당회 결의 및 교회 관례에 따른다.",
                    ],
                },
            ],
        }
    ]

    # Chapter 2: Adopted Consensus Standards from Voting
    adopted_articles: list[dict[str, Any]] = []
    for idx, p in enumerate(proposals, start=1):
        opts = p.get("options") or []
        winner = None
        if p.get("winning_option_id"):
            winner = next((o for o in opts if o["id"] == p["winning_option_id"]), None)
        if not winner and opts:
            winner = max(opts, key=lambda o: (o.get("vote_count", 0), 1 if o.get("is_ai_improved") else 0))
        if winner:
            clean_body = re.sub(r"[#*`]+", "", winner.get("content_md", "")).strip()
            adopted_articles.append(
                {
                    "number": f"제{idx + 2}조",
                    "title": p["cluster_title"],
                    "body": clean_body[:900],
                    "points": [],
                    "practical_tip": f"교역자 투표 채택안({winner['label']}: {winner['title']})",
                }
            )

    # Also include active submissions not covered by proposals
    sub_articles: list[dict[str, Any]] = []
    art_base = len(adopted_articles) + 3
    for idx, s in enumerate(submissions[:12]):
        excerpt = (s.get("extracted_text") or s.get("notes") or s.get("ai_summary") or "").strip()
        lines = [ln.strip() for ln in excerpt.splitlines() if ln.strip() and not ln.startswith("[p.")]
        sub_articles.append(
            {
                "number": f"제{art_base + idx}조",
                "title": s["title"],
                "body": " ".join(lines[:4])[:650] or s.get("ai_summary", ""),
                "points": lines[4:8],
                "practical_tip": f"제출 자료 반영 ({s.get('file_name') or '직접 제출'})",
            }
        )

    if adopted_articles:
        chapters.append(
            {
                "title": "제2장 교역자 합의 표준 규격 (투표 채택안)",
                "summary": "수집 기간 중 제출된 복수 규격을 비교·투표하여 최종 채택한 통일 기준입니다.",
                "articles": adopted_articles,
            }
        )

    if sub_articles:
        chapters.append(
            {
                "title": f"제{len(chapters) + 1}장 세부 실무 지침 및 수합 기준",
                "summary": "각 부서·교역자가 제출한 현장 행정 자료와 개선 의견을 통합 정리한 세부 지침입니다.",
                "articles": sub_articles,
            }
        )

    if comments:
        chapters.append(
            {
                "title": f"제{len(chapters) + 1}장 현장 개선 의견 반영 및 보완 사항",
                "summary": "교역자 토론 및 개선 의견에서 제기된 실무 보완 사항을 반영합니다.",
                "articles": [
                    {
                        "number": f"제{art_base + len(sub_articles) + 1}조",
                        "title": "실무 보완 수칙",
                        "body": "수집 및 투표 과정에서 제안된 아래 개선 사항을 행정 처리 시 준수한다.",
                        "points": [c["content"][:220] for c in comments[:8]],
                    }
                ],
            }
        )

    # Extract standard forms
    std_forms = []
    for p in proposals[:4]:
        std_forms.append(
            {
                "title": f"{p['cluster_title']} 표준 양식",
                "purpose": f"{board['category']} 공식 제출·결재용 표준 서식",
                "fields": ["신청일", "소속 부서 / 교구", "성명 / 직분", "연락처", "상세 내용 및 사유", "첨부 서류 및 비고"],
            }
        )
    if not std_forms:
        std_forms.append(
            {
                "title": f"{board['title']} 표준 신청·보고서",
                "purpose": f"{board['category']} 통일 행정 서식",
                "fields": ["작성일", "소속 부서", "성명 / 직분", "연락처", "제목", "세부 내용 및 요청 사항"],
            }
        )

    return {
        "title": f"{board['title']} 표준 규정집",
        "subtitle": f"목포사랑의교회 {board['category']} 공식 행정 매뉴얼 및 표준 서식",
        "executive_summary": (
            f"본 규정집은 목포사랑의교회 {board['category']}({board['work_type']}) 분야의 기존 행정 문서 {len(submissions)}건과 "
            f"교역자 투표 합의 {len(proposals)}건, 개선 의견 {len(comments)}건을 종합하여 편찬한 공식 정규 행정 표준본입니다."
        ),
        "chapters": chapters,
        "standard_forms": std_forms,
        "checklists": [
            {
                "title": f"{board['category']} 실무 제출 전 필수 점검표",
                "items": [
                    "최신 표준 서식 양식(본 규정집 부록 1)을 사용하였는가?",
                    "담당자 → 부서장 → 당회장(또는 위임전결권자) 결재 위계를 확인하였는가?",
                    "상위 법규(총회헌법·정관·시행세칙) 기준 기한 및 증빙 서류를 누락 없이 첨부하였는가?",
                ],
            }
        ],
    }


async def generate_committee_draft_stream(
    db: Database,
    store: StandardizationStore,
    board: dict[str, Any],
    version_label: str = "",
    custom_directives: str = "",
    approval_preset_id: str = "",
    custom_approval_slots: list[str] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Run Stages 1-3 of the 4-Role Expert Committee and yield an editable manuscript draft before final typesetting."""
    std_cfg = load_std_config(db)
    approval_preset = resolve_approval_preset(
        std_cfg,
        board_category=board.get("category", ""),
        preset_id=approval_preset_id,
        custom_slots=custom_approval_slots,
    )
    approval_slots = list(approval_preset.get("slots") or ["총무", "부장", "지도교역자", "당회장"])
    approval_chain_str = " → ".join(approval_slots)

    submissions = store.list_submissions(board["id"], include_archived=False)
    proposals = store.list_proposals(board["id"])
    comments = store.list_comments(board["id"])
    existing_pubs = store.list_publications(board["id"])

    if not version_label.strip():
        version_label = f"v1.{len(existing_pubs)}"

    vote_summary: list[dict[str, Any]] = []
    for p in proposals:
        opts = p.get("options") or []
        winner = None
        if p.get("winning_option_id"):
            winner = next((o for o in opts if o["id"] == p["winning_option_id"]), None)
        if not winner and opts:
            winner = max(opts, key=lambda o: (o.get("vote_count", 0), 1 if o.get("is_ai_improved") else 0))
        vote_summary.append(
            {
                "cluster_title": p["cluster_title"],
                "adopted_label": winner["label"] if winner else "-",
                "adopted_title": winner["title"] if winner else "-",
                "votes": winner.get("vote_count", 0) if winner else 0,
                "total_votes": p.get("total_votes", 0),
                "adopted_content": (winner.get("content_md", "") if winner else "")[:1500],
            }
        )

    # ---- STAGE 1 ----
    yield {
        "event": "stage",
        "stage": 1,
        "role": "체계·목차 설계 전문가",
        "message": f"제출 자료 {len(submissions)}건·투표 합의 {len(vote_summary)}건·개선 의견 {len(comments)}건을 종합하여 장·절·조 체계를 설계 중...",
    }
    await asyncio.sleep(0.04)

    # ---- STAGE 2: Real Engine v4.0 Law Hierarchy & Conflict Audit ----
    yield {
        "event": "stage",
        "stage": 2,
        "role": "교회 법규 위계 검수 전문가 (v4.0)",
        "message": "총회헌법 · 목포사랑의교회 정관 · 2025년 시행세칙 원문과 수치·기한·결재권자를 정밀 교차 감사 중...",
    }
    law_audit = await asyncio.to_thread(run_v4_law_conflict_audit, db, board, submissions, vote_summary)

    # ---- STAGE 3: 4-Role AI Committee Synthesis ----
    yield {
        "event": "stage",
        "stage": 3,
        "role": "실무 서식·표 편집 전문가 & 최종 교정 편집장",
        "message": "4인 전문가 위원회(구조설계·법규검수·서식편집·교정편집장) 합의로 출판용 원고 초안과 표준 서식을 집필 중...",
    }

    ai_cfg = load_ai_config(db)
    provider_id = ai_cfg.cli_provider
    failover = ai_cfg.failover_enabled

    materials_text = "\n\n".join(
        f"[제출물 {i + 1}: {s['title']} ({s['file_name'] or '직접작성'})]\n"
        f"요약: {s['ai_summary']}\n메모: {s['notes'][:500]}\n본문:\n{(s['extracted_text'] or '')[:1400]}"
        for i, s in enumerate(submissions[:8])
    )
    votes_text = "\n\n".join(
        f"[투표 채택안: {v['cluster_title']} — {v['adopted_label']} ({v['votes']}/{v['total_votes']}표)]\n{v['adopted_content'][:900]}"
        for v in vote_summary
    )
    comments_text = "\n".join(f"- ({c['kind']}) {c['content'][:240]}" for c in comments[:12])
    law_text = "\n".join(f"- [{a['status']}] {a['source']}: {a['note']}" for a in law_audit)

    prompt = f"""당신은 목포사랑의교회 행정표준화위원회(① 체계·목차 설계 전문가, ② 교회 법규 위계 검수 전문가, ③ 실무 서식·표 편집자, ④ 최종 교정 편집장)입니다.
수십 명의 행정·법규 전문가가 모여 완성한 수준의 **공식 정규 행정 표준 규정집 JSON 원고**를 작성하세요.

[편찬 대상 게시글]
제목: {board['title']}
분류: {board['category']} | 작업형태: {board['work_type']}
목적·안내: {board['description']}
적용 교회 결재선: {approval_chain_str} ({approval_preset.get('basis') or approval_preset.get('name', '')})
관리자 추가 편찬 지침: {custom_directives or f'표준 법규 문체, 교회 공식 결재선({approval_chain_str}), 실무 체크리스트 및 표준 서식 포함'}

[투표로 채택된 표준 규격]
{votes_text or '(투표 안건 없음 — 제출 자료 전체를 최적 통합)'}

[수집된 목사님·교역자 행정 자료]
{materials_text or '(제출 자료 없음)'}

[교역자 개선 의견]
{comments_text or '(별도 개선 의견 없음)'}

[참조 상위 법규 정밀 감사 (총회헌법 · 정관 · 시행세칙)]
{law_text or '(기본 정관·시행세칙 준수)'}

[출력 규칙 — 반드시 아래 순수 JSON 객체만 출력]
{{
  "title": "공식 규정집 제목 (예: 목포사랑의교회 재정·회계 행정 표준 규정집)",
  "subtitle": "부제목",
  "executive_summary": "본 규정집의 편찬 목적과 핵심 표준화 요약 (2~3문장)",
  "law_audit_notes": [
    {{"source": "상위 법규명(조항/쪽수)", "status": "정합 확인 | 보완 권고 | 충돌 주의", "note": "검수 의견"}}
  ],
  "chapters": [
    {{
      "title": "제1장 총칙",
      "summary": "장의 취지 1~2문장",
      "articles": [
        {{
          "number": "제1조",
          "title": "조항명",
          "body": "명확하고 간결한 법규/매뉴얼 본문",
          "points": ["세부 기준 1", "세부 기준 2"],
          "practical_tip": "현장 교역자를 위한 1줄 실무 팁"
        }}
      ],
      "table": {{"headers": ["구분", "기준", "결재권자"], "rows": [["예시", "내용", "당회장"]]}}
    }}
  ],
  "standard_forms": [
    {{
      "title": "표준 서식명 (예: 지출 결의서)",
      "purpose": "서식 용도 및 제출 시기",
      "fields": ["작성일", "소속 부서", "성명 / 직분", "항목명", "금액 / 사유", "비고"]
    }}
  ],
  "checklists": [
    {{
      "title": "실무 점검표 제목",
      "items": ["점검 항목 1", "점검 항목 2", "점검 항목 3"]
    }}
  ]
}}
"""

    manuscript: dict[str, Any] | None = None
    used_engine = "offline-committee"
    try:
        raw_parts: list[str] = []
        async for pid, piece in stream_cli_with_failover(
            provider_id, prompt, failover_enabled=failover, timeout_sec=140, ai_config=ai_cfg
        ):
            used_engine = pid
            raw_parts.append(piece)
        raw_str = "".join(raw_parts)
        m = re.search(r"\{[\s\S]*\}", raw_str)
        if m:
            parsed = json.loads(m.group(0))
            if isinstance(parsed, dict) and parsed.get("chapters"):
                manuscript = parsed
                if isinstance(parsed.get("law_audit_notes"), list) and parsed["law_audit_notes"]:
                    law_audit = parsed["law_audit_notes"]
    except Exception:
        manuscript = None

    if not manuscript:
        manuscript = _build_offline_manuscript(board, submissions, proposals, comments, law_audit)
        used_engine = "offline-committee"

    yield {
        "event": "draft",
        "version_label": version_label,
        "manuscript": manuscript,
        "law_audit": law_audit,
        "vote_summary": vote_summary,
        "approval_preset": approval_preset,
        "ai_engine": used_engine,
    }


async def typeset_manuscript_to_publication(
    db: Database,
    store: StandardizationStore,
    board: dict[str, Any],
    manuscript: dict[str, Any],
    law_audit: list[dict[str, Any]],
    vote_summary: list[dict[str, Any]],
    version_label: str,
    created_by: str = "관리자",
    approval_preset_id: str = "",
    custom_approval_slots: list[str] | None = None,
    ai_engine: str = "edited-manuscript",
    include_images: bool = True,
) -> dict[str, Any]:
    """Typeset any AI-generated or human-edited manuscript into A4 PDF + DOCX + HWPX + Revision Diff Report."""
    std_cfg = load_std_config(db)
    pdf_template = std_cfg.get("pdf_template") or DEFAULT_PDF_TEMPLATE
    approval_preset = resolve_approval_preset(
        std_cfg,
        board_category=board.get("category", ""),
        preset_id=approval_preset_id,
        custom_slots=custom_approval_slots,
    )
    approval_slots = list(approval_preset.get("slots") or ["총무", "부장", "지도교역자", "당회장"])

    submissions = store.list_submissions(board["id"], include_archived=False)
    proposals = store.list_proposals(board["id"])
    comments = store.list_comments(board["id"])
    existing_pubs = store.list_publications(board["id"])
    if not version_label.strip():
        version_label = f"v1.{len(existing_pubs)}"

    prev_pub = store.get_latest_publication(board["id"])
    diff_report = (
        build_manuscript_diff_report(
            prev_pub.get("manuscript") if prev_pub else None,
            manuscript,
            prev_version=prev_pub.get("version_label", "") if prev_pub else "",
            curr_version=version_label,
        )
        if prev_pub
        else {}
    )

    image_attachments = (
        await asyncio.to_thread(_collect_board_image_attachments, submissions)
        if include_images
        else []
    )

    pub_html = _render_publication_html(
        board=board,
        manuscript=manuscript,
        law_audit=law_audit,
        vote_summary=vote_summary,
        version_label=version_label,
        created_by=created_by,
        pdf_template=pdf_template,
        approval_preset=approval_preset,
        image_attachments=image_attachments,
        diff_report=diff_report,
        comments_summary=comments,
    )

    pub_dir = get_std_publications_dir(board["id"])
    safe_title = re.sub(r'[\\/:*?"<>|]+', "_", manuscript.get("title") or board["title"])[:60]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pdf_path = pub_dir / f"{safe_title}_{version_label}_{stamp}.pdf"
    docx_path = pub_dir / f"{safe_title}_{version_label}_{stamp}.docx"
    hwpx_path = pub_dir / f"{safe_title}_{version_label}_{stamp}.hwpx"

    pdf_engine = await asyncio.to_thread(_render_html_to_pdf, pub_html, pdf_path)
    await asyncio.to_thread(
        _render_manuscript_docx,
        board,
        manuscript,
        law_audit,
        vote_summary,
        version_label,
        docx_path,
        pdf_template,
        approval_preset,
        image_attachments,
        diff_report,
    )
    await asyncio.to_thread(
        _render_manuscript_hwpx,
        board,
        manuscript,
        law_audit,
        vote_summary,
        version_label,
        hwpx_path,
        pdf_template,
        approval_preset,
        diff_report,
    )

    committee_report = {
        "ai_engine": ai_engine,
        "pdf_engine": pdf_engine,
        "approval_preset_name": approval_preset.get("name", ""),
        "approval_slots": approval_slots,
        "submission_count": len(submissions),
        "proposal_count": len(proposals),
        "comment_count": len(comments),
        "chapter_count": len(manuscript.get("chapters") or []),
        "form_count": len(manuscript.get("standard_forms") or []),
        "image_count": len(image_attachments),
        "diff_change_count": len(diff_report.get("rows") or []),
        "pdf_bytes": pdf_path.stat().st_size if pdf_path.exists() else 0,
        "has_hwpx": hwpx_path.exists(),
    }

    pub = store.create_publication(
        board_id=board["id"],
        version_label=version_label,
        title=manuscript.get("title") or board["title"],
        pdf_path=str(pdf_path),
        docx_path=str(docx_path),
        hwpx_path=str(hwpx_path),
        html_snapshot=pub_html,
        committee_report=committee_report,
        law_audit=law_audit,
        created_by=created_by,
        manuscript=manuscript,
        diff_report=diff_report,
    )
    return pub


async def stream_committee_compile(
    db: Database,
    store: StandardizationStore,
    board: dict[str, Any],
    version_label: str = "",
    custom_directives: str = "",
    created_by: str = "관리자",
    approval_preset_id: str = "",
    custom_approval_slots: list[str] | None = None,
    include_images: bool = True,
) -> AsyncIterator[dict[str, Any]]:
    """
    1-Click 4-Role Expert Committee AI Compilation Pipeline:
      Stage 1: Structure & TOC Architect
      Stage 2: Engine v4.0 Church Law Hierarchy Conflict Auditor
      Stage 3: Administrative Forms & Chief Editor Polish
      Stage 4: A4 PDF + Word(.docx) + Hangul(.hwpx) + 신·구조문 대조표 Typesetting
    """
    draft_payload: dict[str, Any] | None = None
    async for ev in generate_committee_draft_stream(
        db=db,
        store=store,
        board=board,
        version_label=version_label,
        custom_directives=custom_directives,
        approval_preset_id=approval_preset_id,
        custom_approval_slots=custom_approval_slots,
    ):
        if ev.get("event") == "draft":
            draft_payload = ev
        else:
            yield ev

    assert draft_payload is not None

    yield {
        "event": "stage",
        "stage": 4,
        "role": "출판 조판 엔진 (PDF · Word · HWPX)",
        "message": "표지 · 목차 · v4.0 법규 감사표 · 표준 서식 · 신·구조문 대조표를 포함한 PDF · Word(.docx) · 한글(.hwpx) 3종 파일을 조판 중...",
    }

    pub = await typeset_manuscript_to_publication(
        db=db,
        store=store,
        board=board,
        manuscript=draft_payload["manuscript"],
        law_audit=draft_payload["law_audit"],
        vote_summary=draft_payload["vote_summary"],
        version_label=draft_payload["version_label"],
        created_by=created_by,
        approval_preset_id=approval_preset_id,
        custom_approval_slots=custom_approval_slots,
        ai_engine=draft_payload.get("ai_engine", "offline-committee"),
        include_images=include_images,
    )

    yield {
        "event": "done",
        "publication": {k: v for k, v in pub.items() if k not in ("html_snapshot", "manuscript")},
    }


def register_publication_forms_to_vault(
    db: Database,
    store: StandardizationStore,
    pub: dict[str, Any],
    notebook_id: str = DEFAULT_NOTEBOOK_ID,
) -> dict[str, Any]:
    """1-Click register all standard forms from a compiled publication directly into the right-side Forms Vault!"""
    pdf_path = Path(pub.get("pdf_path") or "")
    if not pdf_path.exists():
        raise ValueError("편찬된 PDF 파일을 찾을 수 없습니다.")

    board = store.get_board(pub["board_id"])
    cat_label = (board["category"] if board else "표준 서식")

    # Ensure the compiled PDF exists as a document in the target notebook so Forms Vault downloads/previews work natively
    doc_id = (pub.get("published_doc_id") or "").strip()
    existing_doc = db.get_document(doc_id) if doc_id else None
    if not existing_doc:
        ingested = ingest_file(
            db=db,
            notebook_id=notebook_id or DEFAULT_NOTEBOOK_ID,
            source_path=pdf_path,
            title=f"{pub['title']} ({pub['version_label']})",
            category=cat_label,
            priority=85,
        )
        existing_doc = ingested[0]
        doc_id = existing_doc["id"]
        store.mark_publication_linked_doc(pub["id"], doc_id)

    manuscript = pub.get("manuscript") or {}
    std_forms = manuscript.get("standard_forms") or []
    if not std_forms:
        std_forms = [
            {
                "title": f"{pub['title']} 표준 서식",
                "purpose": f"{cat_label} 공식 행정 표준 양식",
                "fields": ["작성일", "소속 부서", "성명 / 직분", "연락처", "내용 및 사유"],
            }
        ]

    # Locate exact 1-based page number of each standard form inside the compiled PDF
    page_texts: list[str] = []
    pdf_doc = pymupdf.open(str(pdf_path))
    try:
        for i in range(len(pdf_doc)):
            page_texts.append(pdf_doc[i].get_text("text") or "")
    finally:
        pdf_doc.close()

    total_pages = max(1, len(page_texts))
    form_entries: list[dict[str, Any]] = []
    for idx, fm in enumerate(std_forms, start=1):
        f_title = str(fm.get("title") or f"{pub['title']} 표준 서식 제{idx}호").strip()
        f_fields = [str(x).strip() for x in (fm.get("fields") or []) if str(x).strip()]
        f_purpose = str(fm.get("purpose") or "").strip()

        matched_page = total_pages
        marker = f"표준 서식 제{idx}호"
        for p_idx, ptxt in enumerate(page_texts, start=1):
            if marker in ptxt or (len(f_title) >= 4 and f_title in ptxt):
                matched_page = p_idx
                break

        fid = "std_frm_" + hashlib.sha1(f"{pub['id']}:{idx}:{f_title}".encode("utf-8")).hexdigest()[:12]
        sample_lines = [f_title]
        if f_purpose:
            sample_lines.append(f"용도: {f_purpose}")
        for fld in f_fields:
            sample_lines.append(f"{fld}: ")
        form_entries.append(
            {
                "id": fid,
                "title": f"{f_title} ({pub['version_label']})",
                "category": f"표준 서식 · {cat_label}",
                "form_type": "form",
                "page_start": matched_page,
                "page_end": matched_page,
                "has_table": True,
                "sample_text": "\n".join(sample_lines),
                "fields": f_fields or ["작성일", "성명", "직분", "소속", "내용"],
            }
        )

    count = db.upsert_document_forms(doc_id, existing_doc["notebook_id"], form_entries)
    store.mark_publication_forms_registered(pub["id"], count)
    return {"document": existing_doc, "registered_count": count, "forms": form_entries}
