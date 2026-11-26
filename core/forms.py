from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import docx
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Cm, Pt, RGBColor
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
import pymupdf

from core.config import get_exports_dir

_TOC_NOISE_RE = re.compile(r"[·\.…]{5,}")
_FORM_TITLE_RE = re.compile(
    r"(?:(?:권징|정치|행정)\s*서식\s*[-ㅡ_一ᅭ]?\s*\d*\.?\s*[^\n]{2,40}|"
    r"〈[^〉]{2,30}서식[^〉]*〉|"
    r"별지\s*제?\s*\d+호[^\n]{0,30}|"
    r"별표\s*\d*[^\n]{0,30}|"
    r"부\s*록\s+(?:[가-힣·\s\d\.]{2,30}(?:신청서|청원서|청구서|지원서|보고서|평가서|언약서|서식|양식|표))|"
    r"(?:\d+\.\s*)?[가-힣·\s\(\)]{2,25}(?:신청서|청원서|청구서|지원서|보고서|평가서|언약서|통지서|결정서|소원장|상소장|답변서|이의서|증서|위임장|일지|명부|전결표|조견표))"
)
_FALSE_FORM_NOISE_RE = re.compile(
    r"(신도게요|요리문답|편집\s*출간|머리말|목\s*차|헌법적\s*규칙\s*•|"
    r"행정서식은\s*당회결의로|탐문하여\s*그\s*회보를|교회\s*밖\s*식당에서)"
)
_CURATED_TITLE_MAP: list[tuple[str, int, str, str]] = [
    ("시행세칙", 24, "", ""),  # body clause mentioning 복직 청원서 (actual form is p.26)
    ("시행세칙", 25, "휴직 청원서 양식", "행정 서식"),
    ("시행세칙", 26, "복직 청원서 양식", "행정 서식"),
    ("시행세칙", 63, "위임전결규정 전결권자표", "규정·기준표"),
    ("시행세칙", 64, "감사 시행세칙 기준표", "규정·기준표"),
    ("시행세칙", 65, "", ""),
    ("시행세칙", 93, "교구 편성 기준표", "규정·기준표"),
    ("시행세칙", 104, "교사훈련 과정표", "교육·부서 서식"),
    ("시행세칙", 113, "부서 보고서 (교육위원회)", "교육·부서 서식"),
    ("시행세칙", 114, "임원 청원서", "교육·부서 서식"),
    ("시행세칙", 115, "교사 지원서", "교육·부서 서식"),
    ("시행세칙", 116, "주일학교 생애 발달 특성표 (1)", "규정·기준표"),
    ("시행세칙", 117, "주일학교 생애 발달 특성표 (2)", "규정·기준표"),
    ("시행세칙", 134, "선교사 계속후원 신청서", "행정 서식"),
    ("시행세칙", 135, "선교사역 보고서", "교육·부서 서식"),
    ("시행세칙", 136, "선교 재정보고서", "규정·기준표"),
    ("시행세칙", 137, "내년도 선교 예산보고서", "행정 서식"),
    ("시행세칙", 163, "", ""),
    ("시행세칙", 195, "셀사역 보고서", "목회·셀 서식"),
    ("시행세칙", 196, "셀사역자 자기 평가서 (1)", "목회·셀 서식"),
    ("시행세칙", 197, "셀사역자 자기 평가서 (2) · 셀가족모임 언약서", "목회·셀 서식"),
    ("시행세칙", 221, "학습·세례 신청서", "목회·셀 서식"),
    ("해설서", 180, "", ""),
]
_KNOWN_FIELD_KEYWORDS = [
    "성명", "이름", "생년월일", "연락처", "전화번호", "휴대전화", "주소",
    "소속", "부서", "직분", "교구", "셀", "수신", "발신", "제목",
    "청원인", "신청인", "지원자", "원고", "피고", "상소인", "소원인",
    "기간", "일시", "날짜", "장소", "사유", "내용", "비고", "금액",
    "세례일", "등록일", "담당자", "확인", "비고", "추천인",
]


def _make_form_id(doc_id: str, page_start: int, idx: int) -> str:
    raw = f"{doc_id}:{page_start}:{idx}"
    return "frm_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _is_toc_page(text: str) -> bool:
    if not text:
        return False
    dotted_lines = sum(1 for ln in text.splitlines() if _TOC_NOISE_RE.search(ln))
    if dotted_lines >= 4:
        return True
    first_lines = "\n".join(text.splitlines()[:5])
    if re.search(r"목\s*차", first_lines) and dotted_lines >= 2:
        return True
    return False


def _clean_form_title(raw: str) -> str:
    t = re.sub(r"\s+", " ", raw.replace("\x01", " ")).strip()
    t = re.sub(r"^[-\s·•\d\.]+\s*(?=권징|정치|부록)", "", t)
    t = t.replace("ᅳ", "-").replace("ᅭ", "-").replace("一", "-").replace("_", "-")
    t = re.sub(r"\(([^)>]+)>", r"(\1)", t)
    t = re.sub(r"\s*-\s*", " - ", t)
    t = re.sub(r"\s*\.\s*", ". ", t)
    t = re.sub(r"\s{2,}", " ", t)
    t = re.sub(r"\s*[-_]\s*$", "", t)
    return t[:80].strip()


def _extract_fields_from_text(text: str) -> list[str]:
    found: list[str] = []
    compact = re.sub(r"\s+", " ", text)
    for kw in _KNOWN_FIELD_KEYWORDS:
        spaced = r"\s*".join(list(kw))
        if re.search(spaced, compact):
            if kw not in found:
                found.append(kw)
    # Also detect "항목명 :" patterns
    for m in re.finditer(r"([가-힣]{2,10})\s*[:：]", text):
        label = m.group(1).strip()
        if label not in found and len(label) <= 10 and label not in {"참고", "주의", "예시", "구분"}:
            found.append(label)
    return found[:16]


def detect_forms_for_pdf(doc_id: str, doc_title: str, pdf_path: Path, pages_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Scan a PDF and its extracted pages to catalog forms and structured tables."""
    forms: list[dict[str, Any]] = []
    doc = pymupdf.open(str(pdf_path))
    try:
        page_text_map = {p["page_no"]: p["text"] for p in pages_data}
        idx = 0
        for i in range(len(doc)):
            pno = i + 1
            text = page_text_map.get(pno, "")
            if _is_toc_page(text):
                continue

            page = doc[i]
            drawings_count = len(page.get_drawings())
            tables = []
            if drawings_count >= 8:
                try:
                    tf = page.find_tables()
                    tables = [t for t in tf.tables if t.row_count >= 2 and t.col_count >= 2]
                except Exception:
                    tables = []

            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            head_block = "\n".join(lines[:10])
            if _FALSE_FORM_NOISE_RE.search("\n".join(lines[:3])):
                continue
            match = _FORM_TITLE_RE.search(head_block)

            # Avoid body prose mentioning "청원서" inside a normal article paragraph
            has_form_marker = False
            if match:
                m_str = match.group(0).strip()
                if _FALSE_FORM_NOISE_RE.search(m_str):
                    match = None
                elif any(k in m_str for k in ["서식", "부록", "별지", "별표"]) or drawings_count >= 10 or len(tables) >= 1:
                    has_form_marker = True
                elif any(ln == m_str or ln.endswith(m_str) for ln in lines[:6]) and len(m_str) <= 35:
                    if any(k in text for k in ["(인)", "수신", "귀하", "성명", "신청인", "청원인", "제출", "항목", "NO", "년   월"]):
                        has_form_marker = True

            has_significant_table = False
            if len(tables) >= 1:
                max_cells = max(t.row_count * t.col_count for t in tables)
                if max_cells >= 8:
                    has_significant_table = True

            if not has_form_marker and not has_significant_table:
                continue

            # Apply curated clean title / exclusion overrides if known document page
            curated_skip = False
            curated_title = ""
            curated_cat = ""
            for doc_key, target_pno, c_title, c_cat in _CURATED_TITLE_MAP:
                if doc_key in doc_title and pno == target_pno:
                    if not c_title:
                        curated_skip = True
                    else:
                        curated_title = c_title
                        curated_cat = c_cat
                    break
            if curated_skip:
                continue

            # Determine clean title & category
            if curated_title:
                title = curated_title
            elif match:
                title = _clean_form_title(match.group(0))
            else:
                # Pick first meaningful non-page-number line
                candidate = next(
                    (ln for ln in lines[:6] if not re.match(r"^[-–—\s\d]+$", ln) and len(ln) >= 3),
                    f"{doc_title} 표 ({pno}쪽)",
                )
                title = _clean_form_title(candidate)

            if not title or len(title) < 2:
                title = f"{doc_title} 서식 ({pno}쪽)"

            if curated_cat:
                category = curated_cat
            elif "권징" in title or "권징 서식" in head_block:
                category = "권징 서식"
            elif "정치" in title or "청빙" in title or "위임" in title:
                category = "행정·위임 서식"
            elif "셀" in title or "심방" in title or "세례" in title:
                category = "목회·셀 서식"
            elif "교사" in title or "부서" in title or "임원" in title or "교육" in title:
                category = "교육·부서 서식"
            elif has_significant_table and not has_form_marker:
                category = "규정·기준표"
            else:
                category = "행정 서식"

            form_type = "table" if (has_significant_table and not has_form_marker) else "form"
            fields = _extract_fields_from_text(text)

            idx += 1
            forms.append(
                {
                    "id": _make_form_id(doc_id, pno, idx),
                    "title": title,
                    "category": category,
                    "form_type": form_type,
                    "page_start": pno,
                    "page_end": pno,
                    "has_table": bool(tables) or drawings_count >= 12,
                    "sample_text": text[:1500],
                    "fields": fields,
                }
            )
    finally:
        doc.close()

    return forms


def detect_forms_for_non_pdf(doc_id: str, doc_title: str, pages_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect form/table sections in DOCX/XLSX/TXT/HWPX documents."""
    forms: list[dict[str, Any]] = []
    idx = 0
    for p in pages_data:
        text = p["text"]
        pno = p["page_no"]
        is_tbl = bool(p.get("has_table")) or text.count("|") >= 8
        m = _FORM_TITLE_RE.search("\n".join(text.splitlines()[:8]))
        if not is_tbl and not m:
            continue
        title = _clean_form_title(m.group(0)) if m else f"{doc_title} 표/시트 ({pno})"
        idx += 1
        forms.append(
            {
                "id": _make_form_id(doc_id, pno, idx),
                "title": title,
                "category": "문서 표/서식",
                "form_type": "table" if is_tbl and not m else "form",
                "page_start": pno,
                "page_end": pno,
                "has_table": is_tbl,
                "sample_text": text[:1500],
                "fields": _extract_fields_from_text(text),
            }
        )
    return forms


def render_pdf_page_png(pdf_path: Path, page_no: int, dpi: int = 160) -> bytes:
    """Render a 1-based PDF page as PNG bytes with disk cache."""
    cache_dir = get_exports_dir() / "page_previews"
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(f"{pdf_path}:{pdf_path.stat().st_mtime_ns}:{page_no}:{dpi}".encode()).hexdigest()[:16]
    cache_file = cache_dir / f"{key}_p{page_no}.png"
    if cache_file.exists():
        return cache_file.read_bytes()

    doc = pymupdf.open(str(pdf_path))
    try:
        idx = max(0, min(page_no - 1, len(doc) - 1))
        pix = doc[idx].get_pixmap(dpi=dpi)
        png_bytes = pix.tobytes("png")
        cache_file.write_bytes(png_bytes)
        return png_bytes
    finally:
        doc.close()


def export_original_pdf(form: dict[str, Any], out_path: Path | None = None) -> Path:
    """Slice original page(s) losslessly from the source PDF."""
    src_path = Path(form["doc_path"])
    if not src_path.exists() or src_path.suffix.lower() != ".pdf":
        raise ValueError("원본 PDF 파일이 존재하지 않습니다.")

    out_dir = get_exports_dir() / "forms"
    out_dir.mkdir(parents=True, exist_ok=True)
    if out_path is None:
        safe = re.sub(r'[\\/:*?"<>|]+', "_", form["title"])[:45]
        out_path = out_dir / f"{form['id']}_{safe}.pdf"

    src = pymupdf.open(str(src_path))
    dst = pymupdf.open()
    try:
        p_start = max(0, form["page_start"] - 1)
        p_end = max(p_start, min(form["page_end"] - 1, len(src) - 1))
        dst.insert_pdf(src, from_page=p_start, to_page=p_end)
        dst.save(str(out_path))
    finally:
        dst.close()
        src.close()
    return out_path


def _extract_pdf_tables_data(pdf_path: Path, page_start: int, page_end: int) -> list[list[list[str]]]:
    all_tables: list[list[list[str]]] = []
    if not pdf_path.exists() or pdf_path.suffix.lower() != ".pdf":
        return all_tables
    doc = pymupdf.open(str(pdf_path))
    try:
        for pno in range(page_start, page_end + 1):
            if 1 <= pno <= len(doc):
                try:
                    tf = doc[pno - 1].find_tables()
                    for t in tf.tables:
                        rows = t.extract()
                        cleaned = [
                            [re.sub(r"\s+", " ", (c or "").replace("\x01", " ")).strip() for c in row]
                            for row in rows
                            if any((c or "").strip() for c in row)
                        ]
                        if cleaned:
                            all_tables.append(cleaned)
                except Exception:
                    pass
    finally:
        doc.close()
    return all_tables


def export_table_xlsx(form: dict[str, Any], out_path: Path | None = None) -> Path:
    """Export form/table content into a styled Excel .xlsx workbook."""
    out_dir = get_exports_dir() / "forms"
    out_dir.mkdir(parents=True, exist_ok=True)
    if out_path is None:
        safe = re.sub(r'[\\/:*?"<>|]+', "_", form["title"])[:45]
        out_path = out_dir / f"{form['id']}_{safe}.xlsx"

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "서식_표"

    header_fill = PatternFill(start_color="1E3A5F", end_color="1E3A5F", fill_type="solid")
    sub_fill = PatternFill(start_color="EEF2F7", end_color="EEF2F7", fill_type="solid")
    thin = Side(border_style="thin", color="CBD5E1")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    title_font = Font(name="맑은 고딕", size=14, bold=True, color="0F172A")
    header_font = Font(name="맑은 고딕", size=10, bold=True, color="FFFFFF")
    body_font = Font(name="맑은 고딕", size=10, color="1E293B")

    ws["A1"] = form["title"]
    ws["A1"].font = title_font
    ws["A2"] = f"출처: {form.get('doc_title', '')} (p.{form['page_start']})"
    ws["A2"].font = Font(name="맑은 고딕", size=9, color="64748B")

    row_cursor = 4
    pdf_path = Path(form.get("doc_path", ""))
    tables = _extract_pdf_tables_data(pdf_path, form["page_start"], form["page_end"])

    if tables:
        for t_idx, rows in enumerate(tables):
            if t_idx > 0:
                row_cursor += 1
            for r_idx, r in enumerate(rows):
                for c_idx, val in enumerate(r, start=1):
                    cell = ws.cell(row=row_cursor, column=c_idx, value=val)
                    cell.border = border
                    cell.alignment = Alignment(vertical="center", wrap_text=True)
                    if r_idx == 0:
                        cell.fill = header_fill
                        cell.font = header_font
                    else:
                        cell.font = body_font
                row_cursor += 1
    else:
        # Fallback: structured key/value or line table from extracted text
        ws.cell(row=row_cursor, column=1, value="항목 / 구분").fill = header_fill
        ws.cell(row=row_cursor, column=1).font = header_font
        ws.cell(row=row_cursor, column=1).border = border
        ws.cell(row=row_cursor, column=2, value="내용").fill = header_fill
        ws.cell(row=row_cursor, column=2).font = header_font
        ws.cell(row=row_cursor, column=2).border = border
        row_cursor += 1

        sample = form.get("sample_text", "")
        for ln in sample.splitlines():
            ln = ln.strip()
            if not ln:
                continue
            if ":" in ln or "：" in ln:
                parts = re.split(r"[:：]", ln, maxsplit=1)
                k, v = parts[0].strip(), parts[1].strip()
            else:
                k, v = "", ln
            c1 = ws.cell(row=row_cursor, column=1, value=k)
            c2 = ws.cell(row=row_cursor, column=2, value=v)
            if k:
                c1.fill = sub_fill
            c1.font = Font(name="맑은 고딕", size=10, bold=bool(k))
            c2.font = body_font
            c1.border = border
            c2.border = border
            c1.alignment = Alignment(vertical="center", wrap_text=True)
            c2.alignment = Alignment(vertical="center", wrap_text=True)
            row_cursor += 1

    # Auto-fit columns cleanly
    for col in ws.columns:
        col_letter = col[0].column_letter
        max_len = 12
        for cell in col:
            if cell.value:
                max_len = max(max_len, min(len(str(cell.value)) + 4, 52))
        ws.column_dimensions[col_letter].width = max_len

    wb.save(str(out_path))
    return out_path


def _set_korean_font(run: Any, size_pt: float = 10.5, bold: bool = False, color_rgb: tuple[int, int, int] | None = None) -> None:
    run.font.name = "맑은 고딕"
    run.font.size = Pt(size_pt)
    run.bold = bold
    if color_rgb:
        run.font.color.rgb = RGBColor(*color_rgb)
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    rfonts.set(qn("w:ascii"), "맑은 고딕")
    rfonts.set(qn("w:hAnsi"), "맑은 고딕")
    rfonts.set(qn("w:eastAsia"), "맑은 고딕")


def _shade_cell(cell: Any, fill_hex: str) -> None:
    tcpr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
    tcpr.append(shd)


def export_editable_docx(
    form: dict[str, Any],
    filled_data: dict[str, Any] | None = None,
    out_path: Path | None = None,
) -> Path:
    """Create a clean, editable Korean Word (.docx) form — optionally pre-filled by AI."""
    out_dir = get_exports_dir() / ("autofill" if filled_data else "forms")
    out_dir.mkdir(parents=True, exist_ok=True)
    if out_path is None:
        safe = re.sub(r'[\\/:*?"<>|]+', "_", form["title"])[:45]
        suffix = "_작성본" if filled_data else ""
        uid = hashlib.sha1(json.dumps(filled_data or {}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:6] if filled_data else ""
        tag = f"_{uid}" if uid else ""
        out_path = out_dir / f"{form['id']}_{safe}{suffix}{tag}.docx"

    document = docx.Document()
    for sec in document.sections:
        sec.top_margin = Cm(2.0)
        sec.bottom_margin = Cm(2.0)
        sec.left_margin = Cm(2.2)
        sec.right_margin = Cm(2.2)

    # Title
    p_title = document.add_paragraph()
    p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r_title = p_title.add_run(filled_data.get("document_title") if filled_data and filled_data.get("document_title") else form["title"])
    _set_korean_font(r_title, size_pt=17, bold=True, color_rgb=(15, 23, 42))

    # Source subtitle
    p_sub = document.add_paragraph()
    p_sub.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    r_sub = p_sub.add_run(f"근거 출처: {form.get('doc_title', '')} (p.{form['page_start']})")
    _set_korean_font(r_sub, size_pt=8.5, color_rgb=(100, 116, 139))

    if filled_data:
        # AI Auto-Filled structured form
        fields_list: list[dict[str, str]] = filled_data.get("fields", [])
        if fields_list:
            tbl = document.add_table(rows=len(fields_list), cols=2)
            tbl.style = "Table Grid"
            tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
            for idx, item in enumerate(fields_list):
                row = tbl.rows[idx]
                c0, c1 = row.cells[0], row.cells[1]
                c0.width = Cm(4.5)
                c1.width = Cm(12.0)
                _shade_cell(c0, "EEF2F7")
                p0 = c0.paragraphs[0]
                _set_korean_font(p0.add_run(str(item.get("label", ""))), size_pt=10, bold=True, color_rgb=(30, 41, 59))
                p1 = c1.paragraphs[0]
                val = str(item.get("value", "")).strip() or "____________________"
                _set_korean_font(p1.add_run(val), size_pt=10, color_rgb=(15, 23, 42))

        body_paragraphs = filled_data.get("body_paragraphs", [])
        if body_paragraphs:
            document.add_paragraph()
            for para_text in body_paragraphs:
                p = document.add_paragraph()
                _set_korean_font(p.add_run(str(para_text)), size_pt=10.5)

        footer_date = filled_data.get("date_line") or "20    년      월      일"
        signer = filled_data.get("signer_line") or "신청인(제출자):                    (인)"
        recipient = filled_data.get("recipient_line") or ""

        document.add_paragraph()
        p_date = document.add_paragraph()
        p_date.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _set_korean_font(p_date.add_run(footer_date), size_pt=11)

        p_sign = document.add_paragraph()
        p_sign.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        _set_korean_font(p_sign.add_run(signer), size_pt=11, bold=True)

        if recipient:
            p_rec = document.add_paragraph()
            p_rec.alignment = WD_ALIGN_PARAGRAPH.LEFT
            _set_korean_font(p_rec.add_run(recipient), size_pt=12, bold=True)
    else:
        # Clean blank/template rebuild from PDF tables & text
        pdf_path = Path(form.get("doc_path", ""))
        tables = _extract_pdf_tables_data(pdf_path, form["page_start"], form["page_end"])
        if tables:
            for rows in tables:
                n_cols = max(len(r) for r in rows)
                tbl = document.add_table(rows=len(rows), cols=n_cols)
                tbl.style = "Table Grid"
                tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
                for r_idx, r in enumerate(rows):
                    for c_idx in range(n_cols):
                        cell = tbl.rows[r_idx].cells[c_idx]
                        if r_idx == 0:
                            _shade_cell(cell, "1E3A5F")
                        txt = r[c_idx] if c_idx < len(r) else ""
                        p = cell.paragraphs[0]
                        _set_korean_font(
                            p.add_run(txt),
                            size_pt=9.5,
                            bold=(r_idx == 0),
                            color_rgb=(255, 255, 255) if r_idx == 0 else (15, 23, 42),
                        )
                document.add_paragraph()
        elif form.get("fields"):
            fields = form["fields"]
            tbl = document.add_table(rows=len(fields), cols=2)
            tbl.style = "Table Grid"
            tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
            for idx, f_label in enumerate(fields):
                c0, c1 = tbl.rows[idx].cells[0], tbl.rows[idx].cells[1]
                c0.width = Cm(4.5)
                c1.width = Cm(12.0)
                _shade_cell(c0, "EEF2F7")
                _set_korean_font(c0.paragraphs[0].add_run(f_label), size_pt=10, bold=True)
                _set_korean_font(c1.paragraphs[0].add_run(""), size_pt=10)
            document.add_paragraph()

        # Include clean reference original wording below
        sample_text = (form.get("sample_text") or "").strip()
        if sample_text:
            p_hdr = document.add_paragraph()
            _set_korean_font(p_hdr.add_run("[원본 서식 문구]"), size_pt=9.5, bold=True, color_rgb=(71, 85, 105))
            for ln in sample_text.splitlines():
                ln = ln.strip()
                if ln:
                    p = document.add_paragraph()
                    p.paragraph_format.space_after = Pt(2)
                    _set_korean_font(p.add_run(ln), size_pt=9.5, color_rgb=(51, 65, 85))

    document.save(str(out_path))
    return out_path
