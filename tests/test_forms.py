from __future__ import annotations

import asyncio
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

import docx
import openpyxl
import pymupdf

from core.config import DEFAULT_NOTEBOOK_ID
from core.database import Database
from core.forms import export_editable_docx, export_editable_hwpx, export_original_pdf, export_table_xlsx
from core.ingest import _extract_hwpx_pages
from server.cli_providers import generate_autofill_structure


def test_forms_catalog_and_all_export_formats(tmp_path: Path):
    db = Database()
    forms = db.list_forms(DEFAULT_NOTEBOOK_ID)
    assert len(forms) >= 50, f"Expected >= 50 cataloged forms/tables, got {len(forms)}"

    # Find a specific well-known church form (e.g., 신청서 or 지원서 or 소원장)
    target = next(
        (f for f in forms if any(k in f["title"] for k in ["학습", "세례", "지원서", "청원서", "보고서"])),
        forms[0],
    )

    # 1. Original PDF slice
    pdf_out = export_original_pdf(target, out_path=tmp_path / "orig.pdf")
    assert pdf_out.exists() and pdf_out.stat().st_size > 1000
    d = pymupdf.open(str(pdf_out))
    assert len(d) == (target["page_end"] - target["page_start"] + 1)
    d.close()

    # 2. Editable DOCX
    docx_out = export_editable_docx(target, out_path=tmp_path / "blank.docx")
    assert docx_out.exists() and docx_out.stat().st_size > 5000
    wd = docx.Document(str(docx_out))
    assert len(wd.paragraphs) >= 1

    # 3. Table XLSX
    xlsx_out = export_table_xlsx(target, out_path=tmp_path / "table.xlsx")
    assert xlsx_out.exists() and xlsx_out.stat().st_size > 3000
    wb = openpyxl.load_workbook(str(xlsx_out))
    ws = wb.active
    assert ws["A1"].value == target["title"]
    assert ws.max_row >= 4

    # 3b. Editable Hancom HWPX (KS X 6101 OWPML)
    hwpx_out = export_editable_hwpx(target, out_path=tmp_path / "blank.hwpx")
    assert hwpx_out.exists() and hwpx_out.stat().st_size > 1200
    with zipfile.ZipFile(str(hwpx_out), "r") as zf:
        infos = zf.infolist()
        assert infos[0].filename == "mimetype"
        assert infos[0].compress_type == zipfile.ZIP_STORED
        assert zf.read("mimetype").decode("utf-8") == "application/hwp+zip"
        ET.fromstring(zf.read("Contents/header.xml"))
        ET.fromstring(zf.read("Contents/section0.xml"))
    parsed_hwpx = _extract_hwpx_pages(hwpx_out)
    assert len(parsed_hwpx) >= 1 and target["title"] in parsed_hwpx[0]["text"]

    # 4. AI Auto-Fill (deterministic structured check + DOCX generation)
    structured = asyncio.run(
        generate_autofill_structure(
            provider_id="claude",
            form=target,
            user_instruction="성명: 홍길동, 연락처: 010-1234-5678, 신청일: 2026년 11월 26일",
            use_cli=False,
        )
    )
    filled_docx = export_editable_docx(target, filled_data=structured, out_path=tmp_path / "filled.docx")
    assert filled_docx.exists()
    wd2 = docx.Document(str(filled_docx))
    all_text = "\n".join(p.text for p in wd2.paragraphs) + "\n" + "\n".join(
        cell.text for tbl in wd2.tables for row in tbl.rows for cell in row.cells
    )
    assert "홍길동" in all_text
    assert "010-1234-5678" in all_text
