from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from core.database import Database
from core.ingest import (
    SUPPORTED_EXTENSIONS,
    _extract_docx_pages,
    _extract_hwpx_pages,
    _extract_pdf_pages,
    _extract_txt_pages,
    _extract_xlsx_pages,
    clean_text,
)
from core.ocr_winrt import ocr_image_bytes, ocr_image_file
from core.std_config import DEFAULT_STD_CATEGORIES, load_std_config
from core.std_store import StandardizationStore, get_std_uploads_dir
from server.cli_providers import load_ai_config, stream_cli_with_failover

IMAGE_EXTENSIONS: set[str] = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
STD_ALLOWED_EXTENSIONS: set[str] = (SUPPORTED_EXTENSIONS - {".zip"}) | IMAGE_EXTENSIONS | {".pptx"}
MAX_STD_FILE_BYTES: int = 30 * 1024 * 1024  # 30 MB per uploaded file

# Canonical church administrative taxonomy (Mokpo Sarang Church 2025 Bylaws Art. 53)
CHURCH_ADMIN_TAXONOMY: list[tuple[str, list[str]]] = [
    (str(c["name"]), list(c["keywords"])) for c in DEFAULT_STD_CATEGORIES
]


def _get_active_taxonomy(db: Database | None) -> list[tuple[str, list[str]]]:
    cfg = load_std_config(db)
    return [(str(c["name"]), list(c.get("keywords") or [])) for c in cfg.get("categories") or []] or CHURCH_ADMIN_TAXONOMY


def _extract_image_submission(path: Path) -> tuple[str, dict[str, Any]]:
    meta: dict[str, Any] = {"is_image": True, "ocr_applied": False, "width": 0, "height": 0, "format": path.suffix.lstrip(".").upper()}
    try:
        from PIL import Image, ImageOps

        with Image.open(str(path)) as im:
            im = ImageOps.exif_transpose(im)
            meta["width"], meta["height"] = im.size
            if im.format:
                meta["format"] = str(im.format).upper()
    except Exception:
        pass

    ocr_text = clean_text(ocr_image_file(path))
    meta["ocr_applied"] = True
    meta["ocr_chars"] = len(ocr_text)
    header = f"[이미지 첨부: {path.name} ({meta['width']}x{meta['height']}px)]"
    if ocr_text:
        return f"{header}\n{ocr_text}", meta
    return header, meta


def _iter_pptx_shapes_text(shapes: Any, lines_out: list[str], tables_out: list[str], image_blobs: list[tuple[bytes, str]]) -> None:
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    for shape in shapes:
        stype = getattr(shape, "shape_type", None)
        if stype == MSO_SHAPE_TYPE.GROUP and hasattr(shape, "shapes"):
            _iter_pptx_shapes_text(shape.shapes, lines_out, tables_out, image_blobs)
            continue

        if getattr(shape, "has_text_frame", False) and shape.text_frame is not None:
            for para in shape.text_frame.paragraphs:
                txt = re.sub(r"\s+", " ", para.text or "").strip()
                if txt:
                    indent = "  " * min(3, int(getattr(para, "level", 0) or 0))
                    lines_out.append(f"{indent}{txt}")

        if getattr(shape, "has_table", False) and shape.table is not None:
            rows_data: list[list[str]] = []
            for row in shape.table.rows:
                cells = [re.sub(r"\s+", " ", (c.text or "")).strip().replace("|", "/") for c in row.cells]
                if any(cells):
                    rows_data.append(cells)
            if rows_data:
                max_cols = max(len(r) for r in rows_data)
                norm = [r + [""] * (max_cols - len(r)) for r in rows_data]
                md_lines = [
                    "| " + " | ".join(norm[0]) + " |",
                    "| " + " | ".join("---" for _ in range(max_cols)) + " |",
                ]
                for r in norm[1:50]:
                    md_lines.append("| " + " | ".join(r) + " |")
                tables_out.append("\n".join(md_lines))

        if stype == MSO_SHAPE_TYPE.PICTURE and hasattr(shape, "image"):
            try:
                img = shape.image
                ext = f".{getattr(img, 'ext', 'png') or 'png'}"
                if img.blob and len(img.blob) >= 256:
                    image_blobs.append((img.blob, ext))
            except Exception:
                pass


def _extract_pptx_submission(path: Path) -> tuple[str, dict[str, Any]]:
    meta: dict[str, Any] = {"is_pptx": True, "slide_count": 0, "table_count": 0, "embedded_ocr_count": 0}
    try:
        from pptx import Presentation
    except Exception:
        return "", meta

    prs = Presentation(str(path))
    slide_blocks: list[str] = []
    total_tables = 0
    total_ocr = 0
    max_total_ocr = 10

    for idx, slide in enumerate(prs.slides, start=1):
        lines: list[str] = []
        tables: list[str] = []
        img_blobs: list[tuple[bytes, str]] = []
        _iter_pptx_shapes_text(slide.shapes, lines, tables, img_blobs)
        total_tables += len(tables)

        notes_text = ""
        try:
            if slide.has_notes_slide and slide.notes_slide and slide.notes_slide.notes_text_frame:
                notes_text = clean_text(slide.notes_slide.notes_text_frame.text or "")
        except Exception:
            notes_text = ""

        # OCR embedded slide pictures when the slide is image-heavy / scanned (< 45 chars of text)
        ocr_parts: list[str] = []
        plain_len = sum(len(x) for x in lines)
        if plain_len < 45 and img_blobs and total_ocr < max_total_ocr:
            for blob, ext in img_blobs[:2]:
                if total_ocr >= max_total_ocr:
                    break
                extracted_img = clean_text(ocr_image_bytes(blob, ext_hint=ext))
                if extracted_img:
                    ocr_parts.append(extracted_img)
                    total_ocr += 1

        block_parts: list[str] = [f"[슬라이드 {idx}]"]
        if lines:
            block_parts.append(clean_text("\n".join(lines)))
        if tables:
            block_parts.append("\n\n".join(tables))
        if ocr_parts:
            block_parts.append("[슬라이드 이미지 글자인식]\n" + "\n".join(ocr_parts))
        if notes_text:
            block_parts.append(f"[발표자 노트]\n{notes_text}")

        if len(block_parts) > 1:
            slide_blocks.append("\n".join(block_parts))

    meta["slide_count"] = len(prs.slides)
    meta["table_count"] = total_tables
    meta["embedded_ocr_count"] = total_ocr
    return "\n\n".join(slide_blocks), meta


def extract_submission_file(path: Path) -> tuple[str, dict[str, Any]]:
    ext = path.suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return _extract_image_submission(path)
    if ext == ".pptx":
        return _extract_pptx_submission(path)

    meta: dict[str, Any] = {}
    if ext == ".pdf":
        pages, ocr_cnt = _extract_pdf_pages(path, ocr_dpi=200)
        meta = {"page_count": len(pages), "ocr_pages": ocr_cnt}
    elif ext in {".txt", ".md"}:
        pages = _extract_txt_pages(path)
        meta = {"page_count": len(pages)}
    elif ext == ".docx":
        pages = _extract_docx_pages(path)
        meta = {"page_count": len(pages)}
    elif ext == ".xlsx":
        pages = _extract_xlsx_pages(path)
        meta = {"sheet_count": len(pages)}
    elif ext == ".hwpx":
        pages = _extract_hwpx_pages(path)
        meta = {"page_count": len(pages)}
    else:
        return "", meta
    text = "\n\n".join(f"[p.{p['page_no']}]\n{p['text']}" for p in pages if p.get("text", "").strip())
    return text, meta


def extract_submission_file_text(path: Path) -> str:
    text, _ = extract_submission_file(path)
    return text


def _heuristic_analyze(
    board: dict[str, Any],
    all_boards: list[dict[str, Any]],
    title: str,
    notes: str,
    extracted_text: str,
    taxonomy: list[tuple[str, list[str]]] | None = None,
) -> dict[str, Any]:
    """Fast 100% offline-resilient analyzer detecting tags, cluster key, and cross-board routing."""
    combined = f"{title}\n{notes}\n{extracted_text[:6000]}"
    compact = re.sub(r"\s+", "", combined).lower()
    active_tax = taxonomy or CHURCH_ADMIN_TAXONOMY

    # Score against taxonomy
    cat_scores: list[tuple[str, int, list[str]]] = []
    for cat_name, kws in active_tax:
        hits = [kw for kw in kws if kw in compact]
        if hits:
            score = sum(min(4, compact.count(kw)) * 10 for kw in hits)
            cat_scores.append((cat_name, score, hits))
    cat_scores.sort(key=lambda x: x[1], reverse=True)

    top_tags: list[str] = []
    for _, _, hits in cat_scores[:3]:
        for h in hits:
            if h not in top_tags and len(top_tags) < 6:
                top_tags.append(h)

    # Detect cluster key (form/regulation type)
    cluster_patterns = [
        (r"(휴가|휴직|복직).{0,6}(청원|신청)", "휴가·휴직 청원 규격"),
        (r"(지출|예산|청구|결의서|영수증)", "재정 지출·결의 규격"),
        (r"(심방|셀보고|셀사역|교구)", "셀·교구 사역보고 규격"),
        (r"(차량|운행|대관|시설)", "차량·시설 이용 규격"),
        (r"(학습|세례|입교|유아세례)", "학습·세례 신청 규격"),
        (r"(교사|교육|수련회|부서보고)", "교육부서 운영·보고 규격"),
        (r"(장례|결혼|예배|의전)", "예배·의전 진행 규격"),
        (r"(선교|구제|장학|후원)", "선교·구제 지원 규격"),
    ]
    cluster_key = ""
    for pat, label in cluster_patterns:
        if re.search(pat, compact):
            cluster_key = label
            break
    if not cluster_key:
        clean_t = re.sub(r"\.(pdf|docx|hwpx|xlsx|pptx|txt|md|png|jpe?g|webp|bmp|gif|tiff?)$", "", title, flags=re.I).strip()
        clean_t = re.sub(r"\s*(수정본|최종|안|초안|v?\d+(\.\d+)?|\(\d+\))$", "", clean_t, flags=re.I).strip()
        cluster_key = clean_t[:28] or board["category"]

    first_lines = [ln.strip() for ln in (notes or extracted_text).splitlines() if ln.strip() and not ln.strip().startswith("[p.")]
    summary = " ".join(first_lines[:2])[:220] or f"{title} 제출 자료"

    cur_cat_compact = re.sub(r"\s+", "", f"{board['category']} {board['title']}").lower()
    suggestions: list[dict[str, Any]] = []

    if cat_scores:
        best_cat, best_score, best_hits = cat_scores[0]
        # Check secondary strong categories too (multi-domain files!)
        for idx, (cat_name, score, hits) in enumerate(cat_scores[:3]):
            if score < 20:
                continue
            cat_tokens = [t for t in re.split(r"[·/\s]+", cat_name) if len(t) >= 2]
            already_in_current = any(t in cur_cat_compact for t in cat_tokens)
            if already_in_current:
                continue

            # Find if another open board matches this category
            matched_board = None
            for ob in all_boards:
                if ob["id"] == board["id"]:
                    continue
                ob_str = re.sub(r"\s+", "", f"{ob['category']} {ob['title']} {ob['description']}").lower()
                if any(t in ob_str for t in cat_tokens) or any(h in ob_str for h in hits[:3]):
                    matched_board = ob
                    break

            is_primary_mismatch = idx == 0 and score >= 40
            conf = min(94, 58 + min(36, score // 2))
            if matched_board:
                act = "move" if is_primary_mismatch and not any(t in cur_cat_compact for t in re.split(r"[·/\s]+", best_cat) if len(t) >= 2) else "copy"
                suggestions.append(
                    {
                        "target_board_id": matched_board["id"],
                        "suggested_category": cat_name,
                        "action_type": act,
                        "confidence": conf,
                        "reason": (
                            f"핵심 키워드({', '.join(hits[:4])})가 '{matched_board['title']}' 분류와 강하게 일치합니다. "
                            + ("해당 분류로 이동하는 것이 더 적합합니다." if act == "move" else "양쪽 분류에 병행 복사(또는 병합)해 두는 것을 권장합니다.")
                        ),
                    }
                )
            else:
                suggestions.append(
                    {
                        "target_board_id": "",
                        "suggested_category": cat_name,
                        "action_type": "deferred",
                        "confidence": conf,
                        "reason": (
                            f"핵심 내용({', '.join(hits[:4])})이 향후 '{cat_name}' 분류 작업과 밀접합니다. "
                            f"새 '{cat_name}' 모집 게시글을 만들 때 이동·복사·병합할 수 있도록 기억해 두었습니다."
                        ),
                    }
                )

    return {
        "summary": summary,
        "tags": top_tags or [board["category"]],
        "cluster_key": cluster_key,
        "suggestions": suggestions[:3],
    }


async def analyze_submission_and_cross_routes(
    db: Database,
    store: StandardizationStore,
    board: dict[str, Any],
    submission: dict[str, Any],
    use_ai: bool = True,
) -> dict[str, Any]:
    """Analyze a newly uploaded submission, detect cross-board Move/Copy/Merge/Deferred memory (strictly group-isolated), and optionally auto-route."""
    board_gid = (board.get("group_id") or "").strip()
    all_boards = [b for b in store.list_boards() if (b.get("group_id") or "").strip() == board_gid]
    active_tax = _get_active_taxonomy(db)
    heur = _heuristic_analyze(
        board=board,
        all_boards=all_boards,
        title=submission["title"],
        notes=submission["notes"],
        extracted_text=submission["extracted_text"],
        taxonomy=active_tax,
    )

    result = heur
    if use_ai:
        other_boards_desc = "\n".join(
            f"- id={b['id']} | 제목={b['title']} | 분류={b['category']} | 작업형태={b['work_type']}"
            for b in all_boards
            if b["id"] != board["id"]
        ) or "(현재 다른 모집 게시글 없음)"
        tax_names = ", ".join(name for name, _ in active_tax)
        prompt = f"""당신은 목포사랑의교회 행정 문서 분류·표준화 전문 분석가입니다.
아래 새로 제출된 행정 자료를 분석하여 순수 JSON만 출력하세요.

[교회 공식 행정 분류 체계]
{tax_names}

[현재 게시글]
제목: {board['title']} | 분류: {board['category']} | 작업형태: {board['work_type']}

[현재 열려 있는 다른 모집 게시글 목록]
{other_boards_desc}

[제출된 자료]
제목: {submission['title']}
파일명: {submission['file_name']}
작성자 메모: {submission['notes'][:1200]}
본문 발췌:
{submission['extracted_text'][:3200]}

[출력 JSON 스키마 — 순수 JSON만 출력]
{{
  "summary": "핵심 내용 1~2문장 요약",
  "tags": ["핵심태그1", "핵심태그2", "핵심태그3"],
  "cluster_key": "유사 서식/규격을 묶기 위한 짧은 표준 주제명 (예: 휴가·휴직 청원 규격)",
  "suggestions": [
    {{
      "target_board_id": "위 목록 중 일치하는 다른 게시글 id (아직 해당 분류 게시글이 없으면 빈 문자열 '')",
      "suggested_category": "위 교회 공식 행정 분류 체계 중 추천 분류명 (예: 재정부, 차량관리부, 예배선교부)",
      "action_type": "move | copy | merge | deferred 중 하나",
      "confidence": 85,
      "reason": "왜 다른 분류로 이동/복사/병합하거나 향후 새 분류를 위해 기억해야 하는지 1~2문장 설명"
    }}
  ]
}}
규칙: 현재 게시글에만 완전히 속하고 타 분류 연관이 없다면 suggestions는 빈 배열 []로 두세요. 타 분류 내용이 섞여 있거나 다른 분류가 더 적합할 때만 제안하세요.
"""
        ai_cfg = load_ai_config(db)
        provider_id = ai_cfg.cli_provider
        failover = ai_cfg.failover_enabled
        try:
            parts: list[str] = []
            async for _, ch in stream_cli_with_failover(
                provider_id, prompt, failover_enabled=failover, timeout_sec=45, ai_config=ai_cfg
            ):
                parts.append(ch)
            raw = "".join(parts)
            m = re.search(r"\{[\s\S]*\}", raw)
            if m:
                parsed = json.loads(m.group(0))
                if isinstance(parsed, dict) and parsed.get("summary"):
                    result = {
                        "summary": str(parsed.get("summary", heur["summary"])),
                        "tags": list(parsed.get("tags") or heur["tags"]),
                        "cluster_key": str(parsed.get("cluster_key") or heur["cluster_key"]),
                        "suggestions": list(parsed.get("suggestions") or heur["suggestions"]),
                    }
        except Exception:
            # Seamless offline fallback to heuristic analyzer
            pass

    store.update_submission_ai(
        sub_id=submission["id"],
        ai_summary=result["summary"],
        ai_tags=[str(t) for t in result["tags"][:8]],
        ai_cluster_key=result["cluster_key"],
    )

    valid_board_ids = {b["id"] for b in all_boards if b["id"] != board["id"]}
    created_memories: list[dict[str, Any]] = []
    auto_applied_count = 0

    for sug in result.get("suggestions", [])[:3]:
        target_id = str(sug.get("target_board_id") or "").strip()
        if target_id and target_id not in valid_board_ids:
            target_id = ""
        act = str(sug.get("action_type") or ("copy" if target_id else "deferred")).strip()
        if not target_id:
            act = "deferred"
        conf = int(sug.get("confidence") or 75)
        reason = str(sug.get("reason") or "").strip()
        cat = str(sug.get("suggested_category") or "").strip()
        if not reason:
            continue

        mem = store.create_cross_memory(
            submission_id=submission["id"],
            source_board_id=board["id"],
            target_board_id=target_id,
            suggested_category=cat,
            action_type=act,
            confidence=conf,
            reason=reason,
            status="pending",
        )

        # Optional high-confidence automatic routing (User selected Option 1 default + Option 2 parallel!)
        if bool(board.get("auto_route_enabled")) and target_id and conf >= 85 and act in ("move", "copy"):
            applied_sub = execute_cross_action_sync(
                store=store,
                action=act,
                submission_ids=[submission["id"]],
                target_board_id=target_id,
                memory_id=mem["id"],
                mark_auto=True,
            )
            if applied_sub:
                auto_applied_count += 1
                mem = store.get_cross_memory(mem["id"]) or mem

        created_memories.append(mem)

    return {
        "summary": result["summary"],
        "tags": result["tags"],
        "cluster_key": result["cluster_key"],
        "memories": created_memories,
        "auto_applied_count": auto_applied_count,
    }


def rematch_deferred_memories_for_board(
    store: StandardizationStore,
    target_board: dict[str, Any],
    db: Database | None = None,
) -> list[dict[str, Any]]:
    """When a new board is created (or rescanned), wake up matching remembered items from same-scope boards using active church taxonomy!"""
    haystack = re.sub(
        r"\s+",
        "",
        f"{target_board['title']} {target_board['category']} {target_board['work_type']} {target_board['description']}",
    ).lower()
    board_tokens = {t for t in re.findall(r"[가-힣a-z0-9]{2,}", haystack)}
    target_gid = (target_board.get("group_id") or "").strip()
    active_tax = _get_active_taxonomy(db)

    matched: list[dict[str, Any]] = []
    all_pending = store.list_cross_memories(status="pending")
    for mem in all_pending:
        # Strict group isolation: public <-> public, private group <-> same private group only
        src_gid = (mem.get("source_board_group_id") or "").strip()
        if src_gid != target_gid:
            continue
        if mem["source_board_id"] == target_board["id"]:
            continue
        if mem["target_board_id"] == target_board["id"]:
            matched.append(mem)
            continue
        if mem["target_board_id"]:
            continue  # already bound to another board

        sug_text = re.sub(
            r"\s+",
            "",
            f"{mem['suggested_category']} {mem['reason']} {mem['submission_title']}",
        ).lower()
        sug_tokens = {t for t in re.findall(r"[가-힣a-z0-9]{2,}", sug_text)}

        # Check taxonomy overlap or direct token overlap (respecting custom StdConfig categories!)
        overlap = board_tokens & sug_tokens
        tax_match = False
        for cat_name, kws in active_tax:
            cat_parts = [p for p in re.split(r"[·/\s]+", cat_name) if len(p) >= 2]
            in_board = any(p in haystack for p in cat_parts) or any(k in haystack for k in kws[:6])
            in_mem = any(p in sug_text for p in cat_parts) or any(k in sug_text for k in kws[:6])
            if in_board and in_mem:
                tax_match = True
                break

        if overlap or tax_match:
            updated = store.update_cross_memory(
                mem["id"],
                target_board_id=target_board["id"],
                action_type="copy" if mem["action_type"] == "deferred" else mem["action_type"],
            )
            if updated:
                matched.append(updated)

    return matched


def execute_cross_action_sync(
    store: StandardizationStore,
    action: str,
    submission_ids: list[str],
    target_board_id: str,
    memory_id: str | None = None,
    merged_title: str = "",
    mark_auto: bool = False,
) -> dict[str, Any] | None:
    """Execute Move, Copy (parallel), Merge, Dismiss, or Revert cleanly with full auditability."""
    if action == "dismiss" and memory_id:
        return store.update_cross_memory(memory_id, status="dismissed")

    if action == "revert" and memory_id:
        mem = store.get_cross_memory(memory_id)
        if not mem:
            return None
        if mem["action_type"] == "move":
            store.move_submission_board(mem["submission_id"], mem["source_board_id"], origin_tag="direct")
        elif mem["applied_submission_id"]:
            store.delete_submission(mem["applied_submission_id"])
        return store.update_cross_memory(memory_id, status="reverted", applied_submission_id="")

    target_board = store.get_board(target_board_id)
    if not target_board:
        raise ValueError("대상 모집 게시글을 찾을 수 없습니다.")

    subs = [s for sid in submission_ids if (s := store.get_submission(sid)) is not None]
    if not subs:
        raise ValueError("선택된 제출 자료를 찾을 수 없습니다.")

    done_status = "auto_applied" if mark_auto else "applied"

    if action == "move":
        moved_sub = store.move_submission_board(subs[0]["id"], target_board_id, origin_tag="moved")
        if memory_id and moved_sub:
            store.update_cross_memory(
                memory_id,
                status=done_status,
                target_board_id=target_board_id,
                action_type="move",
                applied_submission_id=moved_sub["id"],
            )
        return moved_sub

    if action == "copy":
        created_last = None
        for s in subs:
            new_stored = ""
            if s.get("stored_path") and Path(s["stored_path"]).exists():
                dst = get_std_uploads_dir(target_board_id) / f"copy_{Path(s['stored_path']).name}"
                shutil.copy2(s["stored_path"], dst)
                new_stored = str(dst)
            created_last = store.create_submission(
                board_id=target_board_id,
                title=s["title"],
                notes=s["notes"],
                author_label=s["author_label"],
                owner_id=s["owner_id"],
                is_anonymous=bool(s["is_anonymous"]),
                file_name=s["file_name"],
                file_type=s["file_type"],
                stored_path=new_stored,
                extracted_text=s["extracted_text"],
                ai_summary=s["ai_summary"],
                ai_tags=s.get("ai_tags", []),
                ai_cluster_key=s["ai_cluster_key"],
                source_origin="copied",
                origin_submission_id=s["id"],
            )
        if memory_id and created_last:
            store.update_cross_memory(
                memory_id,
                status=done_status,
                target_board_id=target_board_id,
                action_type="copy",
                applied_submission_id=created_last["id"],
            )
        return created_last

    if action == "merge":
        # Merge 1+ submissions cleanly into a unified consolidated submission in target_board
        title = merged_title.strip() or f"[통합 병합] {subs[0]['title']}" + (f" 외 {len(subs) - 1}건" if len(subs) > 1 else "")
        merged_notes = "\n\n---\n\n".join(
            f"[{s['title']} · 제출: {s['author_label']}]\n{s['notes']}" for s in subs if s["notes"].strip()
        )
        merged_text = "\n\n====================\n\n".join(
            f"## 출처 자료: {s['title']} ({s['file_name'] or '직접 작성'})\n\n{s['extracted_text'] or s['notes']}"
            for s in subs
        )
        all_tags: list[str] = []
        for s in subs:
            for t in s.get("ai_tags", []):
                if t not in all_tags:
                    all_tags.append(t)
        merged_sub = store.create_submission(
            board_id=target_board_id,
            title=title,
            notes=merged_notes or f"총 {len(subs)}개 제출 자료 통합 병합본",
            author_label="관리자 통합",
            owner_id="admin_merge",
            is_anonymous=False,
            file_name="통합병합본.txt",
            file_type="txt",
            stored_path="",
            extracted_text=merged_text,
            ai_summary=f"총 {len(subs)}건의 관련 행정 자료를 통합 병합한 표준 초안 자료",
            ai_tags=all_tags[:8],
            ai_cluster_key=subs[0].get("ai_cluster_key") or target_board["category"],
            source_origin="merged",
            origin_submission_id=",".join(s["id"] for s in subs)[:40],
        )
        if memory_id:
            store.update_cross_memory(
                memory_id,
                status=done_status,
                target_board_id=target_board_id,
                action_type="merge",
                applied_submission_id=merged_sub["id"],
            )
        return merged_sub

    raise ValueError(f"지원하지 않는 작업 유형입니다: {action}")


async def generate_voting_proposals_for_board(
    db: Database,
    store: StandardizationStore,
    board: dict[str, Any],
    use_ai: bool = True,
) -> list[dict[str, Any]]:
    """Cluster similar submissions on a board into voting proposals with original A/B options + an AI Improved synthesis option."""
    subs = store.list_submissions(board["id"], include_archived=False)
    if not subs:
        return []

    # Group by ai_cluster_key (or fallback to board category when single group)
    groups: dict[str, list[dict[str, Any]]] = {}
    for s in subs:
        key = (s.get("ai_cluster_key") or "").strip() or board["category"]
        groups.setdefault(key, []).append(s)

    existing_by_title = {p["cluster_title"]: p for p in store.list_proposals(board["id"])}
    created: list[dict[str, Any]] = []

    ai_cfg = load_ai_config(db)
    provider_id = ai_cfg.cli_provider
    failover = ai_cfg.failover_enabled

    for cluster_key, items in groups.items():
        if cluster_key in existing_by_title:
            existing_prop = existing_by_title[cluster_key]
            # Incremental enrichment: if newly uploaded files belong to an open proposal, append them as new candidate options!
            if existing_prop.get("status") == "open":
                existing_opts = existing_prop.get("options") or []
                non_ai_opts = [o for o in existing_opts if not o.get("is_ai_improved")]
                covered_ids: set[str] = set()
                for o in non_ai_opts:
                    covered_ids.update(o.get("source_submission_ids") or [])
                uncovered = [s for s in items if s["id"] not in covered_ids]
                if uncovered:
                    base_idx = len(non_ai_opts)
                    for offset, s in enumerate(uncovered[:3]):
                        idx_next = base_idx + offset
                        lbl = f"{chr(65 + idx_next)}안" if idx_next < 10 else f"안 {idx_next + 1}"
                        excerpt = (s["extracted_text"] or s["notes"] or s["ai_summary"])[:1600]
                        store.add_proposal_option(
                            proposal_id=existing_prop["id"],
                            label=lbl,
                            title=f"{s['title']} (추가 원안)",
                            content_md=(
                                f"**제출자**: {'익명 교역자' if board.get('submission_anonymous') else s['author_label']}\n"
                                f"**핵심 요약**: {s['ai_summary'] or s['title']}\n\n"
                                f"{excerpt}"
                            ),
                            source_submission_ids=[s["id"]],
                            is_ai_improved=False,
                        )
                    refreshed = store.get_proposal(existing_prop["id"])
                    if refreshed:
                        created.append(refreshed)
            continue

        options: list[dict[str, Any]] = []
        for idx, s in enumerate(items[:4]):
            lbl = f"{chr(65 + idx)}안"
            excerpt = (s["extracted_text"] or s["notes"] or s["ai_summary"])[:1600]
            options.append(
                {
                    "label": lbl,
                    "title": f"{s['title']} (원안)",
                    "content_md": (
                        f"**제출자**: {'익명 교역자' if board.get('submission_anonymous') else s['author_label']}\n"
                        f"**핵심 요약**: {s['ai_summary'] or s['title']}\n\n"
                        f"{excerpt}"
                    ),
                    "source_submission_ids": [s["id"]],
                    "is_ai_improved": False,
                }
            )

        # Synthesize an AI Improved consensus option combining all strengths in this cluster
        ai_content = ""
        ai_summary = f"제출된 {len(items)}건의 유사 행정 자료를 비교하고 공통 표준 규격을 선택하는 투표 안건입니다."
        if use_ai:
            materials = "\n\n---\n\n".join(
                f"[자료 {i + 1}: {s['title']}]\n메모: {s['notes'][:600]}\n본문:\n{(s['extracted_text'] or '')[:1400]}"
                for i, s in enumerate(items[:4])
            )
            prompt = f"""당신은 목포사랑의교회 행정 규격 표준화 위원회 전문 편집자입니다.
아래 '{cluster_key}' 주제로 여러 목사님들이 제출한 자료들의 장점만 통합하고, 중복·모호한 표현을 개선한 **'AI 통합 개선안'**을 깔끔한 한국어 마크다운으로 작성하세요.
(핵심 목적, 표준 항목/절차, 개선된 보완 포인트 3가지를 간결하게 정리, 900자 이내)

{materials}
"""
            try:
                chunks: list[str] = []
                async for _, c in stream_cli_with_failover(
                    provider_id, prompt, failover_enabled=failover, timeout_sec=50, ai_config=ai_cfg
                ):
                    chunks.append(c)
                ai_content = "".join(chunks).strip()
            except Exception:
                ai_content = ""

        if not ai_content:
            # Clean 100% offline synthesis
            bullet_lines = "\n".join(f"- **{s['title']}**: {s['ai_summary'] or (s['notes'] or s['extracted_text'])[:140]}" for s in items[:4])
            ai_content = (
                f"### {cluster_key} 표준 통합 개선안\n\n"
                f"제출된 {len(items)}건의 원안을 통합하여 항목 체계를 단일화하고 실무 가독성을 높인 안입니다.\n\n"
                f"#### 반영된 원안 핵심\n{bullet_lines}\n\n"
                f"#### 표준화 개선 포인트\n"
                f"1. 중복 기입 항목을 통합하고 필수 기재란과 선택 기재란을 명확히 분리\n"
                f"2. 목포사랑의교회 정관 및 시행세칙 결재 위계(담당자 → 부서장 → 당회장)에 맞춘 서명란 통일\n"
                f"3. 인쇄·보관용 A4 표준 규격과 파일 명명 규칙 일원화"
            )

        options.append(
            {
                "label": "AI 개선안",
                "title": f"{cluster_key} — AI 통합 표준 개선안",
                "content_md": ai_content,
                "source_submission_ids": [s["id"] for s in items],
                "is_ai_improved": True,
            }
        )

        prop = store.create_proposal(
            board_id=board["id"],
            cluster_title=cluster_key,
            category_tag=board["category"],
            summary=ai_summary,
            options=options,
        )
        created.append(prop)

    if created and board["status"] == "collecting":
        store.update_board(board["id"], status="voting")
    return created
