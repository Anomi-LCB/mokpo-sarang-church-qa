from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import docx
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Cm, Pt, RGBColor

from core.config import get_exports_dir


def _set_kr_font(run: Any, size_pt: float = 10.5, bold: bool = False, rgb: tuple[int, int, int] = (29, 29, 31)) -> None:
    run.font.name = "맑은 고딕"
    run.font.size = Pt(size_pt)
    run.bold = bold
    run.font.color.rgb = RGBColor(*rgb)
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    rfonts.set(qn("w:ascii"), "맑은 고딕")
    rfonts.set(qn("w:hAnsi"), "맑은 고딕")
    rfonts.set(qn("w:eastAsia"), "맑은 고딕")


def _shade(cell: Any, fill_hex: str) -> None:
    tcpr = cell._tc.get_or_add_tcPr()
    tcpr.append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>'))


def export_qa_report_docx(
    notebook_name: str,
    question: str,
    answer: str,
    mode: str,
    citations: list[dict[str, Any]],
    verification: dict[str, Any] | None = None,
    author_label: str = "교역자/행정팀",
) -> Path:
    """Export a grounded Q&A and its verified source clauses into an executive Word (.docx) meeting report."""
    out_dir = get_exports_dir() / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_q = re.sub(r'[\\/:*?"<>|\s]+', "_", question.strip())[:30] or "법규검토"
    uid = hashlib.sha1(f"{question}:{answer[:120]}:{datetime.now().isoformat()}".encode("utf-8")).hexdigest()[:6]
    out_path = out_dir / f"법규검토보고서_{safe_q}_{uid}.docx"

    doc = docx.Document()
    for sec in doc.sections:
        sec.top_margin = Cm(2.0)
        sec.bottom_margin = Cm(2.0)
        sec.left_margin = Cm(2.2)
        sec.right_margin = Cm(2.2)

    # Title Header
    p_title = doc.add_paragraph()
    p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_kr_font(p_title.add_run(f"{notebook_name} 검토 보고서"), size_pt=17, bold=True, rgb=(15, 23, 42))

    mode_label = {
        "auto": "자율 판단",
        "practical": "실무 정리",
        "strict": "원문 엄격",
        "advisory": "적용·제안",
        "instant": "즉시 원문 검색",
    }.get(mode, mode)
    verify_label = (verification or {}).get("summary") or "원문 근거 기반"

    # Metadata summary table
    meta_rows = [
        ("작성 일시", datetime.now().strftime("%Y년 %m월 %d일 %H:%M")),
        ("작성자", author_label),
        ("검토 모드 / 검증", f"{mode_label} · {verify_label}"),
        ("검토 질의", question.strip()),
    ]
    tbl = doc.add_table(rows=len(meta_rows), cols=2)
    tbl.style = "Table Grid"
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    for idx, (k, v) in enumerate(meta_rows):
        c0, c1 = tbl.rows[idx].cells[0], tbl.rows[idx].cells[1]
        c0.width = Cm(3.6)
        c1.width = Cm(12.9)
        _shade(c0, "F1F5F9")
        _set_kr_font(c0.paragraphs[0].add_run(k), size_pt=9.5, bold=True, rgb=(30, 41, 59))
        _set_kr_font(c1.paragraphs[0].add_run(v), size_pt=9.5, bold=(idx == 3), rgb=(15, 23, 42))

    doc.add_paragraph()

    # Main Answer Body
    p_sec1 = doc.add_paragraph()
    _set_kr_font(p_sec1.add_run("1. 검토 내용 및 안내"), size_pt=12.5, bold=True, rgb=(0, 102, 214))

    for raw_ln in answer.replace("\r\n", "\n").splitlines():
        ln = raw_ln.strip()
        if not ln:
            continue
        if ln.startswith("### "):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(8)
            p.paragraph_format.space_after = Pt(3)
            _set_kr_font(p.add_run(ln[4:].replace("**", "")), size_pt=11, bold=True, rgb=(15, 23, 42))
        elif ln.startswith("## "):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(10)
            p.paragraph_format.space_after = Pt(4)
            _set_kr_font(p.add_run(ln[3:].replace("**", "")), size_pt=12, bold=True, rgb=(15, 23, 42))
        elif ln.startswith("# "):
            p = doc.add_paragraph()
            _set_kr_font(p.add_run(ln[2:].replace("**", "")), size_pt=13, bold=True, rgb=(15, 23, 42))
        else:
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(3)
            clean = re.sub(r"\*\*([^*]+)\*\*", r"\1", ln)
            clean = re.sub(r"^[-*]\s+", "• ", clean)
            _set_kr_font(p.add_run(clean), size_pt=10, rgb=(30, 41, 59))

    # Grounded Original Clauses Appendix
    if citations:
        doc.add_paragraph()
        p_sec2 = doc.add_paragraph()
        _set_kr_font(p_sec2.add_run("2. 근거 원문 조항 발췌"), size_pt=12.5, bold=True, rgb=(0, 102, 214))

        ctbl = doc.add_table(rows=len(citations) + 1, cols=3)
        ctbl.style = "Table Grid"
        ctbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        headers = ["문서 / 위치", "쪽수", "원문 발췌"]
        widths = [Cm(4.2), Cm(1.8), Cm(10.5)]
        for c_idx, h in enumerate(headers):
            cell = ctbl.rows[0].cells[c_idx]
            cell.width = widths[c_idx]
            _shade(cell, "1E3A5F")
            _set_kr_font(cell.paragraphs[0].add_run(h), size_pt=9.5, bold=True, rgb=(255, 255, 255))

        for r_idx, c in enumerate(citations, start=1):
            row = ctbl.rows[r_idx]
            loc = " · ".join(x for x in (c.get("section_path", ""), c.get("heading", "")) if x)
            p_str = f"p.{c['page_start']}" if c["page_start"] == c["page_end"] else f"p.{c['page_start']}~{c['page_end']}"
            vals = [f"{c['doc_title']}\n{loc}".strip(), p_str, c.get("excerpt", "")[:650]]
            for c_idx, val in enumerate(vals):
                cell = row.cells[c_idx]
                cell.width = widths[c_idx]
                _set_kr_font(cell.paragraphs[0].add_run(val), size_pt=8.8, rgb=(30, 41, 59))

    doc.save(str(out_path))
    return out_path
