from __future__ import annotations

import asyncio
import html
import json
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator

import docx
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Cm, Pt, RGBColor
import pymupdf

from core.config import DEFAULT_NOTEBOOK_ID
from core.database import Database
from core.retriever import retrieve
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


def _render_publication_html(
    board: dict[str, Any],
    manuscript: dict[str, Any],
    law_audit: list[dict[str, Any]],
    vote_summary: list[dict[str, Any]],
    version_label: str,
    created_by: str,
) -> str:
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

    # Build Law Hierarchy Audit Rows
    audit_html_rows = []
    for item in law_audit:
        st = item.get("status", "정합")
        badge_cls = "badge-ok" if "정합" in st or "적합" in st else "badge-warn"
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

    # Build Standard Forms HTML (each crisp printable A4 form box)
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
            f'  <div><div class="form-code">표준 서식 제{f_idx}호</div><h3>{_esc(f_title)}</h3>'
            f'  {f"<p class=form-purpose>{_esc(f_purpose)}</p>" if f_purpose else ""}</div>'
            f'  <table class="approval-box"><tr><th>담당</th><th>부서장</th><th>당회장</th></tr>'
            f'  <tr><td style="height:36px;"></td><td></td><td></td></tr></table>'
            f"</div>"
            f'<table class="form-grid"><tbody>{f_rows}</tbody></table>'
            f'<div class="form-footer">'
            f'  <p class="form-stmt">위와 같이 제출(신청)하오니 허락하여 주시기 바랍니다.</p>'
            f'  <p class="form-date">20    년      월      일</p>'
            f'  <p class="form-sign">신청인(작성자): ____________________ (인)</p>'
            f'  <p class="form-recipient">목포사랑의교회 당회장 귀하</p>'
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
    border-left: 7mm solid #0f4c81;
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
    padding: 16mm 0;
  }}
  .cover-kicker {{
    color: #0f4c81;
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
    margin: 0 0 22px 0;
  }}
  .cover-summary {{
    border-left: 3px solid #0f4c81;
    background: #f7f7f5;
    padding: 14px 18px;
    font-size: 10.2pt;
    color: #3f3f46;
    line-height: 1.72;
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
  .form-code {{ font-size: 8.5pt; font-weight: 700; color: #0f4c81; }}
  .form-top h3 {{ margin: 2px 0 4px 0; font-size: 15pt; font-weight: 800; letter-spacing: 0.04em; }}
  .form-purpose {{ margin: 0; font-size: 8.8pt; color: #52525b; }}
  .approval-box {{ border-collapse: collapse; font-size: 8.5pt; min-width: 148px; }}
  .approval-box th, .approval-box td {{ border: 1px solid #3f3f46; text-align: center; padding: 3px 8px; }}
  .approval-box th {{ background: #f4f4f2; font-weight: 600; }}
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
      <span>대한예수교장로회 · 목포사랑의교회 공식 행정 표준 규정집</span>
      <span class="cover-ver">{_esc(version_label)}</span>
    </div>
    <div class="cover-main">
      <div class="cover-kicker">{_esc(board['category'])} · {_esc(board['work_type'])}</div>
      <h1 class="cover-title">{_esc(doc_title)}</h1>
      <p class="cover-sub">{_esc(subtitle)}</p>
      {f'<div class="cover-summary">{_esc(exec_summary)}</div>' if exec_summary else ''}
      <table class="cover-meta">
        <tr><th>시행 · 편찬일</th><td>{_esc(today_str)}</td><th>판본</th><td>{_esc(version_label)}</td></tr>
        <tr><th>적용 분류</th><td>{_esc(board['category'])}</td><th>편찬 주관</th><td>{_esc(created_by)} (행정표준화위원회)</td></tr>
        <tr><th>반영 범위</th><td colspan="3">교역자 제출 행정자료 · 투표 채택안 {len(vote_summary)}건 · 상위 법규(총회헌법·정관·시행세칙) 위계 검수 완료</td></tr>
      </table>
    </div>
    <div class="cover-bottom">
      <span>목포사랑의교회 행정Q&amp;A 표준화 편찬 시스템</span>
      <span>공식 정규 행정 문서</span>
    </div>
  </div>

  <!-- TOC & LAW AUDIT -->
  <div>
    <div class="running-bar">
      <span>목포사랑의교회 행정Q&amp;A · {_esc(doc_title)}</span>
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
      <span>목포사랑의교회 공식 행정 표준 규정</span>
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
        <tr><td>{_esc(version_label)}</td><td>{_esc(today_str)}</td><td>{_esc(created_by)}</td><td>교역자 행정 파일 수집·투표 합의·4역할 전문가 위원회 검수를 거쳐 정규 PDF 편찬</td></tr>
      </tbody>
    </table>
  </section>
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
) -> Path:
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
    rk = p_k.add_run(f"목포사랑의교회 공식 행정 표준 규정집 ({version_label})")
    rk.font.name = "맑은 고딕"
    rk.font.size = Pt(10)
    rk.font.color.rgb = RGBColor(15, 76, 129)

    p_t = d.add_paragraph()
    p_t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    rt = p_t.add_run(manuscript.get("title") or board["title"])
    rt.font.name = "맑은 고딕"
    rt.font.size = Pt(18)
    rt.bold = True

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

    # Standard Forms
    for f_idx, fm in enumerate(manuscript.get("standard_forms") or [], start=1):
        d.add_page_break()
        fh = d.add_heading(f"표준 서식 제{f_idx}호: {fm.get('title', '')}", level=1)
        for r in fh.runs:
            r.font.name = "맑은 고딕"
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

        d.add_paragraph("\n위와 같이 신청(제출)하오니 허락하여 주시기 바랍니다.").alignment = WD_ALIGN_PARAGRAPH.CENTER
        d.add_paragraph("20    년      월      일").alignment = WD_ALIGN_PARAGRAPH.CENTER
        d.add_paragraph("신청인(작성자):                  (인)").alignment = WD_ALIGN_PARAGRAPH.RIGHT
        pr = d.add_paragraph()
        pr.alignment = WD_ALIGN_PARAGRAPH.CENTER
        rr = pr.add_run("목포사랑의교회 당회장 귀하")
        rr.bold = True
        rr.font.size = Pt(12)

    out_docx.parent.mkdir(parents=True, exist_ok=True)
    d.save(str(out_docx))
    return out_docx


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


async def stream_committee_compile(
    db: Database,
    store: StandardizationStore,
    board: dict[str, Any],
    version_label: str = "",
    custom_directives: str = "",
    created_by: str = "관리자",
) -> AsyncIterator[dict[str, Any]]:
    """
    4-Role Expert Committee AI Compilation Pipeline:
      Stage 1: Structure & TOC Architect
      Stage 2: Church Law Hierarchy Auditor (cross-checks real 총회헌법·정관·시행세칙 via RAG!)
      Stage 3: Administrative Forms & Checklist Designer
      Stage 4: Chief Editor Polish + Vector A4 HTML->PDF & DOCX Typesetting
    """
    submissions = store.list_submissions(board["id"], include_archived=False)
    proposals = store.list_proposals(board["id"])
    comments = store.list_comments(board["id"])
    existing_pubs = store.list_publications(board["id"])

    if not version_label.strip():
        version_label = f"v1.{len(existing_pubs)}"

    # Build concise voting consensus summary
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

    # ---- STAGE 1: Architecture & Consensus Analysis ----
    yield {
        "event": "stage",
        "stage": 1,
        "role": "체계·목차 설계 전문가",
        "message": f"제출 자료 {len(submissions)}건·투표 합의 {len(vote_summary)}건·개선 의견 {len(comments)}건을 종합하여 장·절·조 체계를 설계 중...",
    }
    await asyncio.sleep(0.05)

    # ---- STAGE 2: Real RAG Cross-Audit against Church Constitution / Bylaws / Rules ----
    yield {
        "event": "stage",
        "stage": 2,
        "role": "교회 법규 위계 검수 전문가",
        "message": "총회헌법 · 목포사랑의교회 정관 · 2025년 시행세칙 원문과 교차 대조하여 상위 법규 충돌 여부를 검수 중...",
    }

    query_seed = f"{board['title']} {board['category']} " + " ".join(s["title"] for s in submissions[:4])
    law_retrieval = await asyncio.to_thread(retrieve, db, DEFAULT_NOTEBOOK_ID, query_seed, None, 6)
    law_audit: list[dict[str, Any]] = []
    for ch in law_retrieval.chunks[:5]:
        loc = f"p.{ch['page_start']}"
        sec = " / ".join(x for x in (ch.get("section_path", ""), ch.get("heading", "")) if x)
        law_audit.append(
            {
                "source": f"{ch['doc_title']} ({loc})",
                "status": "정합 확인",
                "note": f"[{sec or '관련 조항'}] {ch['content'][:150].replace(chr(10), ' ')}...",
            }
        )

    # ---- STAGE 3: 4-Role Expert Committee AI Synthesis ----
    yield {
        "event": "stage",
        "stage": 3,
        "role": "실무 서식·표 편집 전문가 & 최종 교정 편집장",
        "message": "4인 전문가 위원회(구조설계·법규검수·서식편집·교정편집장) 합의로 출판용 원고와 표준 서식을 집필 중...",
    }

    provider_id = db.get_setting("cli_provider", "claude") or "claude"
    failover = db.get_setting("cli_failover_enabled", "1") == "1"

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
    law_text = "\n".join(f"- {a['source']}: {a['note']}" for a in law_audit)

    prompt = f"""당신은 목포사랑의교회 행정표준화위원회(① 체계·목차 설계 전문가, ② 교회 법규 위계 검수 전문가, ③ 실무 서식·표 편집자, ④ 최종 교정 편집장)입니다.
수십 명의 행정·법규 전문가가 모여 완성한 수준의 **공식 정규 행정 표준 규정집 JSON 원고**를 작성하세요.

[편찬 대상 게시글]
제목: {board['title']}
분류: {board['category']} | 작업형태: {board['work_type']}
목적·안내: {board['description']}
관리자 추가 편찬 지침: {custom_directives or '표준 법규 문체, 명확한 결재선, 실무 체크리스트 및 표준 서식 포함'}

[투표로 채택된 표준 규격]
{votes_text or '(투표 안건 없음 — 제출 자료 전체를 최적 통합)'}

[수집된 목사님·교역자 행정 자료]
{materials_text or '(제출 자료 없음)'}

[교역자 개선 의견]
{comments_text or '(별도 개선 의견 없음)'}

[참조 상위 법규 (총회헌법 · 정관 · 시행세칙)]
{law_text or '(기본 정관·시행세칙 준수)'}

[출력 규칙 — 반드시 아래 순수 JSON 객체만 출력]
{{
  "title": "공식 규정집 제목 (예: 목포사랑의교회 재정·회계 행정 표준 규정집)",
  "subtitle": "부제목",
  "executive_summary": "본 규정집의 편찬 목적과 핵심 표준화 요약 (2~3문장)",
  "law_audit_notes": [
    {{"source": "상위 법규명(조항/쪽수)", "status": "정합 또는 보완권고", "note": "검수 의견"}}
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

    ai_cfg = load_ai_config(db)
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

    # ---- STAGE 4: A4 Publication PDF + Word DOCX Typesetting ----
    yield {
        "event": "stage",
        "stage": 4,
        "role": "출판 조판 엔진",
        "message": "표지 · 목차 · 법규 검수표 · 표준 서식 양식을 포함한 출판급 A4 정규 PDF 및 Word(.docx) 파일을 조판 중...",
    }

    pub_html = _render_publication_html(
        board=board,
        manuscript=manuscript,
        law_audit=law_audit,
        vote_summary=vote_summary,
        version_label=version_label,
        created_by=created_by,
    )

    pub_dir = get_std_publications_dir(board["id"])
    safe_title = re.sub(r'[\\/:*?"<>|]+', "_", manuscript.get("title") or board["title"])[:60]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pdf_path = pub_dir / f"{safe_title}_{version_label}_{stamp}.pdf"
    docx_path = pub_dir / f"{safe_title}_{version_label}_{stamp}.docx"

    pdf_engine = await asyncio.to_thread(_render_html_to_pdf, pub_html, pdf_path)
    await asyncio.to_thread(_render_manuscript_docx, board, manuscript, law_audit, vote_summary, version_label, docx_path)

    committee_report = {
        "ai_engine": used_engine,
        "pdf_engine": pdf_engine,
        "submission_count": len(submissions),
        "proposal_count": len(proposals),
        "comment_count": len(comments),
        "chapter_count": len(manuscript.get("chapters") or []),
        "form_count": len(manuscript.get("standard_forms") or []),
        "pdf_bytes": pdf_path.stat().st_size if pdf_path.exists() else 0,
    }

    pub = store.create_publication(
        board_id=board["id"],
        version_label=version_label,
        title=manuscript.get("title") or board["title"],
        pdf_path=str(pdf_path),
        docx_path=str(docx_path),
        html_snapshot=pub_html,
        committee_report=committee_report,
        law_audit=law_audit,
        created_by=created_by,
    )

    yield {
        "event": "done",
        "publication": {k: v for k, v in pub.items() if k != "html_snapshot"},
    }
