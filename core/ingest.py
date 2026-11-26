from __future__ import annotations

import hashlib
import re
import shutil
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any, Callable

import docx
import openpyxl
import pymupdf

from core.config import DEFAULT_NOTEBOOK_ID, SEED_ARCHIVES, get_base_dir, get_docs_dir
from core.database import Database
from core.forms import detect_forms_for_non_pdf, detect_forms_for_pdf
from core.ocr_winrt import ocr_pdf_pages, postprocess_ocr_text

SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".docx", ".xlsx", ".hwpx", ".zip"}

_PART_RE = re.compile(r"^(제\s*\d+\s*편[^\n]{0,40}|[ⅠⅡⅢⅣⅤⅥI-V]+\.\s*[^\n]{2,40})$")
_CHAPTER_RE = re.compile(r"^(제\s*\d+\s*장[^\n]{0,50})$")
_ARTICLE_RE = re.compile(
    r"^(제\s*\d+\s*조(?:\s*의\s*\d+)?[^\n]{0,65}|"
    r"문\s*\d+\.\s*[^\n]{2,80}|"
    r"\[?별표\s*\d*\]?[^\n]{0,60}|"
    r"부\s*칙[^\n]{0,40})$"
)


def _extract_markdown_tables(page: pymupdf.Page) -> list[str]:
    """Use PyMuPDF layout table detection to preserve exact row/column cell alignment as Markdown."""
    md_tables: list[str] = []
    try:
        finder = page.find_tables()
        tables = getattr(finder, "tables", None) or []
        for tbl in tables[:4]:
            rows = tbl.extract() or []
            cleaned_rows: list[list[str]] = []
            for r in rows:
                cells = [re.sub(r"\s+", " ", (c or "")).strip().replace("|", "/") for c in r]
                if any(cells):
                    cleaned_rows.append(cells)
            if len(cleaned_rows) < 2:
                continue
            max_cols = max(len(r) for r in cleaned_rows)
            if max_cols < 2 or max_cols > 14:
                continue
            norm_rows = [r + [""] * (max_cols - len(r)) for r in cleaned_rows]
            header = "| " + " | ".join(norm_rows[0]) + " |"
            sep = "| " + " | ".join("---" for _ in range(max_cols)) + " |"
            body = ["| " + " | ".join(r) + " |" for r in norm_rows[1:40]]
            md_tables.append(clean_text("\n".join([header, sep, *body])))
    except Exception:
        pass
    return md_tables


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\x01", " ").replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"제\s*(\d+)\s*([편장절조항관])", r"제\1\2", text)
    lines = [re.sub(r"[ \t]{2,}", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def _doc_id_for(notebook_id: str, filename: str, content_hash: str) -> str:
    raw = f"{notebook_id}:{filename}:{content_hash}"
    return "doc_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14]


def _file_hash(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()[:16]


def _extract_pdf_pages(
    pdf_path: Path,
    progress_cb: Callable[[int, int, str], None] | None = None,
    ocr_dpi: int = 260,
) -> tuple[list[dict[str, Any]], int]:
    doc = pymupdf.open(str(pdf_path))
    total_pages = len(doc)
    raw_pages: list[dict[str, Any]] = []
    ocr_needed: list[int] = []
    try:
        for i in range(total_pages):
            pno = i + 1
            page = doc[i]
            txt = clean_text(page.get_text("text"))
            has_img = len(page.get_images()) > 0
            drawings = len(page.get_drawings())
            has_table = drawings >= 15
            if len(txt) < 25 and has_img:
                ocr_needed.append(pno)
            elif len(txt) >= 25 and drawings >= 8:
                md_tables = _extract_markdown_tables(page)
                if md_tables:
                    has_table = True
                    # Append structured Markdown table block for cell-accurate table retrieval
                    tbl_block = "\n\n[구조화 표]\n" + "\n\n".join(md_tables)
                    if len(tbl_block) <= 4500:
                        txt = txt + tbl_block
            raw_pages.append(
                {
                    "page_no": pno,
                    "text": txt,
                    "is_ocr": False,
                    "has_table": has_table,
                    "has_form": False,
                }
            )
    finally:
        doc.close()

    if ocr_needed:
        ocr_map = ocr_pdf_pages(
            pdf_path=pdf_path,
            page_numbers_1based=ocr_needed,
            dpi=ocr_dpi,
            workers=6,
            progress_cb=progress_cb,
        )
        for p in raw_pages:
            if p["page_no"] in ocr_map:
                ocr_txt = postprocess_ocr_text(ocr_map[p["page_no"]])
                if len(ocr_txt) > len(p["text"]):
                    p["text"] = ocr_txt
                    p["is_ocr"] = True

    return raw_pages, len(ocr_needed)


def _extract_txt_pages(path: Path) -> list[dict[str, Any]]:
    raw = path.read_bytes()
    text = ""
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    text = clean_text(text)
    # Split into logical ~2500-char pages
    pages: list[dict[str, Any]] = []
    buf: list[str] = []
    size = 0
    pno = 1
    for ln in text.splitlines():
        buf.append(ln)
        size += len(ln) + 1
        if size >= 2400:
            pages.append({"page_no": pno, "text": "\n".join(buf), "is_ocr": False, "has_table": False, "has_form": False})
            pno += 1
            buf = []
            size = 0
    if buf or not pages:
        pages.append({"page_no": pno, "text": "\n".join(buf), "is_ocr": False, "has_table": False, "has_form": False})
    return pages


def _extract_docx_pages(path: Path) -> list[dict[str, Any]]:
    d = docx.Document(str(path))
    blocks: list[str] = []
    has_table = bool(d.tables)
    for p in d.paragraphs:
        t = p.text.strip()
        if t:
            blocks.append(t)
    for tbl in d.tables:
        rows_md: list[str] = []
        for r in tbl.rows:
            vals = [re.sub(r"\s+", " ", c.text).strip() for c in r.cells]
            rows_md.append(" | ".join(vals))
        if rows_md:
            blocks.append("\n".join(rows_md))

    full = clean_text("\n".join(blocks))
    pages: list[dict[str, Any]] = []
    chunk_size = 2400
    for idx in range(0, max(1, len(full)), chunk_size):
        pages.append(
            {
                "page_no": len(pages) + 1,
                "text": full[idx : idx + chunk_size],
                "is_ocr": False,
                "has_table": has_table,
                "has_form": False,
            }
        )
    return pages


def _extract_xlsx_pages(path: Path) -> list[dict[str, Any]]:
    wb = openpyxl.load_workbook(str(path), data_only=True)
    pages: list[dict[str, Any]] = []
    for idx, name in enumerate(wb.sheetnames, start=1):
        ws = wb[name]
        lines = [f"[시트: {name}]"]
        for row in ws.iter_rows(values_only=True):
            vals = [str(v).strip() if v is not None else "" for v in row]
            if any(vals):
                lines.append(" | ".join(vals))
        pages.append(
            {
                "page_no": idx,
                "text": clean_text("\n".join(lines)),
                "is_ocr": False,
                "has_table": True,
                "has_form": False,
            }
        )
    return pages


def _extract_hwpx_pages(path: Path) -> list[dict[str, Any]]:
    """Parse standard Korean HWPX (ZIP + OWPML XML) natively."""
    pages: list[dict[str, Any]] = []
    with zipfile.ZipFile(str(path), "r") as z:
        sec_files = sorted(n for n in z.namelist() if re.match(r"Contents/section\d+\.xml$", n, re.I))
        for idx, name in enumerate(sec_files, start=1):
            xml_bytes = z.read(name)
            root = ET.fromstring(xml_bytes)
            lines: list[str] = []
            for elem in root.iter():
                tag = elem.tag.split("}")[-1]
                if tag == "t" and elem.text:
                    lines.append(elem.text)
                elif tag == "p":
                    lines.append("\n")
            txt = clean_text("".join(lines))
            pages.append(
                {
                    "page_no": idx,
                    "text": txt,
                    "is_ocr": False,
                    "has_table": "tbl" in xml_bytes.decode("utf-8", errors="ignore"),
                    "has_form": False,
                }
            )
    if not pages:
        pages.append({"page_no": 1, "text": "", "is_ocr": False, "has_table": False, "has_form": False})
    return pages


def chunk_pages(
    pages: list[dict[str, Any]],
    max_chars: int = 620,
    overlap_chars: int = 100,
    doc_title: str = "",
    doc_category: str = "",
) -> list[dict[str, Any]]:
    """
    v4.0 Contextual Parent-Child (Small-to-Big) Legal Chunker:
    1. Groups lines into logical Parent Articles (제N조 / 별표 / 문N / 부칙) so the entire parent
       clause + provisos (다만, ...) are preserved in `parent_content`.
    2. Indexes fine-grained Child Chunks (~620 chars) with Anthropic-style `context_header`
       ([문서명 | 분류 | 편 > 장 > 조]) for razor-sharp BM25 + dense vector retrieval.
    3. Detects structured `[구조화 표]` blocks as dedicated `table` chunks.
    """
    # Pass 1: Build logical parent articles / sections first
    articles: list[dict[str, Any]] = []
    cur_part = ""
    cur_chapter = ""
    cur_article = ""
    cur_lines: list[tuple[int, str]] = []

    def _close_article() -> None:
        nonlocal cur_lines
        if not cur_lines:
            return
        body = "\n".join(t for _, t in cur_lines).strip()
        if len(body) >= 15:
            p_start = cur_lines[0][0]
            p_end = cur_lines[-1][0]
            sec_path = " > ".join(x for x in (cur_part, cur_chapter) if x)
            heading = cur_article or cur_chapter or cur_part
            art_id_m = re.search(r"(제\s*\d+\s*조(?:\s*의\s*\d+)?|별표\s*\d*|부칙|문\s*\d+)", heading or "")
            p_key = re.sub(r"\s+", "", art_id_m.group(1)) if art_id_m else f"p{p_start}_{len(articles)}"
            articles.append(
                {
                    "page_start": p_start,
                    "page_end": p_end,
                    "heading": heading,
                    "section_path": sec_path,
                    "parent_key": p_key,
                    "lines": list(cur_lines),
                    "full_text": body,
                }
            )
        cur_lines = []

    for p in pages:
        pno = int(p["page_no"])
        text = p.get("text") or ""
        if not text.strip():
            continue
        for ln in text.splitlines():
            s = ln.strip()
            if not s:
                continue
            is_boundary = False
            if _PART_RE.match(s) and len(s) <= 45:
                if cur_lines:
                    _close_article()
                cur_part = s
                cur_chapter = ""
                cur_article = ""
                is_boundary = True
            elif _CHAPTER_RE.match(s) and len(s) <= 55:
                if cur_lines:
                    _close_article()
                cur_chapter = s
                cur_article = ""
                is_boundary = True
            elif _ARTICLE_RE.match(s) and len(s) <= 85:
                if cur_lines:
                    _close_article()
                cur_article = s
                is_boundary = True

            cur_lines.append((pno, s))
            # Prevent runaway mega-sections without explicit article headings from exceeding 2400 chars
            if not is_boundary and sum(len(x) + 1 for _, x in cur_lines) >= 2400:
                _close_article()

    _close_article()

    # Pass 2: Emit fine-grained contextual child chunks pointing to their complete parent article
    chunks: list[dict[str, Any]] = []
    for art in articles:
        full_parent = art["full_text"][:2400]
        hdr_parts = [x for x in (doc_title, doc_category, art["section_path"], art["heading"]) if x]
        ctx_header = f"[{' | '.join(hdr_parts)}]" if hdr_parts else ""

        buf: list[tuple[int, str]] = []
        buf_len = 0

        def _flush_child() -> None:
            nonlocal buf, buf_len
            body = "\n".join(t for _, t in buf).strip()
            if len(body) >= 15:
                ctype = "table" if ("| ---" in body or "[구조화 표]" in body) else (
                    "proviso" if ("다만," in body or "예외" in body) else "clause"
                )
                chunks.append(
                    {
                        "page_start": buf[0][0],
                        "page_end": buf[-1][0],
                        "heading": art["heading"],
                        "section_path": art["section_path"],
                        "content": body,
                        "parent_key": art["parent_key"],
                        "context_header": ctx_header,
                        "parent_content": full_parent,
                        "chunk_type": ctype,
                    }
                )
            buf = []
            buf_len = 0

        for pno, s in art["lines"]:
            # Start clean sub-chunk on table marker or numbered clause item if buffer already substantial
            is_item_start = bool(re.match(r"^([①-⑮]|\d+\.\s|\[구조화 표\])", s))
            if is_item_start and buf_len >= int(max_chars * 0.65):
                _flush_child()
            buf.append((pno, s))
            buf_len += len(s) + 1
            if buf_len >= max_chars:
                tail = buf[-2:] if len(buf) > 2 else []
                _flush_child()
                if tail and sum(len(x) for _, x in tail) <= overlap_chars + 100:
                    buf = list(tail)
                    buf_len = sum(len(x) + 1 for _, x in buf)

        _flush_child()

    return chunks


def ingest_file(
    db: Database,
    notebook_id: str,
    source_path: Path,
    title: str | None = None,
    category: str | None = None,
    priority: int = 50,
    progress_cb: Callable[[int, int, str], None] | None = None,
    ocr_dpi: int = 260,
) -> list[dict[str, Any]]:
    """Ingest a file (or archive of files) into a notebook, run OCR if needed, chunk, index, and catalog forms."""
    source_path = Path(source_path)
    ext = source_path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"지원하지 않는 파일 형식입니다: {ext}")

    if not db.get_notebook(notebook_id):
        raise ValueError(f"노트북을 찾을 수 없습니다: {notebook_id}")

    # Handle ZIP archives by unpacking supported inner documents
    if ext == ".zip":
        results: list[dict[str, Any]] = []
        extract_dir = get_docs_dir(notebook_id) / f"_unzip_{source_path.stem}"
        extract_dir.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(str(source_path), "r") as z:
                inner_entries = [info for info in z.infolist() if not info.is_dir()]
                has_primary_docs = any(
                    Path(info.filename).suffix.lower() in {".pdf", ".docx", ".xlsx", ".hwpx"}
                    for info in inner_entries
                )
                for info in inner_entries:
                    inner_name = Path(info.filename).name
                    if has_primary_docs and inner_name.lower() == "skill.md":
                        continue
                    inner_ext = Path(inner_name).suffix.lower()
                    if inner_ext in (SUPPORTED_EXTENSIONS - {".zip"}):
                        target = extract_dir / inner_name
                        target.write_bytes(z.read(info))
                        res = ingest_file(
                            db=db,
                            notebook_id=notebook_id,
                            source_path=target,
                            title=title or Path(inner_name).stem,
                            category=category,
                            priority=priority,
                            progress_cb=progress_cb,
                            ocr_dpi=ocr_dpi,
                        )
                        results.extend(res)
            return results
        finally:
            shutil.rmtree(extract_dir, ignore_errors=True)

    fhash = _file_hash(source_path)
    doc_id = _doc_id_for(notebook_id, source_path.name, fhash)
    docs_dir = get_docs_dir(notebook_id)
    safe_name = re.sub(r'[\\/:*?"<>|]+', "_", source_path.name)
    stored_path = docs_dir / f"{doc_id}_{safe_name}"
    if source_path.resolve() != stored_path.resolve():
        shutil.copy2(str(source_path), str(stored_path))

    display_title = title or source_path.stem
    doc_category = category or "일반 자료"

    # Insert initial processing state
    db.upsert_document(
        {
            "id": doc_id,
            "notebook_id": notebook_id,
            "title": display_title,
            "original_filename": source_path.name,
            "stored_path": str(stored_path),
            "file_type": ext.lstrip("."),
            "category": doc_category,
            "priority": priority,
            "status": "indexing",
        }
    )

    try:
        ocr_pages = 0
        if ext == ".pdf":
            pages, ocr_pages = _extract_pdf_pages(stored_path, progress_cb=progress_cb, ocr_dpi=ocr_dpi)
            forms = detect_forms_for_pdf(doc_id, display_title, stored_path, pages)
        elif ext in {".txt", ".md"}:
            pages = _extract_txt_pages(stored_path)
            forms = detect_forms_for_non_pdf(doc_id, display_title, pages)
        elif ext == ".docx":
            pages = _extract_docx_pages(stored_path)
            forms = detect_forms_for_non_pdf(doc_id, display_title, pages)
        elif ext == ".xlsx":
            pages = _extract_xlsx_pages(stored_path)
            forms = detect_forms_for_non_pdf(doc_id, display_title, pages)
        elif ext == ".hwpx":
            pages = _extract_hwpx_pages(stored_path)
            forms = detect_forms_for_non_pdf(doc_id, display_title, pages)
        else:
            pages, forms = [], []

        form_page_set = {f["page_start"] for f in forms}
        for p in pages:
            if p["page_no"] in form_page_set:
                p["has_form"] = True

        chunks = chunk_pages(pages, doc_title=display_title, doc_category=doc_category)
        total_chars = sum(len(p["text"]) for p in pages)

        db.replace_document_content(doc_id, notebook_id, pages, chunks)
        db.replace_document_forms(doc_id, notebook_id, forms)
        doc_record = {
            "id": doc_id,
            "notebook_id": notebook_id,
            "title": display_title,
            "original_filename": source_path.name,
            "stored_path": str(stored_path),
            "file_type": ext.lstrip("."),
            "category": doc_category,
            "priority": priority,
            "page_count": len(pages),
            "ocr_pages": ocr_pages,
            "total_chars": total_chars,
            "status": "ready",
            "error_msg": "",
        }
        db.upsert_document(doc_record)
        doc_record["chunk_count"] = len(chunks)
        doc_record["form_count"] = len(forms)
        return [doc_record]
    except Exception as exc:
        db.upsert_document(
            {
                "id": doc_id,
                "notebook_id": notebook_id,
                "title": display_title,
                "original_filename": source_path.name,
                "stored_path": str(stored_path),
                "file_type": ext.lstrip("."),
                "category": doc_category,
                "priority": priority,
                "status": "error",
                "error_msg": str(exc),
            }
        )
        raise


def replace_document_file(
    db: Database,
    doc_id: str,
    source_path: Path,
    title: str | None = None,
    category: str | None = None,
    priority: int | None = None,
    progress_cb: Callable[[int, int, str], None] | None = None,
    ocr_dpi: int = 260,
) -> dict[str, Any]:
    """Update an existing document in-place (preserving doc_id) with a revised file and re-index/re-OCR."""
    existing = db.get_document(doc_id)
    if not existing:
        raise ValueError(f"문서를 찾을 수 없습니다: {doc_id}")

    notebook_id = existing["notebook_id"]
    source_path = Path(source_path)
    ext = source_path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"지원하지 않는 파일 형식입니다: {ext}")

    # If a ZIP archive is provided for replacement, pick the primary document inside (skipping SKILL.md)
    actual_source = source_path
    extract_dir: Path | None = None
    if ext == ".zip":
        extract_dir = get_docs_dir(notebook_id) / f"_unzip_update_{doc_id}"
        extract_dir.mkdir(parents=True, exist_ok=True)
        chosen: Path | None = None
        with zipfile.ZipFile(str(source_path), "r") as z:
            inner = [info for info in z.infolist() if not info.is_dir()]
            for info in inner:
                name = Path(info.filename).name
                if name.lower() == "skill.md":
                    continue
                if Path(name).suffix.lower() in (SUPPORTED_EXTENSIONS - {".zip"}):
                    target = extract_dir / name
                    target.write_bytes(z.read(info))
                    chosen = target
                    break
        if not chosen:
            shutil.rmtree(extract_dir, ignore_errors=True)
            raise ValueError("압축 파일 안에서 지원되는 문서(PDF/DOCX/HWPX/TXT/XLSX)를 찾을 수 없습니다.")
        actual_source = chosen
        ext = actual_source.suffix.lower()

    docs_dir = get_docs_dir(notebook_id)
    safe_name = re.sub(r'[\\/:*?"<>|]+', "_", actual_source.name)
    fhash = _file_hash(actual_source)
    new_stored_path = docs_dir / f"{doc_id}_{fhash[:6]}_{safe_name}"
    if actual_source.resolve() != new_stored_path.resolve():
        shutil.copy2(str(actual_source), str(new_stored_path))
    if extract_dir is not None:
        shutil.rmtree(extract_dir, ignore_errors=True)

    display_title = (title or "").strip() or existing["title"]
    doc_category = (category or "").strip() or existing["category"]
    doc_priority = priority if priority is not None else int(existing["priority"])
    old_stored_path = Path(existing["stored_path"])

    ocr_pages = 0
    if ext == ".pdf":
        pages, ocr_pages = _extract_pdf_pages(new_stored_path, progress_cb=progress_cb, ocr_dpi=ocr_dpi)
        forms = detect_forms_for_pdf(doc_id, display_title, new_stored_path, pages)
    elif ext in {".txt", ".md"}:
        pages = _extract_txt_pages(new_stored_path)
        forms = detect_forms_for_non_pdf(doc_id, display_title, pages)
    elif ext == ".docx":
        pages = _extract_docx_pages(new_stored_path)
        forms = detect_forms_for_non_pdf(doc_id, display_title, pages)
    elif ext == ".xlsx":
        pages = _extract_xlsx_pages(new_stored_path)
        forms = detect_forms_for_non_pdf(doc_id, display_title, pages)
    elif ext == ".hwpx":
        pages = _extract_hwpx_pages(new_stored_path)
        forms = detect_forms_for_non_pdf(doc_id, display_title, pages)
    else:
        pages, forms = [], []

    form_page_set = {f["page_start"] for f in forms}
    for p in pages:
        if p["page_no"] in form_page_set:
            p["has_form"] = True

    chunks = chunk_pages(pages, doc_title=display_title, doc_category=doc_category)
    total_chars = sum(len(p["text"]) for p in pages)

    db.replace_document_content(doc_id, notebook_id, pages, chunks)
    db.replace_document_forms(doc_id, notebook_id, forms)

    updated_record = {
        "id": doc_id,
        "notebook_id": notebook_id,
        "title": display_title,
        "original_filename": actual_source.name,
        "stored_path": str(new_stored_path),
        "file_type": ext.lstrip("."),
        "category": doc_category,
        "priority": doc_priority,
        "page_count": len(pages),
        "ocr_pages": ocr_pages,
        "total_chars": total_chars,
        "status": "ready",
        "error_msg": "",
        "created_at": existing["created_at"],
    }
    db.upsert_document(updated_record)
    updated_record["chunk_count"] = len(chunks)
    updated_record["form_count"] = len(forms)

    # Remove previous file cleanly if path changed
    if old_stored_path.exists() and old_stored_path.resolve() != new_stored_path.resolve():
        try:
            old_stored_path.unlink(missing_ok=True)
        except OSError:
            pass
    return updated_record


def seed_default_church_notebook(
    db: Database,
    archive_dir: Path | None = None,
    progress_cb: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    """Idempotently ingest the 4 church zip archives into the default notebook."""
    db.ensure_default_notebook()
    existing_titles = {d["title"] for d in db.list_documents(DEFAULT_NOTEBOOK_ID) if d["status"] == "ready"}
    src_dir = archive_dir or get_base_dir()
    ingested: list[dict[str, Any]] = []

    for item in SEED_ARCHIVES:
        if item["title"] in existing_titles:
            if progress_cb:
                progress_cb(f"[건너뜀] 이미 색인됨: {item['title']}")
            continue
        zip_path = src_dir / item["zip_name"]
        if not zip_path.exists():
            if progress_cb:
                progress_cb(f"[경고] 파일 없음: {zip_path}")
            continue
        if progress_cb:
            progress_cb(f"[색인 시작] {item['title']} ({item['zip_name']})")

        def _ocr_cb(done: int, total: int, msg: str) -> None:
            if progress_cb and (done == total or done % 25 == 0 or done == 1):
                progress_cb(f"  -> {item['title']}: {msg}")

        docs = ingest_file(
            db=db,
            notebook_id=DEFAULT_NOTEBOOK_ID,
            source_path=zip_path,
            title=item["title"],
            category=item["category"],
            priority=item["priority"],
            progress_cb=_ocr_cb,
        )
        ingested.extend(docs)
        if progress_cb:
            for d in docs:
                progress_cb(
                    f"[완료] {d['title']}: {d['page_count']}쪽, "
                    f"청크 {d['chunk_count']}개, 서식/표 {d['form_count']}개, OCR {d['ocr_pages']}쪽"
                )
    return ingested


def reindex_notebook_v4(
    db: Database,
    notebook_id: str = DEFAULT_NOTEBOOK_ID,
    progress_cb: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    """
    Upgrade all ready documents in a notebook to v4.0 index in-place:
    - Preserves doc_id, pins, tags, forms_catalog, chat sessions/messages, groups, and std_boards 100%.
    - Re-extracts structured Markdown tables via PyMuPDF find_tables() for native PDF pages while
      reusing existing OCR text for scanned pages (fast <5s upgrade!).
    - Rebuilds Contextual Parent-Child chunks, Kiwi Korean morpheme FTS5 tokens, and Legal Cross-Reference Graph.
    """
    docs = [d for d in db.list_documents(notebook_id) if d["status"] == "ready"]
    total = len(docs)
    total_chunks = 0
    total_refs = 0
    upgraded_tables = 0

    for idx, d in enumerate(docs, start=1):
        doc_id = d["id"]
        title = d["title"]
        category = d.get("category") or "일반 자료"
        stored = Path(d["stored_path"]) if d.get("stored_path") else None

        if progress_cb:
            progress_cb(int((idx - 1) / max(1, total) * 85), f"v4.0 정밀 재색인 중 ({idx}/{total}): {title}")

        existing_pages = db.get_document_pages(doc_id)
        if not existing_pages:
            continue
        for p in existing_pages:
            p["text"] = clean_text(str(p.get("text") or ""))

        # Enhance native text PDF pages with structured Markdown table extraction (without re-running OCR)
        if d.get("file_type") == "pdf" and stored and stored.exists():
            try:
                pdf = pymupdf.open(str(stored))
                try:
                    for p in existing_pages:
                        if p.get("is_ocr"):
                            continue
                        pno = int(p["page_no"])
                        if pno < 1 or pno > len(pdf):
                            continue
                        txt = str(p.get("text") or "")
                        if "[구조화 표]" in txt:
                            continue
                        page_obj = pdf[pno - 1]
                        if len(page_obj.get_drawings()) >= 8:
                            md_tables = _extract_markdown_tables(page_obj)
                            if md_tables:
                                tbl_block = "\n\n[구조화 표]\n" + "\n\n".join(md_tables)
                                if len(tbl_block) <= 4500:
                                    p["text"] = txt + tbl_block
                                    p["has_table"] = 1
                                    upgraded_tables += len(md_tables)
                finally:
                    pdf.close()
            except Exception:
                pass

        chunks = chunk_pages(existing_pages, doc_title=title, doc_category=category)
        db.replace_document_content(doc_id, notebook_id, existing_pages, chunks)
        total_chunks += len(chunks)

    with db.connect() as conn:
        total_refs = int(
            conn.execute("SELECT COUNT(*) FROM chunk_refs WHERE notebook_id = ?", (notebook_id,)).fetchone()[0]
        )

    # If local ONNX neural pack is installed, refresh missing vectors automatically
    embedded = 0
    try:
        from core.neural_engine import neural_engine

        if neural_engine.is_embed_installed():
            embedded = neural_engine.index_notebook_embeddings(db, notebook_id, progress_cb=progress_cb)
        neural_engine.invalidate_cache(notebook_id)
    except Exception:
        pass

    if progress_cb:
        progress_cb(
            100,
            f"v4.0 재색인 완료 — 문서 {total}권 · 계층 청크 {total_chunks}개 · 교차참조 {total_refs}건 · 구조화 표 {upgraded_tables}개",
        )

    return {
        "ok": True,
        "documents": total,
        "chunks": total_chunks,
        "cross_refs": total_refs,
        "tables_extracted": upgraded_tables,
        "embedded_chunks": embedded,
    }
