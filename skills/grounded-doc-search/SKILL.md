---
name: grounded-doc-search
description: >-
  NotebookLM-style grounded document search, scanned Korean PDF OCR indexing,
  table/form extraction (PDF/DOCX/XLSX), and AI form auto-fill over user-provided
  PDF, ZIP, TXT, MD, DOCX, HWPX, and XLSX sources. Use when answering questions
  strictly from specific local documents (such as church constitutions, bylaws,
  manuals, regulations, or custom PDF/text folders) with zero hallucination,
  or when creating a dedicated domain search notebook and extracting/filling forms.
---

# Grounded Document Search & Form Engine (`grounded-doc-search`)

Use this skill whenever the user wants NotebookLM-style, strictly grounded Q&A, clause lookup, or form/table extraction over specific local documents — including **목포사랑의교회 4대 법규·행정 문서(총회헌법·헌법해설서·정관·시행세칙)** OR any newly provided PDF/ZIP/TXT/DOCX/HWPX/XLSX collection.

## Core Grounding Rules (Mandatory)

Read [references/grounding_rules.md](./references/grounding_rules.md) when handling legal/bylaw hierarchy conflicts or formatting edge cases. Always enforce:

1. **Zero Hallucination Gate**: NEVER answer from general memory if the indexed corpus returns `has_evidence: false` or lacks relevant evidence. Reply clearly: *"제공된 자료에서 해당 정보를 찾을 수 없습니다."*
2. **Practical Synthesis + Verifiable Citation**: When evidence exists, synthesize clearly and practically for the user's real-world question (connecting higher-level rules with detailed manuals/commentary), and ALWAYS list exact sources (`[문서명] 장·조/항목, p.쪽수`).
3. **Clean Korean Readability**: Force a line break before numbered items (`1.`, `2.`) and sub-clauses (`①`, `②`). Never output raw system tags like `[source]` or `<cite>`.
4. **Forms & Tables**: When the user asks for a form, application, table, or filled document, extract the lossless original PDF page slice AND/OR generate an editable DOCX/XLSX file using the CLI script below. Never invent missing personal data during auto-fill; keep unknown fields blank.

## CLI Workflow

Use the bundled engine script [scripts/doc_skill_cli.py](./scripts/doc_skill_cli.py) with the project's Python interpreter (`c:\Users\L\Desktop\교회검색기\.venv\Scripts\python.exe`, or `python`):

### 1. Search an existing notebook (default: `mokpo-sarang-church`)
```bash
python scripts/doc_skill_cli.py search "장로 후보자 추천 나이와 당회 사정 절차" --notebook mokpo-sarang-church --top-k 8
```
- Inspect the JSON output: check `has_evidence`, `chunks`, and `forms`.
- If `has_evidence` is `false`, report immediately that no supporting information exists in the provided documents.
- If `has_evidence` is `true`, synthesize the grounded answer using ONLY the returned `chunks`, cite document title + heading + page numbers, and offer any matched `forms`.

### 2. Ingest new PDF / ZIP / TXT / MD / DOCX / HWPX / XLSX materials into a new dedicated notebook
```bash
python scripts/doc_skill_cli.py init-notebook "당회 회의록 검색기" --id danghoe-minutes --desc "당회 회의록 전용 검색"
python scripts/doc_skill_cli.py ingest "C:\path\to\files_or_folder" --notebook danghoe-minutes
```
- Scanned image PDFs (zero text layer) are automatically processed via offline Windows Korean WinRT OCR.

### 3. List, extract, or auto-fill forms and tables
```bash
# List cataloged forms/tables
python scripts/doc_skill_cli.py list-forms --notebook mokpo-sarang-church --query "신청서"

# Extract original PDF slice, editable DOCX, or Excel XLSX
python scripts/doc_skill_cli.py extract-form <form_id> --format pdf --out ./output.pdf
python scripts/doc_skill_cli.py extract-form <form_id> --format docx --out ./output.docx
python scripts/doc_skill_cli.py extract-form <form_id> --format xlsx --out ./output.xlsx

# Auto-fill a form DOCX from structured JSON fields (missing fields stay blank)
python scripts/doc_skill_cli.py autofill-form <form_id> --fields-json '{"성명":"홍길동","연락처":"010-1234-5678"}' --out ./filled.docx
```

## Verification Checklist
- Confirm `has_evidence` before composing any factual claim.
- Confirm every cited article/page matches the JSON output from `doc_skill_cli.py search`.
- Confirm extracted PDF/DOCX/XLSX files exist and are non-empty before giving their paths to the user.
