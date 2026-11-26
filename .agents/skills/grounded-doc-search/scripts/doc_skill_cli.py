#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

os.environ.setdefault("PYTHONUTF8", "1")

# Locate project root (works both inside repo and when installed to ~/.claude/skills or ~/.gemini/config/skills)
_THIS_FILE = Path(__file__).resolve()
_CANDIDATES = [
    _THIS_FILE.parent.parent.parent.parent,
    Path(os.environ.get("CHURCH_SEARCH_HOME", "")),
    Path(r"c:\Users\L\Desktop\교회검색기"),
]
_ENGINE_ROOT: Path | None = None
for _c in _CANDIDATES:
    if _c and (_c / "core" / "database.py").exists():
        _ENGINE_ROOT = _c
        break

if _ENGINE_ROOT is None:
    print(json.dumps({"error": "Cannot locate grounded-doc-search core engine. Set CHURCH_SEARCH_HOME."}, ensure_ascii=False))
    sys.exit(1)

if str(_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_ENGINE_ROOT))

# Default data dir to engine root/data unless explicitly overridden
if "CHURCH_SEARCH_DATA_DIR" not in os.environ:
    os.environ["CHURCH_SEARCH_DATA_DIR"] = str(_ENGINE_ROOT / "data")

from core.config import DEFAULT_NOTEBOOK_ID
from core.database import Database
from core.forms import export_editable_docx, export_original_pdf, export_table_xlsx
from core.ingest import SUPPORTED_EXTENSIONS, ingest_file
from core.retriever import retrieve


def cmd_list_notebooks(args: argparse.Namespace) -> None:
    db = Database()
    db.ensure_default_notebook()
    print(json.dumps(db.list_notebooks(), ensure_ascii=False, indent=2))


def cmd_init_notebook(args: argparse.Namespace) -> None:
    db = Database()
    nb_id = args.id or f"nb-{uuid.uuid4().hex[:8]}"
    existing = db.get_notebook(nb_id)
    if existing:
        print(json.dumps({"status": "exists", "notebook": existing}, ensure_ascii=False, indent=2))
        return
    nb = db.create_notebook(
        notebook_id=nb_id,
        name=args.name,
        description=args.desc or "",
        system_rules=args.rules or "",
    )
    print(json.dumps({"status": "created", "notebook": nb}, ensure_ascii=False, indent=2))


def cmd_ingest(args: argparse.Namespace) -> None:
    db = Database()
    db.ensure_default_notebook()
    if not db.get_notebook(args.notebook):
        db.create_notebook(args.notebook, args.notebook)

    target = Path(args.path)
    if not target.exists():
        print(json.dumps({"error": f"Path not found: {target}"}, ensure_ascii=False))
        sys.exit(1)

    files: list[Path] = []
    if target.is_dir():
        for p in sorted(target.rglob("*")):
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS:
                files.append(p)
    else:
        files.append(target)

    ingested = []
    for f in files:
        res = ingest_file(
            db=db,
            notebook_id=args.notebook,
            source_path=f,
            category=args.category,
            priority=args.priority,
            progress_cb=lambda d, t, m: print(f"[progress] {f.name}: {m}", file=sys.stderr, flush=True)
            if d == t or d % 30 == 0
            else None,
        )
        ingested.extend(res)
    print(json.dumps({"ingested_count": len(ingested), "documents": ingested}, ensure_ascii=False, indent=2))


def cmd_search(args: argparse.Namespace) -> None:
    db = Database()
    db.ensure_default_notebook()
    doc_ids = [x.strip() for x in args.doc_ids.split(",") if x.strip()] if args.doc_ids else None
    res = retrieve(db, args.notebook, args.query, doc_ids=doc_ids, top_k=args.top_k)
    payload = {
        "has_evidence": res.has_evidence,
        "confidence": res.confidence,
        "query_keywords": res.query_keywords,
        "clause_refs": res.clause_refs,
        "searched_docs": res.searched_doc_titles,
        "chunks": [
            {
                "doc_title": c["doc_title"],
                "doc_category": c["doc_category"],
                "heading": c["heading"],
                "section_path": c["section_path"],
                "page_start": c["page_start"],
                "page_end": c["page_end"],
                "score": c["score"],
                "content": c["content"],
            }
            for c in res.chunks
        ],
        "forms": [
            {
                "id": f["id"],
                "title": f["title"],
                "category": f["category"],
                "doc_title": f["doc_title"],
                "page_start": f["page_start"],
                "fields": f["fields"],
            }
            for f in res.forms
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_list_forms(args: argparse.Namespace) -> None:
    db = Database()
    forms = db.list_forms(args.notebook, query=args.query or "")
    out = [
        {
            "id": f["id"],
            "title": f["title"],
            "category": f["category"],
            "form_type": f["form_type"],
            "doc_title": f["doc_title"],
            "page_start": f["page_start"],
            "fields": f["fields"],
        }
        for f in forms
    ]
    print(json.dumps(out, ensure_ascii=False, indent=2))


def cmd_extract_form(args: argparse.Namespace) -> None:
    db = Database()
    form = db.get_form(args.form_id)
    if not form:
        print(json.dumps({"error": f"Form not found: {args.form_id}"}, ensure_ascii=False))
        sys.exit(1)
    out_path = Path(args.out).resolve() if args.out else None
    fmt = args.format.lower()
    if fmt == "pdf":
        p = export_original_pdf(form, out_path=out_path)
    elif fmt == "docx":
        p = export_editable_docx(form, out_path=out_path)
    elif fmt == "xlsx":
        p = export_table_xlsx(form, out_path=out_path)
    else:
        print(json.dumps({"error": "Supported formats: pdf, docx, xlsx"}, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps({"ok": True, "format": fmt, "path": str(p), "size_bytes": p.stat().st_size}, ensure_ascii=False, indent=2))


def cmd_autofill_form(args: argparse.Namespace) -> None:
    db = Database()
    form = db.get_form(args.form_id)
    if not form:
        print(json.dumps({"error": f"Form not found: {args.form_id}"}, ensure_ascii=False))
        sys.exit(1)
    raw = json.loads(args.fields_json)
    if isinstance(raw, dict) and "fields" in raw and isinstance(raw["fields"], list):
        structured = raw
    elif isinstance(raw, dict):
        known = list(form.get("fields", []))
        for k in raw.keys():
            if k not in known:
                known.append(k)
        structured = {
            "document_title": form["title"],
            "fields": [{"label": k, "value": str(raw.get(k, ""))} for k in known],
            "body_paragraphs": [],
            "date_line": str(raw.get("날짜") or raw.get("신청일") or "20    년      월      일"),
            "signer_line": f"신청인: {raw.get('성명') or raw.get('이름') or '            '} (인)",
            "recipient_line": str(raw.get("수신") or "목포사랑의교회 귀중"),
        }
    else:
        raise ValueError("--fields-json must be a JSON object")

    out_path = Path(args.out).resolve() if args.out else None
    p = export_editable_docx(form, filled_data=structured, out_path=out_path)
    print(json.dumps({"ok": True, "path": str(p), "size_bytes": p.stat().st_size}, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Grounded Document Search & Form Extraction Skill CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list-notebooks").set_defaults(func=cmd_list_notebooks)

    p_init = sub.add_parser("init-notebook")
    p_init.add_argument("name")
    p_init.add_argument("--id", default="")
    p_init.add_argument("--desc", default="")
    p_init.add_argument("--rules", default="")
    p_init.set_defaults(func=cmd_init_notebook)

    p_ing = sub.add_parser("ingest")
    p_ing.add_argument("path")
    p_ing.add_argument("--notebook", default=DEFAULT_NOTEBOOK_ID)
    p_ing.add_argument("--category", default="일반 자료")
    p_ing.add_argument("--priority", type=int, default=50)
    p_ing.set_defaults(func=cmd_ingest)

    p_s = sub.add_parser("search")
    p_s.add_argument("query")
    p_s.add_argument("--notebook", default=DEFAULT_NOTEBOOK_ID)
    p_s.add_argument("--doc-ids", default="")
    p_s.add_argument("--top-k", type=int, default=8)
    p_s.set_defaults(func=cmd_search)

    p_lf = sub.add_parser("list-forms")
    p_lf.add_argument("--notebook", default=DEFAULT_NOTEBOOK_ID)
    p_lf.add_argument("--query", default="")
    p_lf.set_defaults(func=cmd_list_forms)

    p_ef = sub.add_parser("extract-form")
    p_ef.add_argument("form_id")
    p_ef.add_argument("--format", default="pdf", choices=["pdf", "docx", "xlsx"])
    p_ef.add_argument("--out", default="")
    p_ef.set_defaults(func=cmd_extract_form)

    p_af = sub.add_parser("autofill-form")
    p_af.add_argument("form_id")
    p_af.add_argument("--fields-json", required=True)
    p_af.add_argument("--out", default="")
    p_af.set_defaults(func=cmd_autofill_form)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
