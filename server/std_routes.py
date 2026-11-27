from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import re
import uuid
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from core.config import DEFAULT_NOTEBOOK_ID
from core.database import Database
from core.ingest import ingest_file, replace_document_file
from core.std_config import load_std_config, reset_std_config, save_std_config
from core.std_engine import (
    IMAGE_EXTENSIONS,
    MAX_STD_FILE_BYTES,
    STD_ALLOWED_EXTENSIONS,
    analyze_submission_and_cross_routes,
    execute_cross_action_sync,
    extract_submission_file,
    generate_voting_proposals_for_board,
    rematch_deferred_memories_for_board,
)
from core.std_publisher import (
    generate_committee_draft_stream,
    register_publication_forms_to_vault,
    stream_committee_compile,
    typeset_manuscript_to_publication,
)
from core.std_store import StandardizationStore, get_std_uploads_dir
from server.auth import AuthUser, get_client_ip, require_admin, require_user
from server.backup import create_backup

router = APIRouter(prefix="/api/std", tags=["standardization"])


class BoardCreateReq(BaseModel):
    title: str = Field(..., min_length=2, max_length=120)
    category: str = Field(default="일반 행정", max_length=60)
    work_type: str = Field(default="규정·서식 표준화", max_length=60)
    description: str = Field(default="", max_length=2000)
    guidelines: str = Field(default="", max_length=3000)
    deadline: str = Field(default="", max_length=40)
    vote_visibility: str = Field(default="named")  # named | anonymous
    submission_anonymous: bool = False
    allow_vote_change: bool = True
    auto_route_enabled: bool = False
    group_id: str = Field(default="", max_length=48)
    quorum_target: int = Field(default=0, ge=0, le=500)


class BoardUpdateReq(BaseModel):
    title: str | None = None
    category: str | None = None
    work_type: str | None = None
    description: str | None = None
    guidelines: str | None = None
    status: str | None = None  # collecting | voting | published
    deadline: str | None = None
    vote_visibility: str | None = None
    submission_anonymous: bool | None = None
    allow_vote_change: bool | None = None
    auto_route_enabled: bool | None = None
    group_id: str | None = None
    quorum_target: int | None = None


class SubmissionUpdateReq(BaseModel):
    title: str | None = Field(default=None, max_length=160)
    notes: str | None = Field(default=None, max_length=5000)
    ai_cluster_key: str | None = Field(default=None, max_length=80)
    reanalyze: bool = False
    use_ai: bool = True


class CrossMemoryActionReq(BaseModel):
    action: str = Field(..., pattern="^(move|copy|merge|dismiss|revert)$")
    target_board_id: str = ""
    merged_title: str = ""


class BatchSubmissionActionReq(BaseModel):
    action: str = Field(..., pattern="^(move|copy|merge)$")
    submission_ids: list[str] = Field(..., min_length=1)
    target_board_id: str = Field(..., min_length=1)
    merged_title: str = ""


class ProposalCreateReq(BaseModel):
    cluster_title: str = Field(..., min_length=2, max_length=140)
    category_tag: str = Field(default="공통 규격", max_length=60)
    summary: str = Field(default="", max_length=1200)
    options: list[dict[str, Any]] = Field(..., min_length=1)


class ProposalOptionUpdateReq(BaseModel):
    label: str | None = Field(default=None, max_length=30)
    title: str | None = Field(default=None, max_length=160)
    content_md: str | None = Field(default=None, max_length=12000)


class VoteCastReq(BaseModel):
    option_id: str = Field(..., min_length=1)
    comment: str = Field(default="", max_length=500)


class ProposalUpdateReq(BaseModel):
    status: str | None = None  # open | closed | adopted
    winning_option_id: str | None = None


class CommentCreateReq(BaseModel):
    content: str = Field(..., min_length=2, max_length=2000)
    proposal_id: str = ""
    submission_id: str = ""
    kind: str = Field(default="improvement")  # improvement | question | decision


class CompileReq(BaseModel):
    version_label: str = Field(default="", max_length=30)
    custom_directives: str = Field(default="", max_length=2000)
    approval_preset_id: str = Field(default="", max_length=40)
    custom_approval_slots: list[str] | None = None
    include_images: bool = True


class FinalizeManuscriptReq(BaseModel):
    version_label: str = Field(default="", max_length=30)
    manuscript: dict[str, Any]
    law_audit: list[dict[str, Any]] = Field(default_factory=list)
    vote_summary: list[dict[str, Any]] = Field(default_factory=list)
    approval_preset_id: str = Field(default="", max_length=40)
    custom_approval_slots: list[str] | None = None
    ai_engine: str = Field(default="edited-manuscript", max_length=60)
    include_images: bool = True


class StdConfigUpdateReq(BaseModel):
    categories: list[dict[str, Any]] | None = None
    work_types: list[str] | None = None
    approval_presets: list[dict[str, Any]] | None = None
    pdf_template: dict[str, Any] | None = None


class PublishToQaReq(BaseModel):
    notebook_id: str = DEFAULT_NOTEBOOK_ID
    replace_doc_id: str = ""  # empty = register as new official doc; non-empty = revise existing doc
    title: str = ""
    category: str = ""
    priority: int = 85


class RegisterFormsReq(BaseModel):
    notebook_id: str = DEFAULT_NOTEBOOK_ID


def _get_store(request: Request) -> StandardizationStore:
    store: StandardizationStore | None = getattr(request.app.state, "std_store", None)
    if store is None:
        db: Database = request.app.state.db
        store = StandardizationStore(db_path=db.db_path)
        request.app.state.std_store = store
    return store


def _can_manage_board(board: dict[str, Any], db: Database, user: AuthUser) -> bool:
    """Admin can manage all boards; a Group Leader can manage standardization boards belonging to their own group."""
    if user.role == "admin":
        return True
    gid = (board.get("group_id") or "").strip()
    if gid and db.get_group_member_role(gid, user.owner_id) == "leader":
        return True
    return False


def _assert_board_access(board: dict[str, Any], db: Database, user: AuthUser) -> None:
    gid = (board.get("group_id") or "").strip()
    if not gid or user.role == "admin":
        return
    if not db.is_group_member(gid, user.owner_id):
        raise HTTPException(status_code=403, detail="이 표준화 과제는 초대된 그룹 멤버만 접근할 수 있습니다.")


def _assert_board_manage(board: dict[str, Any], db: Database, user: AuthUser) -> None:
    if not _can_manage_board(board, db, user):
        raise HTTPException(
            status_code=403,
            detail="관리자 또는 해당 그룹의 그룹장만 이 표준화 과제를 관리할 수 있습니다.",
        )


def _emit_std(request: Request, board_id: str, group_id: str = "", actor_label: str = "") -> None:
    bus = getattr(request.app.state, "events", None)
    if bus is not None:
        bus.publish("std_updated", board_id=board_id, group_id=group_id, actor_label=actor_label)


def _invalidate_qa_cache_and_notify(request: Request, notebook_id: str, actor_label: str = "") -> None:
    cache = getattr(request.app.state, "answer_cache", None)
    if cache is not None:
        try:
            cache.invalidate_all()
        except Exception:
            pass
    bus = getattr(request.app.state, "events", None)
    if bus is not None:
        bus.publish("doc_library_updated", notebook_id=notebook_id, actor_label=actor_label)


def _is_deadline_expired(deadline: str) -> bool:
    d_str = (deadline or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d_str):
        return False
    return d_str < date.today().isoformat()


# ---- Church Taxonomy, Approval Lines & PDF Cover Template Config ----
@router.get("/config")
def get_std_config_route(request: Request, _: AuthUser = Depends(require_user)) -> dict[str, Any]:
    return load_std_config(request.app.state.db)


@router.put("/config")
def save_std_config_route(
    body: StdConfigUpdateReq,
    request: Request,
    user: AuthUser = Depends(require_admin),
) -> dict[str, Any]:
    db: Database = request.app.state.db
    current = load_std_config(db)
    merged = {
        "categories": body.categories if body.categories is not None else current["categories"],
        "work_types": body.work_types if body.work_types is not None else current["work_types"],
        "approval_presets": body.approval_presets if body.approval_presets is not None else current["approval_presets"],
        "pdf_template": body.pdf_template if body.pdf_template is not None else current["pdf_template"],
    }
    saved = save_std_config(db, merged)
    db.log_audit(
        "std_config_updated",
        user.role,
        user.label,
        get_client_ip(request),
        f"분류 {len(saved['categories'])}개 · 결재선 {len(saved['approval_presets'])}개 수정",
    )
    return saved


@router.post("/config/reset")
def reset_std_config_route(
    request: Request,
    user: AuthUser = Depends(require_admin),
) -> dict[str, Any]:
    db: Database = request.app.state.db
    cfg = reset_std_config(db)
    db.log_audit("std_config_reset", user.role, user.label, get_client_ip(request), "2025 시행세칙 기본 규격 복원")
    return cfg


# ---- Boards ----
@router.get("/boards")
def list_boards(request: Request, user: AuthUser = Depends(require_user)) -> list[dict[str, Any]]:
    db: Database = request.app.state.db
    allowed_gids = db.get_user_group_ids(user.owner_id)
    boards = _get_store(request).list_boards(allowed_group_ids=allowed_gids, is_admin=(user.role == "admin"))
    for b in boards:
        b["can_manage"] = _can_manage_board(b, db, user)
    return boards


@router.post("/boards")
def create_board(
    body: BoardCreateReq,
    request: Request,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    store = _get_store(request)
    db: Database = request.app.state.db
    gid = (body.group_id or "").strip()
    if user.role != "admin":
        if not gid or db.get_group_member_role(gid, user.owner_id) != "leader":
            raise HTTPException(status_code=403, detail="관리자 또는 해당 그룹장만 표준화 모집 게시글을 개설할 수 있습니다.")
    if gid and not db.get_group(gid):
        raise HTTPException(status_code=404, detail="선택한 그룹을 찾을 수 없습니다.")

    board = store.create_board(
        title=body.title,
        category=body.category,
        work_type=body.work_type,
        description=body.description,
        guidelines=body.guidelines,
        deadline=body.deadline,
        vote_visibility=body.vote_visibility,
        submission_anonymous=body.submission_anonymous,
        allow_vote_change=body.allow_vote_change,
        auto_route_enabled=body.auto_route_enabled,
        group_id=gid,
        quorum_target=body.quorum_target,
        created_by=user.label,
    )
    board["can_manage"] = _can_manage_board(board, db, user)
    # Immediately wake up same-scope deferred cross-board memories using active church taxonomy!
    matched_memories = rematch_deferred_memories_for_board(store, board, db=db)
    db.log_audit("std_board_created", user.role, user.label, get_client_ip(request), f"표준화 게시글: {board['title']}")
    _emit_std(request, board["id"], group_id=gid, actor_label=user.label)
    return {**board, "matched_memories": matched_memories}


@router.get("/boards/{board_id}")
def get_board_detail(
    board_id: str,
    request: Request,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    store = _get_store(request)
    db: Database = request.app.state.db
    board = store.get_board(board_id)
    if not board:
        raise HTTPException(status_code=404, detail="모집 게시글을 찾을 수 없습니다.")
    _assert_board_access(board, db, user)
    can_manage = _can_manage_board(board, db, user)
    board["can_manage"] = can_manage
    mask_sub = bool(board.get("submission_anonymous")) and not can_manage
    anon_votes = board.get("vote_visibility") == "anonymous"

    allowed_gids = db.get_user_group_ids(user.owner_id)
    visible_ids = (
        None
        if user.role == "admin"
        else {b["id"] for b in store.list_boards(allowed_group_ids=allowed_gids, is_admin=False)}
    )
    return {
        "board": board,
        "can_manage": can_manage,
        "submissions": store.list_submissions(board_id, mask_anonymous=mask_sub),
        "proposals": store.list_proposals(board_id, viewer_voter_id=user.owner_id, anonymous_votes=anon_votes),
        "comments": store.list_comments(board_id, mask_anonymous=mask_sub),
        "memories": store.list_cross_memories(board_id=board_id, visible_board_ids=visible_ids),
        "publications": store.list_publications(board_id),
    }


@router.patch("/boards/{board_id}")
def update_board(
    board_id: str,
    body: BoardUpdateReq,
    request: Request,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    store = _get_store(request)
    db: Database = request.app.state.db
    board = store.get_board(board_id)
    if not board:
        raise HTTPException(status_code=404, detail="모집 게시글을 찾을 수 없습니다.")
    _assert_board_manage(board, db, user)
    payload = body.model_dump(exclude_none=True)
    # Non-admin group leaders cannot transfer a group board into public or another group
    if user.role != "admin":
        payload.pop("group_id", None)
    updated = store.update_board(board_id, **payload)
    if not updated:
        raise HTTPException(status_code=404, detail="모집 게시글을 찾을 수 없습니다.")
    updated["can_manage"] = _can_manage_board(updated, db, user)
    _emit_std(request, board_id, group_id=updated.get("group_id", ""), actor_label=user.label)
    return updated


@router.delete("/boards/{board_id}")
def delete_board(
    board_id: str,
    request: Request,
    user: AuthUser = Depends(require_user),
) -> dict[str, bool]:
    store = _get_store(request)
    db: Database = request.app.state.db
    board = store.get_board(board_id)
    if not board:
        raise HTTPException(status_code=404, detail="모집 게시글을 찾을 수 없습니다.")
    _assert_board_manage(board, db, user)
    gid = board.get("group_id", "")
    ok = store.delete_board(board_id)
    if not ok:
        raise HTTPException(status_code=404, detail="모집 게시글을 찾을 수 없습니다.")
    db.log_audit("std_board_deleted", user.role, user.label, get_client_ip(request), f"삭제: {board['title']} ({board_id})")
    _emit_std(request, board_id, group_id=gid, actor_label=user.label)
    return {"ok": True}


# ---- Submissions (Files [PDF/Office/PPTX/Images] + Pastor Field Notes) ----
@router.post("/boards/{board_id}/submissions")
async def create_submission(
    board_id: str,
    request: Request,
    title: str = Form(""),
    notes: str = Form(""),
    file: UploadFile | None = File(None),
    use_ai: bool = Form(True),
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    store = _get_store(request)
    db: Database = request.app.state.db
    board = store.get_board(board_id)
    if not board:
        raise HTTPException(status_code=404, detail="모집 게시글을 찾을 수 없습니다.")
    _assert_board_access(board, db, user)

    file_name = ""
    file_type = ""
    stored_path = ""
    extracted_text = ""
    file_hash = ""
    file_size = 0
    file_meta: dict[str, Any] = {}
    duplicate_of: dict[str, Any] | None = None

    if file is not None and file.filename:
        orig_name = Path(file.filename).name
        ext = Path(orig_name).suffix.lower()
        if ext not in STD_ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"지원하지 않는 파일 형식입니다({orig_name}). 지원 형식: PDF, Word, HWPX, Excel, PPTX, 이미지(PNG·JPG·WEBP 등), TXT, MD",
            )
        safe_name = re.sub(r'[\\/:*?"<>|]+', "_", orig_name)
        dest = get_std_uploads_dir(board_id) / f"{uuid.uuid4().hex[:8]}_{safe_name}"

        hasher = hashlib.sha256()
        total_bytes = 0
        try:
            with dest.open("wb") as out_f:
                while True:
                    chunk = await file.read(1024 * 256)
                    if not chunk:
                        break
                    total_bytes += len(chunk)
                    if total_bytes > MAX_STD_FILE_BYTES:
                        out_f.close()
                        dest.unlink(missing_ok=True)
                        raise HTTPException(
                            status_code=413,
                            detail=f"파일 크기가 최대 허용 용량(30MB)을 초과했습니다: {orig_name}",
                        )
                    hasher.update(chunk)
                    out_f.write(chunk)
        except HTTPException:
            raise
        except Exception as exc:
            dest.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail=f"파일 저장 실패: {exc}")

        file_hash = hasher.hexdigest()
        file_size = total_bytes
        dup = store.find_duplicate_submission(board_id, file_hash)
        if dup:
            duplicate_of = {"id": dup["id"], "title": dup["title"], "file_name": dup["file_name"]}

        file_name = orig_name
        file_type = ext.lstrip(".")
        stored_path = str(dest)
        extracted_text, file_meta = await asyncio.to_thread(extract_submission_file, dest)

    final_title = title.strip() or (Path(file_name).stem if file_name else "") or notes.strip()[:40]
    if not final_title:
        raise HTTPException(status_code=400, detail="파일을 첨부하거나 제출 제목/내용을 입력해 주세요.")

    sub = store.create_submission(
        board_id=board_id,
        title=final_title,
        notes=notes,
        author_label=user.label,
        owner_id=user.owner_id,
        is_anonymous=bool(board.get("submission_anonymous")),
        file_name=file_name,
        file_type=file_type,
        stored_path=stored_path,
        extracted_text=extracted_text,
        file_hash=file_hash,
        file_size=file_size,
        meta=file_meta,
    )

    ai_analysis = await analyze_submission_and_cross_routes(
        db=db,
        store=store,
        board=board,
        submission=sub,
        use_ai=use_ai,
    )
    refreshed = store.get_submission(sub["id"]) or sub
    _emit_std(request, board_id, group_id=board.get("group_id", ""), actor_label=user.label)
    return {
        "ok": True,
        "submission": refreshed,
        "duplicate_of": duplicate_of,
        "analysis": ai_analysis,
    }


@router.get("/submissions/{sub_id}/file")
def get_submission_file(
    sub_id: str,
    request: Request,
    download: int = 0,
    user: AuthUser = Depends(require_user),
) -> FileResponse:
    """Serve original uploaded file (inline image/PDF preview or attachment download) with strict board access check."""
    store = _get_store(request)
    db: Database = request.app.state.db
    sub = store.get_submission(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="제출 자료를 찾을 수 없습니다.")
    board = store.get_board(sub["board_id"])
    if board:
        _assert_board_access(board, db, user)
    sp = (sub.get("stored_path") or "").strip()
    if not sp or not Path(sp).exists():
        raise HTTPException(status_code=404, detail="원본 첨부 파일이 존재하지 않습니다.")

    p = Path(sp)
    orig_name = sub.get("file_name") or p.name
    media_type, _ = mimetypes.guess_type(orig_name)
    if not media_type:
        if p.suffix.lower() == ".hwpx":
            media_type = "application/hwp+zip"
        elif p.suffix.lower() == ".pptx":
            media_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        else:
            media_type = "application/octet-stream"

    encoded = quote(orig_name)
    is_inline_safe = (p.suffix.lower() in IMAGE_EXTENSIONS or p.suffix.lower() == ".pdf") and not download
    disp = "inline" if is_inline_safe else "attachment"
    return FileResponse(
        path=str(p),
        media_type=media_type,
        headers={
            "Content-Disposition": f"{disp}; filename*=UTF-8''{encoded}",
            "Cache-Control": "private, max-age=300",
        },
    )


@router.patch("/submissions/{sub_id}")
async def update_submission(
    sub_id: str,
    body: SubmissionUpdateReq,
    request: Request,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    store = _get_store(request)
    db: Database = request.app.state.db
    sub = store.get_submission(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="제출 자료를 찾을 수 없습니다.")
    board = store.get_board(sub["board_id"])
    if not board:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")
    can_manage = _can_manage_board(board, db, user)
    if not can_manage and sub["owner_id"] != user.owner_id:
        raise HTTPException(status_code=403, detail="본인 제출 자료, 그룹장 또는 관리자만 수정할 수 있습니다.")

    updated = store.update_submission(
        sub_id=sub_id,
        title=body.title,
        notes=body.notes,
        ai_cluster_key=body.ai_cluster_key,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="제출 자료를 찾을 수 없습니다.")

    analysis = None
    if body.reanalyze:
        analysis = await analyze_submission_and_cross_routes(
            db=db,
            store=store,
            board=board,
            submission=updated,
            use_ai=body.use_ai,
        )
        updated = store.get_submission(sub_id) or updated

    _emit_std(request, board["id"], group_id=board.get("group_id", ""), actor_label=user.label)
    return {"ok": True, "submission": updated, "analysis": analysis}


@router.delete("/submissions/{sub_id}")
def delete_submission(
    sub_id: str,
    request: Request,
    user: AuthUser = Depends(require_user),
) -> dict[str, bool]:
    store = _get_store(request)
    db: Database = request.app.state.db
    sub = store.get_submission(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="제출 자료를 찾을 수 없습니다.")
    board = store.get_board(sub["board_id"])
    can_manage = _can_manage_board(board, db, user) if board else (user.role == "admin")
    if not can_manage and sub["owner_id"] != user.owner_id:
        raise HTTPException(status_code=403, detail="본인 제출 자료, 그룹장 또는 관리자만 삭제할 수 있습니다.")
    store.delete_submission(sub_id)
    if board:
        _emit_std(request, board["id"], group_id=board.get("group_id", ""), actor_label=user.label)
    return {"ok": True}


# ---- Cross-Board AI Memory & Manual Move / Copy / Merge / Undo ----
@router.get("/cross-memory")
def list_cross_memory(
    request: Request,
    board_id: str = "",
    status: str = "",
    user: AuthUser = Depends(require_user),
) -> list[dict[str, Any]]:
    store = _get_store(request)
    db: Database = request.app.state.db
    if user.role == "admin":
        return store.list_cross_memories(board_id=board_id, status=status)
    allowed_gids = db.get_user_group_ids(user.owner_id)
    visible_ids = {b["id"] for b in store.list_boards(allowed_group_ids=allowed_gids, is_admin=False)}
    return store.list_cross_memories(board_id=board_id, status=status, visible_board_ids=visible_ids)


@router.post("/boards/{board_id}/scan-memory")
def scan_deferred_memory(
    board_id: str,
    request: Request,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    store = _get_store(request)
    db: Database = request.app.state.db
    board = store.get_board(board_id)
    if not board:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")
    _assert_board_manage(board, db, user)
    matched = rematch_deferred_memories_for_board(store, board, db=db)
    if matched:
        _emit_std(request, board_id, group_id=board.get("group_id", ""), actor_label=user.label)
    return {"ok": True, "matched": matched}


@router.post("/cross-memory/{mem_id}/apply")
def apply_cross_memory(
    mem_id: str,
    body: CrossMemoryActionReq,
    request: Request,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    store = _get_store(request)
    db: Database = request.app.state.db
    mem = store.get_cross_memory(mem_id)
    if not mem:
        raise HTTPException(status_code=404, detail="교차 분류 기억 항목을 찾을 수 없습니다.")
    src_board = store.get_board(mem["source_board_id"])
    target_id = body.target_board_id.strip() or mem["target_board_id"]
    tgt_board = store.get_board(target_id) if target_id else None

    if user.role != "admin":
        if not src_board or not _can_manage_board(src_board, db, user):
            raise HTTPException(status_code=403, detail="해당 그룹장 또는 관리자만 교차 분류를 적용할 수 있습니다.")
        if tgt_board and not _can_manage_board(tgt_board, db, user):
            raise HTTPException(status_code=403, detail="대상 게시글의 관리 권한이 없습니다.")

    try:
        res = execute_cross_action_sync(
            store=store,
            action=body.action,
            submission_ids=[mem["submission_id"]],
            target_board_id=target_id,
            memory_id=mem_id,
            merged_title=body.merged_title,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.log_audit(
        "std_cross_action",
        user.role,
        user.label,
        get_client_ip(request),
        f"{body.action}: {mem['submission_title']} -> {target_id}",
    )
    _emit_std(request, mem["source_board_id"], group_id=(src_board or {}).get("group_id", ""), actor_label=user.label)
    if target_id and target_id != mem["source_board_id"]:
        _emit_std(request, target_id, group_id=(tgt_board or {}).get("group_id", ""), actor_label=user.label)
    return {"ok": True, "result": res, "memory": store.get_cross_memory(mem_id)}


@router.post("/submissions/batch-action")
def batch_submission_action(
    body: BatchSubmissionActionReq,
    request: Request,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    store = _get_store(request)
    db: Database = request.app.state.db
    tgt_board = store.get_board(body.target_board_id)
    if not tgt_board:
        raise HTTPException(status_code=404, detail="대상 모집 게시글을 찾을 수 없습니다.")
    _assert_board_manage(tgt_board, db, user)

    if user.role != "admin":
        for sid in body.submission_ids:
            s = store.get_submission(sid)
            if s:
                sb = store.get_board(s["board_id"])
                if sb:
                    _assert_board_manage(sb, db, user)

    try:
        res = execute_cross_action_sync(
            store=store,
            action=body.action,
            submission_ids=body.submission_ids,
            target_board_id=body.target_board_id,
            merged_title=body.merged_title,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.log_audit(
        "std_manual_batch",
        user.role,
        user.label,
        get_client_ip(request),
        f"수동 {body.action} ({len(body.submission_ids)}건) -> {body.target_board_id}",
    )
    _emit_std(request, body.target_board_id, group_id=tgt_board.get("group_id", ""), actor_label=user.label)
    return {"ok": True, "result": res}


# ---- Proposals, Options, Voting & Improvement Comments ----
@router.post("/boards/{board_id}/generate-proposals")
async def generate_proposals(
    board_id: str,
    request: Request,
    use_ai: bool = True,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    store = _get_store(request)
    db: Database = request.app.state.db
    board = store.get_board(board_id)
    if not board:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")
    _assert_board_manage(board, db, user)
    created = await generate_voting_proposals_for_board(db, store, board, use_ai=use_ai)
    _emit_std(request, board_id, group_id=board.get("group_id", ""), actor_label=user.label)
    return {"ok": True, "created": created, "count": len(created)}


@router.post("/boards/{board_id}/proposals")
def create_proposal_manual(
    board_id: str,
    body: ProposalCreateReq,
    request: Request,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    store = _get_store(request)
    db: Database = request.app.state.db
    board = store.get_board(board_id)
    if not board:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")
    _assert_board_manage(board, db, user)
    created = store.create_proposal(
        board_id=board_id,
        cluster_title=body.cluster_title,
        category_tag=body.category_tag,
        summary=body.summary,
        options=body.options,
    )
    _emit_std(request, board_id, group_id=board.get("group_id", ""), actor_label=user.label)
    return created


@router.patch("/proposal-options/{option_id}")
def update_proposal_option_route(
    option_id: str,
    body: ProposalOptionUpdateReq,
    request: Request,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    """Allow admin or group leader to polish proposal option wording before/after adoption."""
    store = _get_store(request)
    db: Database = request.app.state.db
    opt = store.get_proposal_option(option_id)
    if not opt:
        raise HTTPException(status_code=404, detail="투표 후보안을 찾을 수 없습니다.")
    prop = store.get_proposal(opt["proposal_id"])
    if not prop:
        raise HTTPException(status_code=404, detail="투표 안건을 찾을 수 없습니다.")
    board = store.get_board(prop["board_id"])
    if board:
        _assert_board_manage(board, db, user)
    updated = store.update_proposal_option(
        option_id=option_id,
        label=body.label,
        title=body.title,
        content_md=body.content_md,
    )
    if board:
        _emit_std(request, board["id"], group_id=board.get("group_id", ""), actor_label=user.label)
    return {"ok": True, "option": updated}


@router.post("/proposals/{proposal_id}/vote")
def cast_vote(
    proposal_id: str,
    body: VoteCastReq,
    request: Request,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    store = _get_store(request)
    prop = store.get_proposal(proposal_id)
    if not prop:
        raise HTTPException(status_code=404, detail="투표 안건을 찾을 수 없습니다.")
    if prop["status"] != "open":
        raise HTTPException(status_code=400, detail="이미 마감된 투표 안건입니다.")
    board = store.get_board(prop["board_id"])
    if board:
        _assert_board_access(board, request.app.state.db, user)
        if _is_deadline_expired(board.get("deadline", "")):
            raise HTTPException(
                status_code=400,
                detail=f"마감일({board['deadline']})이 지나 투표가 자동 마감되었습니다.",
            )
    allow_change = bool(board.get("allow_vote_change", 1)) if board else True
    try:
        updated = store.cast_vote(
            proposal_id=proposal_id,
            option_id=body.option_id,
            voter_id=user.owner_id or user.label,
            voter_label=user.label,
            comment=body.comment,
            allow_change=allow_change,
        )
        if board:
            _emit_std(request, board["id"], group_id=board.get("group_id", ""), actor_label=user.label)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "proposal": updated}


@router.patch("/proposals/{proposal_id}")
def update_proposal(
    proposal_id: str,
    body: ProposalUpdateReq,
    request: Request,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    store = _get_store(request)
    db: Database = request.app.state.db
    prop = store.get_proposal(proposal_id)
    if not prop:
        raise HTTPException(status_code=404, detail="투표 안건을 찾을 수 없습니다.")
    board = store.get_board(prop["board_id"])
    if board:
        _assert_board_manage(board, db, user)
    updated = store.update_proposal(
        proposal_id, status=body.status, winning_option_id=body.winning_option_id
    )
    if not updated:
        raise HTTPException(status_code=404, detail="투표 안건을 찾을 수 없습니다.")
    if board:
        _emit_std(request, board["id"], group_id=board.get("group_id", ""), actor_label=user.label)
    return updated


@router.delete("/proposals/{proposal_id}")
def delete_proposal(
    proposal_id: str,
    request: Request,
    user: AuthUser = Depends(require_user),
) -> dict[str, bool]:
    store = _get_store(request)
    db: Database = request.app.state.db
    prop = store.get_proposal(proposal_id)
    if not prop:
        raise HTTPException(status_code=404, detail="투표 안건을 찾을 수 없습니다.")
    board = store.get_board(prop["board_id"])
    if board:
        _assert_board_manage(board, db, user)
    ok = store.delete_proposal(proposal_id)
    if not ok:
        raise HTTPException(status_code=404, detail="투표 안건을 찾을 수 없습니다.")
    if board:
        _emit_std(request, board["id"], group_id=board.get("group_id", ""), actor_label=user.label)
    return {"ok": True}


@router.post("/boards/{board_id}/comments")
def add_comment(
    board_id: str,
    body: CommentCreateReq,
    request: Request,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    store = _get_store(request)
    board = store.get_board(board_id)
    if not board:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")
    _assert_board_access(board, request.app.state.db, user)
    out = store.add_comment(
        board_id=board_id,
        content=body.content,
        author_label=user.label,
        owner_id=user.owner_id,
        proposal_id=body.proposal_id,
        submission_id=body.submission_id,
        kind=body.kind,
    )
    _emit_std(request, board_id, group_id=board.get("group_id", ""), actor_label=user.label)
    return out


# ---- 4-Role Expert Committee Compilation (1-Click & 2-Stage Draft-Edit-Finalize) ----
@router.post("/boards/{board_id}/compile/stream")
async def compile_publication_stream(
    board_id: str,
    body: CompileReq,
    request: Request,
    user: AuthUser = Depends(require_user),
) -> StreamingResponse:
    store = _get_store(request)
    db: Database = request.app.state.db
    board = store.get_board(board_id)
    if not board:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")
    _assert_board_manage(board, db, user)

    def _sse(ev: str, payload: dict[str, Any]) -> str:
        return f"event: {ev}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def gen():
        try:
            async for item in stream_committee_compile(
                db=db,
                store=store,
                board=board,
                version_label=body.version_label,
                custom_directives=body.custom_directives,
                created_by=user.label,
                approval_preset_id=body.approval_preset_id,
                custom_approval_slots=body.custom_approval_slots,
                include_images=body.include_images,
            ):
                ev = item.pop("event", "stage")
                if ev == "done":
                    _emit_std(request, board_id, group_id=board.get("group_id", ""), actor_label=user.label)
                yield _sse(ev, item)
        except Exception as exc:
            yield _sse("error", {"message": str(exc)})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/boards/{board_id}/compile/draft-stream")
async def compile_draft_stream(
    board_id: str,
    body: CompileReq,
    request: Request,
    user: AuthUser = Depends(require_user),
) -> StreamingResponse:
    """Stages 1-3: generate an editable structured manuscript + real v4.0 law audit before typesetting."""
    store = _get_store(request)
    db: Database = request.app.state.db
    board = store.get_board(board_id)
    if not board:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")
    _assert_board_manage(board, db, user)

    def _sse(ev: str, payload: dict[str, Any]) -> str:
        return f"event: {ev}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def gen():
        try:
            async for item in generate_committee_draft_stream(
                db=db,
                store=store,
                board=board,
                version_label=body.version_label,
                custom_directives=body.custom_directives,
                approval_preset_id=body.approval_preset_id,
                custom_approval_slots=body.custom_approval_slots,
            ):
                ev = item.pop("event", "stage")
                yield _sse(ev, item)
        except Exception as exc:
            yield _sse("error", {"message": str(exc)})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/boards/{board_id}/compile/finalize")
async def compile_finalize_manuscript(
    board_id: str,
    body: FinalizeManuscriptReq,
    request: Request,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    """Stage 4: typeset user-reviewed/edited manuscript into A4 PDF + Word(.docx) + Hangul(.hwpx) + Diff Table."""
    store = _get_store(request)
    db: Database = request.app.state.db
    board = store.get_board(board_id)
    if not board:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")
    _assert_board_manage(board, db, user)

    pub = await typeset_manuscript_to_publication(
        db=db,
        store=store,
        board=board,
        manuscript=body.manuscript,
        law_audit=body.law_audit,
        vote_summary=body.vote_summary,
        version_label=body.version_label,
        created_by=user.label,
        approval_preset_id=body.approval_preset_id,
        custom_approval_slots=body.custom_approval_slots,
        ai_engine=body.ai_engine,
        include_images=body.include_images,
    )
    _emit_std(request, board_id, group_id=board.get("group_id", ""), actor_label=user.label)
    return {
        "ok": True,
        "publication": {k: v for k, v in pub.items() if k not in ("html_snapshot", "manuscript")},
    }


@router.get("/publications/{pub_id}/preview")
def preview_publication_html(
    pub_id: str,
    request: Request,
    user: AuthUser = Depends(require_user),
) -> HTMLResponse:
    store = _get_store(request)
    pub = store.get_publication(pub_id)
    if not pub:
        raise HTTPException(status_code=404, detail="편찬 문서를 찾을 수 없습니다.")
    board = store.get_board(pub["board_id"])
    if board:
        _assert_board_access(board, request.app.state.db, user)
    return HTMLResponse(pub.get("html_snapshot", "<p>미리보기 없음</p>"))


@router.get("/publications/{pub_id}/diff")
def get_publication_diff(
    pub_id: str,
    request: Request,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    store = _get_store(request)
    pub = store.get_publication(pub_id)
    if not pub:
        raise HTTPException(status_code=404, detail="편찬 문서를 찾을 수 없습니다.")
    board = store.get_board(pub["board_id"])
    if board:
        _assert_board_access(board, request.app.state.db, user)
    return {
        "id": pub["id"],
        "version_label": pub["version_label"],
        "title": pub["title"],
        "diff_report": pub.get("diff_report") or {},
        "manuscript": pub.get("manuscript") or {},
        "law_audit": pub.get("law_audit") or [],
    }


@router.get("/publications/{pub_id}/download/{fmt}")
def download_publication(
    pub_id: str,
    fmt: str,
    request: Request,
    user: AuthUser = Depends(require_user),
) -> FileResponse:
    store = _get_store(request)
    pub = store.get_publication(pub_id)
    if not pub:
        raise HTTPException(status_code=404, detail="편찬 문서를 찾을 수 없습니다.")
    board = store.get_board(pub["board_id"])
    if board:
        _assert_board_access(board, request.app.state.db, user)
    fmt_l = fmt.lower()
    if fmt_l == "pdf":
        p = Path(pub["pdf_path"])
        media = "application/pdf"
    elif fmt_l == "docx":
        p = Path(pub["docx_path"])
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif fmt_l == "hwpx":
        hp = (pub.get("hwpx_path") or "").strip()
        if not hp:
            raise HTTPException(status_code=404, detail="이 판본에는 한글(HWPX) 파일이 없습니다.")
        p = Path(hp)
        media = "application/hwp+zip"
    else:
        raise HTTPException(status_code=400, detail="지원 형식: pdf, docx, hwpx")
    if not p.exists():
        raise HTTPException(status_code=404, detail="생성된 파일이 존재하지 않습니다.")
    encoded = quote(p.name)
    return FileResponse(
        path=str(p),
        media_type=media,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
    )


@router.post("/publications/{pub_id}/publish-to-qa")
async def publish_to_qa_notebook(
    pub_id: str,
    body: PublishToQaReq,
    request: Request,
    user: AuthUser = Depends(require_admin),
) -> dict[str, Any]:
    """1-click promote compiled official PDF into the main '행정 Q&A' search notebook (new doc or in-place revision)."""
    store = _get_store(request)
    db: Database = request.app.state.db
    pub = store.get_publication(pub_id)
    if not pub:
        raise HTTPException(status_code=404, detail="편찬 문서를 찾을 수 없습니다.")
    pdf_path = Path(pub["pdf_path"])
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="편찬된 PDF 파일을 찾을 수 없습니다.")

    board = store.get_board(pub["board_id"])
    doc_title = body.title.strip() or f"{pub['title']} ({pub['version_label']})"
    doc_cat = body.category.strip() or (board["category"] if board else "표준 행정 규정")

    create_backup(db.db_path, reason="pre_std_publish")

    if body.replace_doc_id.strip():
        updated = await asyncio.to_thread(
            replace_document_file,
            db=db,
            doc_id=body.replace_doc_id.strip(),
            source_path=pdf_path,
            title=doc_title,
            category=doc_cat,
            priority=body.priority,
        )
        doc_rec = updated
    else:
        ingested = await asyncio.to_thread(
            ingest_file,
            db=db,
            notebook_id=body.notebook_id or DEFAULT_NOTEBOOK_ID,
            source_path=pdf_path,
            title=doc_title,
            category=doc_cat,
            priority=body.priority,
        )
        doc_rec = ingested[0]

    store.mark_publication_linked_doc(pub_id, doc_rec["id"])
    _invalidate_qa_cache_and_notify(request, doc_rec["notebook_id"], actor_label=user.label)
    if board:
        _emit_std(request, board["id"], group_id=board.get("group_id", ""), actor_label=user.label)
    db.log_audit(
        "std_published_to_qa",
        user.role,
        user.label,
        get_client_ip(request),
        f"행정Q&A 정식 편입: {doc_rec['title']} (doc_id={doc_rec['id']})",
    )
    return {"ok": True, "document": doc_rec}


@router.post("/publications/{pub_id}/register-forms")
async def register_publication_forms(
    pub_id: str,
    body: RegisterFormsReq,
    request: Request,
    user: AuthUser = Depends(require_admin),
) -> dict[str, Any]:
    """1-click push compiled standard forms directly into the right-side Forms Vault (작성·PDF·DOCX·HWPX·XLSX)."""
    store = _get_store(request)
    db: Database = request.app.state.db
    pub = store.get_publication(pub_id)
    if not pub:
        raise HTTPException(status_code=404, detail="편찬 문서를 찾을 수 없습니다.")

    try:
        res = await asyncio.to_thread(
            register_publication_forms_to_vault,
            db,
            store,
            pub,
            body.notebook_id or DEFAULT_NOTEBOOK_ID,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    _invalidate_qa_cache_and_notify(request, res["document"]["notebook_id"], actor_label=user.label)
    board = store.get_board(pub["board_id"])
    if board:
        _emit_std(request, board["id"], group_id=board.get("group_id", ""), actor_label=user.label)
    db.log_audit(
        "std_forms_registered",
        user.role,
        user.label,
        get_client_ip(request),
        f"서식 보관함 등록: {pub['title']} ({res['registered_count']}종)",
    )
    return {"ok": True, **res}
