from __future__ import annotations

import asyncio
import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from core.config import DEFAULT_NOTEBOOK_ID
from core.database import Database
from core.ingest import SUPPORTED_EXTENSIONS, ingest_file, replace_document_file
from core.std_config import load_std_config, reset_std_config, save_std_config
from core.std_engine import (
    analyze_submission_and_cross_routes,
    execute_cross_action_sync,
    extract_submission_file_text,
    generate_voting_proposals_for_board,
    rematch_deferred_memories_for_board,
)
from core.std_publisher import stream_committee_compile
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


def _get_store(request: Request) -> StandardizationStore:
    store: StandardizationStore | None = getattr(request.app.state, "std_store", None)
    if store is None:
        db: Database = request.app.state.db
        store = StandardizationStore(db_path=db.db_path)
        request.app.state.std_store = store
    return store


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
def list_boards(request: Request, _: AuthUser = Depends(require_user)) -> list[dict[str, Any]]:
    return _get_store(request).list_boards()


@router.post("/boards")
def create_board(
    body: BoardCreateReq,
    request: Request,
    user: AuthUser = Depends(require_admin),
) -> dict[str, Any]:
    store = _get_store(request)
    db: Database = request.app.state.db
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
        created_by=user.label,
    )
    # Immediately wake up any deferred cross-board memories matching this newly created board!
    matched_memories = rematch_deferred_memories_for_board(store, board)
    db.log_audit("std_board_created", user.role, user.label, get_client_ip(request), f"표준화 게시글: {board['title']}")
    return {**board, "matched_memories": matched_memories}


@router.get("/boards/{board_id}")
def get_board_detail(
    board_id: str,
    request: Request,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    store = _get_store(request)
    board = store.get_board(board_id)
    if not board:
        raise HTTPException(status_code=404, detail="모집 게시글을 찾을 수 없습니다.")
    mask_sub = bool(board.get("submission_anonymous")) and user.role != "admin"
    anon_votes = board.get("vote_visibility") == "anonymous"
    return {
        "board": board,
        "submissions": store.list_submissions(board_id, mask_anonymous=mask_sub),
        "proposals": store.list_proposals(board_id, viewer_voter_id=user.owner_id, anonymous_votes=anon_votes),
        "comments": store.list_comments(board_id, mask_anonymous=mask_sub),
        "memories": store.list_cross_memories(board_id=board_id),
        "publications": store.list_publications(board_id),
    }


@router.patch("/boards/{board_id}")
def update_board(
    board_id: str,
    body: BoardUpdateReq,
    request: Request,
    _: AuthUser = Depends(require_admin),
) -> dict[str, Any]:
    store = _get_store(request)
    updated = store.update_board(board_id, **body.model_dump(exclude_none=True))
    if not updated:
        raise HTTPException(status_code=404, detail="모집 게시글을 찾을 수 없습니다.")
    return updated


@router.delete("/boards/{board_id}")
def delete_board(
    board_id: str,
    request: Request,
    user: AuthUser = Depends(require_admin),
) -> dict[str, bool]:
    store = _get_store(request)
    ok = store.delete_board(board_id)
    if not ok:
        raise HTTPException(status_code=404, detail="모집 게시글을 찾을 수 없습니다.")
    request.app.state.db.log_audit("std_board_deleted", user.role, user.label, get_client_ip(request), f"삭제: {board_id}")
    return {"ok": True}


# ---- Submissions (Files + Pastor Field Notes) ----
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

    file_name = ""
    file_type = ""
    stored_path = ""
    extracted_text = ""

    if file is not None and file.filename:
        orig_name = Path(file.filename).name
        ext = Path(orig_name).suffix.lower()
        allowed_exts = SUPPORTED_EXTENSIONS - {".zip"}
        if ext not in allowed_exts:
            raise HTTPException(
                status_code=400,
                detail=f"지원하지 않는 파일 형식입니다({orig_name}). 지원: {', '.join(sorted(allowed_exts))}",
            )
        safe_name = re.sub(r'[\\/:*?"<>|]+', "_", orig_name)
        dest = get_std_uploads_dir(board_id) / f"{uuid.uuid4().hex[:8]}_{safe_name}"
        with dest.open("wb") as out_f:
            shutil.copyfileobj(file.file, out_f)
        file_name = orig_name
        file_type = ext.lstrip(".")
        stored_path = str(dest)
        extracted_text = await asyncio.to_thread(extract_submission_file_text, dest)

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
    )

    ai_analysis = await analyze_submission_and_cross_routes(
        db=db,
        store=store,
        board=board,
        submission=sub,
        use_ai=use_ai,
    )
    refreshed = store.get_submission(sub["id"]) or sub
    return {
        "ok": True,
        "submission": refreshed,
        "analysis": ai_analysis,
    }


@router.delete("/submissions/{sub_id}")
def delete_submission(
    sub_id: str,
    request: Request,
    user: AuthUser = Depends(require_user),
) -> dict[str, bool]:
    store = _get_store(request)
    sub = store.get_submission(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="제출 자료를 찾을 수 없습니다.")
    if user.role != "admin" and sub["owner_id"] != user.owner_id:
        raise HTTPException(status_code=403, detail="본인 제출 자료 또는 관리자만 삭제할 수 있습니다.")
    store.delete_submission(sub_id)
    if sub.get("stored_path"):
        try:
            Path(sub["stored_path"]).unlink(missing_ok=True)
        except OSError:
            pass
    return {"ok": True}


# ---- Cross-Board AI Memory & Manual Move / Copy / Merge / Undo ----
@router.get("/cross-memory")
def list_cross_memory(
    request: Request,
    board_id: str = "",
    status: str = "",
    _: AuthUser = Depends(require_user),
) -> list[dict[str, Any]]:
    return _get_store(request).list_cross_memories(board_id=board_id, status=status)


@router.post("/boards/{board_id}/scan-memory")
def scan_deferred_memory(
    board_id: str,
    request: Request,
    _: AuthUser = Depends(require_admin),
) -> dict[str, Any]:
    store = _get_store(request)
    board = store.get_board(board_id)
    if not board:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")
    matched = rematch_deferred_memories_for_board(store, board)
    return {"ok": True, "matched": matched}


@router.post("/cross-memory/{mem_id}/apply")
def apply_cross_memory(
    mem_id: str,
    body: CrossMemoryActionReq,
    request: Request,
    user: AuthUser = Depends(require_admin),
) -> dict[str, Any]:
    store = _get_store(request)
    mem = store.get_cross_memory(mem_id)
    if not mem:
        raise HTTPException(status_code=404, detail="교차 분류 기억 항목을 찾을 수 없습니다.")
    target_id = body.target_board_id.strip() or mem["target_board_id"]
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
    request.app.state.db.log_audit(
        "std_cross_action",
        user.role,
        user.label,
        get_client_ip(request),
        f"{body.action}: {mem['submission_title']} -> {target_id}",
    )
    return {"ok": True, "result": res, "memory": store.get_cross_memory(mem_id)}


@router.post("/submissions/batch-action")
def batch_submission_action(
    body: BatchSubmissionActionReq,
    request: Request,
    user: AuthUser = Depends(require_admin),
) -> dict[str, Any]:
    store = _get_store(request)
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
    request.app.state.db.log_audit(
        "std_manual_batch",
        user.role,
        user.label,
        get_client_ip(request),
        f"수동 {body.action} ({len(body.submission_ids)}건) -> {body.target_board_id}",
    )
    return {"ok": True, "result": res}


# ---- Proposals, Voting & Improvement Comments ----
@router.post("/boards/{board_id}/generate-proposals")
async def generate_proposals(
    board_id: str,
    request: Request,
    use_ai: bool = True,
    _: AuthUser = Depends(require_admin),
) -> dict[str, Any]:
    store = _get_store(request)
    board = store.get_board(board_id)
    if not board:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")
    created = await generate_voting_proposals_for_board(request.app.state.db, store, board, use_ai=use_ai)
    return {"ok": True, "created": created, "count": len(created)}


@router.post("/boards/{board_id}/proposals")
def create_proposal_manual(
    board_id: str,
    body: ProposalCreateReq,
    request: Request,
    _: AuthUser = Depends(require_admin),
) -> dict[str, Any]:
    store = _get_store(request)
    if not store.get_board(board_id):
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")
    return store.create_proposal(
        board_id=board_id,
        cluster_title=body.cluster_title,
        category_tag=body.category_tag,
        summary=body.summary,
        options=body.options,
    )


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
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "proposal": updated}


@router.patch("/proposals/{proposal_id}")
def update_proposal(
    proposal_id: str,
    body: ProposalUpdateReq,
    request: Request,
    _: AuthUser = Depends(require_admin),
) -> dict[str, Any]:
    updated = _get_store(request).update_proposal(
        proposal_id, status=body.status, winning_option_id=body.winning_option_id
    )
    if not updated:
        raise HTTPException(status_code=404, detail="투표 안건을 찾을 수 없습니다.")
    return updated


@router.delete("/proposals/{proposal_id}")
def delete_proposal(
    proposal_id: str,
    request: Request,
    _: AuthUser = Depends(require_admin),
) -> dict[str, bool]:
    ok = _get_store(request).delete_proposal(proposal_id)
    if not ok:
        raise HTTPException(status_code=404, detail="투표 안건을 찾을 수 없습니다.")
    return {"ok": True}


@router.post("/boards/{board_id}/comments")
def add_comment(
    board_id: str,
    body: CommentCreateReq,
    request: Request,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    store = _get_store(request)
    if not store.get_board(board_id):
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")
    return store.add_comment(
        board_id=board_id,
        content=body.content,
        author_label=user.label,
        owner_id=user.owner_id,
        proposal_id=body.proposal_id,
        submission_id=body.submission_id,
        kind=body.kind,
    )


# ---- 4-Role Expert Committee PDF Compilation & 1-Click Publish into Q&A ----
@router.post("/boards/{board_id}/compile/stream")
async def compile_publication_stream(
    board_id: str,
    body: CompileReq,
    request: Request,
    user: AuthUser = Depends(require_admin),
) -> StreamingResponse:
    store = _get_store(request)
    db: Database = request.app.state.db
    board = store.get_board(board_id)
    if not board:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")

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


@router.get("/publications/{pub_id}/preview")
def preview_publication_html(
    pub_id: str,
    request: Request,
    _: AuthUser = Depends(require_user),
) -> HTMLResponse:
    pub = _get_store(request).get_publication(pub_id)
    if not pub:
        raise HTTPException(status_code=404, detail="편찬 문서를 찾을 수 없습니다.")
    return HTMLResponse(pub.get("html_snapshot", "<p>미리보기 없음</p>"))


@router.get("/publications/{pub_id}/download/{fmt}")
def download_publication(
    pub_id: str,
    fmt: str,
    request: Request,
    _: AuthUser = Depends(require_user),
) -> FileResponse:
    pub = _get_store(request).get_publication(pub_id)
    if not pub:
        raise HTTPException(status_code=404, detail="편찬 문서를 찾을 수 없습니다.")
    fmt_l = fmt.lower()
    if fmt_l == "pdf":
        p = Path(pub["pdf_path"])
        media = "application/pdf"
    elif fmt_l == "docx":
        p = Path(pub["docx_path"])
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        raise HTTPException(status_code=400, detail="지원 형식: pdf, docx")
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
    db.log_audit(
        "std_published_to_qa",
        user.role,
        user.label,
        get_client_ip(request),
        f"행정Q&A 정식 편입: {doc_rec['title']} (doc_id={doc_rec['id']})",
    )
    return {"ok": True, "document": doc_rec}
