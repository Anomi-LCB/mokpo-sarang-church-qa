from __future__ import annotations

import asyncio
import gzip
import json
import os
import re
import shutil
import tempfile
import urllib.request
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from core.config import (
    APP_NAME,
    APP_VERSION,
    DEFAULT_NOTEBOOK_ID,
    DEFAULT_PORT,
    get_base_dir,
    get_downloads_dir,
    get_exports_dir,
    get_resource_dir,
)
from core.database import Database
from core.forms import export_editable_docx, export_original_pdf, export_table_xlsx, render_pdf_page_png
from core.ingest import SUPPORTED_EXTENSIONS, ingest_file, replace_document_file
from core.report import export_qa_report_docx
from core.retriever import format_instant_search_answer, retrieve
from core.verifier import build_double_verify_prompt, verify_citations
from server.auth import AuthUser, PinAuthManager, get_client_ip, require_admin, require_user
from server.backup import create_backup, ensure_daily_backup, get_backup_path, list_backups, restore_backup
from server.cli_providers import (
    NO_EVIDENCE_MESSAGE,
    build_grounded_prompt,
    detect_cli_providers,
    generate_autofill_structure,
    get_api_providers_status,
    import_initial_ai_config,
    load_ai_config,
    save_ai_api_key,
    stream_cli_with_failover,
    test_ai_connection,
)
from server.discovery import DiscoveryResponder
from server.queue_manager import QueryQueueManager
from server.std_routes import router as std_router
from server.tunnel import NetworkTunnelManager
from server.updater import UpdateManager, get_local_releases_dir, get_updates_dir
from core.std_store import StandardizationStore


class LoginReq(BaseModel):
    pin: str = Field(..., min_length=1, max_length=64)
    label: str = Field(default="", max_length=40)
    client_id: str = Field(default="", max_length=48)


class PinUpdateReq(BaseModel):
    member_pin: str | None = None
    admin_pin: str | None = None
    revoke_existing: bool = True


class NotebookCreateReq(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    description: str = Field(default="", max_length=300)
    system_rules: str = Field(default="", max_length=4000)


class NotebookUpdateReq(BaseModel):
    name: str | None = None
    description: str | None = None
    system_rules: str | None = None


class ChatStreamReq(BaseModel):
    notebook_id: str = DEFAULT_NOTEBOOK_ID
    session_id: str | None = None
    query: str = Field(..., min_length=1, max_length=3000)
    doc_ids: list[str] | None = None
    mode: str = Field(default="auto")  # auto | practical | strict | advisory
    instant: bool = False
    double_verify: bool = False
    provider: str | None = None


class AutofillReq(BaseModel):
    instruction: str = Field(default="", max_length=3000)
    use_cli: bool = True
    profile: dict[str, str] | None = None


class FormRenderDocxReq(BaseModel):
    document_title: str = Field(..., min_length=1, max_length=160)
    fields: list[dict[str, str]] = Field(default_factory=list)
    body_paragraphs: list[str] = Field(default_factory=list)
    date_line: str = Field(default="", max_length=120)
    signer_line: str = Field(default="", max_length=160)
    recipient_line: str = Field(default="", max_length=160)


class FeedbackCreateReq(BaseModel):
    category: str = Field(default="bug")  # bug | ux | feature | doc
    title: str = Field(..., min_length=2, max_length=160)
    description: str = Field(..., min_length=4, max_length=5000)
    device_info: str = Field(default="", max_length=300)
    context_info: str = Field(default="", max_length=500)


class FeedbackUpdateReq(BaseModel):
    status: str | None = None  # open | reviewing | resolved
    creator_note: str | None = Field(default=None, max_length=2000)


class CreatorSettingsReq(BaseModel):
    new_creator_pin: str | None = None
    creator_relay_url: str | None = None
    creator_relay_token_out: str | None = None


class CliSettingsReq(BaseModel):
    connection_mode: str = "auto"  # auto | cli | api
    provider: str = "claude"
    model: str = ""
    api_provider: str = "anthropic"
    api_model: str = ""
    api_base_url: str = ""
    api_key: str | None = None
    clear_api_key: bool = False
    max_concurrent: int = 2
    custom_public_url: str = ""
    cli_failover_enabled: bool = True
    default_double_verify: bool = False
    default_chat_shared: bool = False
    audit_log_enabled: bool = True


class AiConnectionTestReq(BaseModel):
    mode: str = "api"  # api | cli
    provider: str = "anthropic"
    api_key: str | None = None
    model: str | None = None
    base_url: str | None = None


class UpdateSettingsReq(BaseModel):
    channel: str | None = None  # github | custom
    github_repo: str | None = None
    custom_url: str | None = None
    auto_check: bool | None = None
    skipped_version: str | None = None


class UpdateSkipReq(BaseModel):
    version: str = Field(..., min_length=1, max_length=40)


class TunnelActionReq(BaseModel):
    kind: str = "tailscale"
    token: str = ""


class SessionUpdateReq(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=80)
    is_shared: bool | None = None


class DocumentMetaUpdateReq(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    category: str | None = Field(default=None, min_length=1, max_length=40)
    priority: int | None = Field(default=None, ge=0, le=100)


class ReportExportReq(BaseModel):
    notebook_name: str = "목포사랑의교회 법규·행정"
    question: str = Field(..., min_length=1, max_length=3000)
    answer: str = Field(..., min_length=1, max_length=30000)
    mode: str = "practical"
    citations: list[dict[str, Any]] = Field(default_factory=list)
    verification: dict[str, Any] | None = None


def _find_apk_path() -> Path | None:
    candidates = [
        get_downloads_dir() / "목포사랑의교회-행정Q&A.apk",
        get_downloads_dir() / "church-search.apk",
        get_base_dir() / "dist" / "목포사랑의교회-행정Q&A.apk",
        get_base_dir() / "dist" / "church-search.apk",
        get_resource_dir() / "dist" / "목포사랑의교회-행정Q&A.apk",
        get_resource_dir() / "dist" / "church-search.apk",
    ]
    for p in candidates:
        if p.exists() and p.stat().st_size > 1024:
            return p
    return None


def _find_frontend_dist() -> Path | None:
    candidates = [
        get_resource_dir() / "frontend" / "dist",
        get_base_dir() / "frontend" / "dist",
    ]
    for p in candidates:
        if (p / "index.html").exists():
            return p
    return None


def create_app(db_path: Path | None = None, port: int | None = None, on_shutdown: Any = None) -> FastAPI:
    active_port = port or int(os.environ.get("CHURCH_SEARCH_PORT", str(DEFAULT_PORT)))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = Database(db_path=db_path)
        db.ensure_default_notebook()
        import_initial_ai_config(db, db.db_path.parent)
        ensure_daily_backup(db.db_path)
        auth = PinAuthManager(db)
        max_c = int(db.get_setting("max_concurrent_cli", "2") or "2")
        queue_mgr = QueryQueueManager(max_concurrent=max_c)
        tunnel_mgr = NetworkTunnelManager(port=active_port)
        updater = UpdateManager(port=active_port, on_shutdown=on_shutdown)

        def _discovery_info() -> dict[str, str]:
            custom_url = db.get_setting("custom_public_url", "") or ""
            summary = tunnel_mgr.get_network_summary(custom_public_url=custom_url, apk_available=False)
            return {
                "lan_url": str(summary.get("lan_url", "")),
                "primary_external_url": str(summary.get("primary_external_url", "")),
            }

        discovery = DiscoveryResponder(port=active_port, info_provider=_discovery_info)
        discovery.start()

        app.state.db = db
        app.state.std_store = StandardizationStore(db_path=db.db_path)
        app.state.auth = auth
        app.state.queue = queue_mgr
        app.state.tunnel = tunnel_mgr
        app.state.updater = updater
        app.state.discovery = discovery
        app.state.jobs = {}
        try:
            yield
        finally:
            discovery.stop()
            tunnel_mgr.stop_cloudflare_tunnel()

    app = FastAPI(title=APP_NAME, lifespan=lifespan)
    app.include_router(std_router)

    # Hardened CORS: reflect local/LAN/Tailscale/HTTPS origins safely instead of wildcard "*" with credentials
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|100\.\d+\.\d+\.\d+|[^/]+\.(ts\.net|trycloudflare\.com))(:\d+)?$",
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Admin-Pin", "X-Creator-Pin", "X-Creator-Token"],
    )

    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        return response

    # ---- Health ----
    @app.get("/api/health")
    def health(request: Request) -> dict[str, Any]:
        db: Database = request.app.state.db
        q: QueryQueueManager = request.app.state.queue
        return {
            "status": "ok",
            "app": APP_NAME,
            "version": APP_VERSION,
            "notebooks": len(db.list_notebooks()),
            "queue": q.status(),
        }

    # ---- Auth & Short-lived File Tickets ----
    @app.post("/api/auth/login")
    def login(body: LoginReq, request: Request, response: Response) -> dict[str, Any]:
        auth: PinAuthManager = request.app.state.auth
        ip = get_client_ip(request)
        user = auth.authenticate_pin(body.pin, client_ip=ip, label=body.label, client_id=body.client_id)
        token = auth.issue_token(user)
        is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        auth.set_cookie(response, token, is_https=is_https)
        return {
            "ok": True,
            "role": user.role,
            "label": user.label,
            "owner_id": user.owner_id,
            "is_default_pin": auth.is_using_default_pins() if user.role == "admin" else False,
            "token": token,
        }

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response) -> dict[str, bool]:
        auth: PinAuthManager = request.app.state.auth
        auth.clear_cookie(response)
        return {"ok": True}

    @app.get("/api/auth/me")
    def auth_me(request: Request) -> dict[str, Any]:
        auth: PinAuthManager = request.app.state.auth
        db: Database = request.app.state.db
        user = auth.get_user_from_request(request)
        if not user:
            return {"authenticated": False}
        return {
            "authenticated": True,
            "role": user.role,
            "label": user.label,
            "owner_id": user.owner_id,
            "is_default_pin": auth.is_using_default_pins() if user.role == "admin" else False,
            "default_double_verify": db.get_setting("default_double_verify", "0") == "1",
        }

    @app.post("/api/auth/ticket")
    def issue_ticket(request: Request, user: AuthUser = Depends(require_user)) -> dict[str, Any]:
        auth: PinAuthManager = request.app.state.auth
        return {"ticket": auth.issue_file_ticket(user), "expires_in": 120}

    @app.put("/api/admin/pins")
    def update_pins(
        body: PinUpdateReq,
        request: Request,
        response: Response,
        user: AuthUser = Depends(require_admin),
    ) -> dict[str, Any]:
        auth: PinAuthManager = request.app.state.auth
        db: Database = request.app.state.db
        auth.update_pins(
            member_pin=body.member_pin,
            admin_pin=body.admin_pin,
            revoke_existing=body.revoke_existing,
        )
        db.log_audit("pin_updated", user.role, user.label, get_client_ip(request), "PIN/비밀번호 변경 및 기존 세션 정리")
        # Re-issue fresh session token for the current admin so they stay signed in seamlessly
        fresh = auth.issue_token(user)
        is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        auth.set_cookie(response, fresh, is_https=is_https)
        return {"ok": True, "token": fresh, "is_default_pin": auth.is_using_default_pins()}

    @app.post("/api/admin/revoke-sessions")
    def revoke_sessions(
        request: Request,
        response: Response,
        user: AuthUser = Depends(require_admin),
    ) -> dict[str, Any]:
        auth: PinAuthManager = request.app.state.auth
        db: Database = request.app.state.db
        ver = auth.revoke_all_sessions()
        db.log_audit("sessions_revoked", user.role, user.label, get_client_ip(request), f"전체 기기 로그아웃 (v{ver})")
        fresh = auth.issue_token(user)
        is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        auth.set_cookie(response, fresh, is_https=is_https)
        return {"ok": True, "token": fresh, "token_version": ver}

    # ---- Notebooks ----
    @app.get("/api/notebooks")
    def list_notebooks(request: Request, _: AuthUser = Depends(require_user)) -> list[dict[str, Any]]:
        return request.app.state.db.list_notebooks()

    @app.post("/api/notebooks")
    def create_notebook(
        body: NotebookCreateReq,
        request: Request,
        user: AuthUser = Depends(require_admin),
    ) -> dict[str, Any]:
        db: Database = request.app.state.db
        slug = re.sub(r"[^a-z0-9가-힣]+", "-", body.name.lower()).strip("-")[:24]
        nb_id = f"nb-{slug or 'custom'}-{uuid.uuid4().hex[:6]}"
        nb = db.create_notebook(
            notebook_id=nb_id,
            name=body.name.strip(),
            description=body.description.strip(),
            system_rules=body.system_rules.strip(),
        )
        db.log_audit("notebook_created", user.role, user.label, get_client_ip(request), f"노트북 생성: {nb['name']}")
        return nb

    @app.put("/api/notebooks/{notebook_id}")
    def update_notebook(
        notebook_id: str,
        body: NotebookUpdateReq,
        request: Request,
        user: AuthUser = Depends(require_admin),
    ) -> dict[str, Any]:
        db: Database = request.app.state.db
        nb = db.update_notebook(
            notebook_id=notebook_id,
            name=body.name,
            description=body.description,
            system_rules=body.system_rules,
        )
        if not nb:
            raise HTTPException(status_code=404, detail="노트북을 찾을 수 없습니다.")
        db.log_audit("notebook_updated", user.role, user.label, get_client_ip(request), f"노트북 규칙 수정: {nb['name']}")
        return nb

    @app.delete("/api/notebooks/{notebook_id}")
    def delete_notebook(
        notebook_id: str,
        request: Request,
        user: AuthUser = Depends(require_admin),
    ) -> dict[str, bool]:
        if notebook_id == DEFAULT_NOTEBOOK_ID:
            raise HTTPException(status_code=400, detail="기본 목포사랑의교회 노트북은 삭제할 수 없습니다.")
        auth: PinAuthManager = request.app.state.auth
        auth.verify_admin_pin(request.headers.get("X-Admin-Pin"), get_client_ip(request), user.label)
        db: Database = request.app.state.db
        create_backup(db.db_path, reason="pre_del_nb")
        ok = db.delete_notebook(notebook_id)
        if not ok:
            raise HTTPException(status_code=404, detail="노트북을 찾을 수 없습니다.")
        db.log_audit("notebook_deleted", user.role, user.label, get_client_ip(request), f"노트북 삭제: {notebook_id}")
        return {"ok": True}

    # ---- Documents ----
    @app.get("/api/notebooks/{notebook_id}/documents")
    def list_documents(notebook_id: str, request: Request, _: AuthUser = Depends(require_user)) -> list[dict[str, Any]]:
        return request.app.state.db.list_documents(notebook_id)

    @app.get("/api/notebooks/{notebook_id}/offline-bundle")
    def get_offline_bundle(notebook_id: str, request: Request, _: AuthUser = Depends(require_user)) -> Response:
        db: Database = request.app.state.db
        bundle = db.export_offline_bundle(notebook_id)
        if not bundle:
            raise HTTPException(status_code=404, detail="노트북을 찾을 수 없습니다.")
        raw = json.dumps(bundle, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        accept_enc = (request.headers.get("accept-encoding") or "").lower()
        if "gzip" in accept_enc:
            gz = gzip.compress(raw, compresslevel=6)
            return Response(
                content=gz,
                media_type="application/json; charset=utf-8",
                headers={
                    "Content-Encoding": "gzip",
                    "Cache-Control": "private, max-age=60",
                    "Vary": "Accept-Encoding",
                },
            )
        return Response(
            content=raw,
            media_type="application/json; charset=utf-8",
            headers={"Cache-Control": "private, max-age=60"},
        )

    @app.post("/api/notebooks/{notebook_id}/documents/upload")
    async def upload_documents(
        notebook_id: str,
        request: Request,
        files: list[UploadFile] = File(...),
        category: str = Form("일반 자료"),
        priority: int = Form(50),
        user: AuthUser = Depends(require_admin),
    ) -> dict[str, Any]:
        db: Database = request.app.state.db
        if not db.get_notebook(notebook_id):
            raise HTTPException(status_code=404, detail="노트북을 찾을 수 없습니다.")

        job_id = "job_" + uuid.uuid4().hex[:10]
        tmp_dir = Path(tempfile.mkdtemp(prefix="church_up_"))
        saved_paths: list[tuple[Path, str]] = []
        for uf in files:
            orig_name = Path(uf.filename or "document.pdf").name
            ext = Path(orig_name).suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                raise HTTPException(
                    status_code=400,
                    detail=f"지원하지 않는 파일 형식입니다({orig_name}). 지원: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
                )
            dest = tmp_dir / orig_name
            with dest.open("wb") as out_f:
                shutil.copyfileobj(uf.file, out_f)
            saved_paths.append((dest, orig_name))

        db.log_audit(
            "doc_upload",
            user.role,
            user.label,
            get_client_ip(request),
            f"파일 업로드 ({len(saved_paths)}건): {', '.join(n for _, n in saved_paths[:3])}",
        )

        job_state: dict[str, Any] = {
            "id": job_id,
            "status": "running",
            "progress": 0,
            "message": f"{len(saved_paths)}개 파일 분석 준비 중...",
            "documents": [],
            "error": "",
        }
        request.app.state.jobs[job_id] = job_state

        def _worker() -> None:
            try:
                all_docs: list[dict[str, Any]] = []
                total_files = len(saved_paths)
                for idx, (path, name) in enumerate(saved_paths):
                    base_pct = int((idx / total_files) * 100)
                    job_state["progress"] = base_pct
                    job_state["message"] = f"[{idx + 1}/{total_files}] {name} 파싱 및 색인 중..."

                    def _cb(done: int, total: int, msg: str) -> None:
                        inner_pct = int((done / max(1, total)) * (100 / total_files))
                        job_state["progress"] = min(99, base_pct + inner_pct)
                        job_state["message"] = f"[{idx + 1}/{total_files}] {name}: {msg}"

                    ingested = ingest_file(
                        db=db,
                        notebook_id=notebook_id,
                        source_path=path,
                        category=category,
                        priority=priority,
                        progress_cb=_cb,
                    )
                    all_docs.extend(ingested)
                job_state["documents"] = all_docs
                job_state["progress"] = 100
                job_state["status"] = "done"
                job_state["message"] = f"총 {len(all_docs)}개 문서 색인 완료"
            except Exception as exc:
                job_state["status"] = "error"
                job_state["error"] = str(exc)
                job_state["message"] = f"오류 발생: {exc}"
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

        asyncio.get_running_loop().run_in_executor(None, _worker)
        return {"job_id": job_id, "status": "running"}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str, request: Request, _: AuthUser = Depends(require_user)) -> dict[str, Any]:
        job = request.app.state.jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")
        return job

    @app.put("/api/documents/{doc_id}")
    def update_document_meta(
        doc_id: str,
        body: DocumentMetaUpdateReq,
        request: Request,
        user: AuthUser = Depends(require_admin),
    ) -> dict[str, Any]:
        db: Database = request.app.state.db
        doc = db.get_document(doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
        updated = dict(doc)
        if body.title is not None:
            updated["title"] = body.title.strip()
        if body.category is not None:
            updated["category"] = body.category.strip()
        if body.priority is not None:
            updated["priority"] = body.priority
        db.upsert_document(updated)
        db.log_audit("doc_updated", user.role, user.label, get_client_ip(request), f"문서 정보 수정: {updated['title']}")
        return updated

    @app.post("/api/documents/{doc_id}/replace")
    async def replace_document(
        doc_id: str,
        request: Request,
        file: UploadFile = File(...),
        title: str = Form(""),
        category: str = Form(""),
        priority: int | None = Form(None),
        user: AuthUser = Depends(require_admin),
    ) -> dict[str, Any]:
        db: Database = request.app.state.db
        existing = db.get_document(doc_id)
        if not existing:
            raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")

        orig_name = Path(file.filename or "document.pdf").name
        ext = Path(orig_name).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"지원하지 않는 파일 형식입니다({orig_name}). 지원: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
            )

        create_backup(db.db_path, reason="pre_update_doc")
        job_id = "job_" + uuid.uuid4().hex[:10]
        tmp_dir = Path(tempfile.mkdtemp(prefix="church_rep_"))
        dest = tmp_dir / orig_name
        with dest.open("wb") as out_f:
            shutil.copyfileobj(file.file, out_f)

        db.log_audit(
            "doc_replaced",
            user.role,
            user.label,
            get_client_ip(request),
            f"문서 파일 교체: {existing['title']} <- {orig_name}",
        )

        job_state: dict[str, Any] = {
            "id": job_id,
            "status": "running",
            "progress": 5,
            "message": f"{orig_name} 업데이트 준비 중...",
            "documents": [],
            "error": "",
        }
        request.app.state.jobs[job_id] = job_state

        def _worker() -> None:
            try:
                def _cb(done: int, total: int, msg: str) -> None:
                    job_state["progress"] = min(98, max(8, int((done / max(1, total)) * 95)))
                    job_state["message"] = f"{orig_name}: {msg}"

                updated_doc = replace_document_file(
                    db=db,
                    doc_id=doc_id,
                    source_path=dest,
                    title=title.strip() or None,
                    category=category.strip() or None,
                    priority=priority,
                    progress_cb=_cb,
                )
                job_state["documents"] = [updated_doc]
                job_state["progress"] = 100
                job_state["status"] = "done"
                job_state["message"] = f"{updated_doc['title']} 업데이트 완료"
            except Exception as exc:
                job_state["status"] = "error"
                job_state["error"] = str(exc)
                job_state["message"] = f"업데이트 오류: {exc}"
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

        asyncio.get_running_loop().run_in_executor(None, _worker)
        return {"job_id": job_id, "status": "running"}

    @app.delete("/api/documents/{doc_id}")
    def delete_document(
        doc_id: str,
        request: Request,
        user: AuthUser = Depends(require_admin),
    ) -> dict[str, bool]:
        auth: PinAuthManager = request.app.state.auth
        auth.verify_admin_pin(request.headers.get("X-Admin-Pin"), get_client_ip(request), user.label)
        db: Database = request.app.state.db
        doc = db.get_document(doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
        create_backup(db.db_path, reason="pre_del_doc")
        db.delete_document(doc_id)
        db.log_audit("doc_deleted", user.role, user.label, get_client_ip(request), f"문서 삭제: {doc['title']}")
        try:
            Path(doc["stored_path"]).unlink(missing_ok=True)
        except OSError:
            pass
        return {"ok": True}

    @app.get("/api/documents/{doc_id}/page/{page_no}.png")
    def get_document_page_image(
        doc_id: str,
        page_no: int,
        request: Request,
        dpi: int = 160,
        _: AuthUser = Depends(require_user),
    ) -> Response:
        db: Database = request.app.state.db
        doc = db.get_document(doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
        pdf_path = Path(doc["stored_path"])
        if pdf_path.suffix.lower() != ".pdf" or not pdf_path.exists():
            raise HTTPException(status_code=400, detail="PDF 문서만 페이지 이미지 미리보기를 지원합니다.")
        png = render_pdf_page_png(pdf_path, page_no=page_no, dpi=min(240, max(90, dpi)))
        return Response(content=png, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})

    @app.get("/api/documents/{doc_id}/page/{page_no}/text")
    def get_document_page_text(
        doc_id: str,
        page_no: int,
        request: Request,
        _: AuthUser = Depends(require_user),
    ) -> dict[str, Any]:
        db: Database = request.app.state.db
        page = db.get_page_text(doc_id, page_no)
        doc = db.get_document(doc_id)
        if not page or not doc:
            raise HTTPException(status_code=404, detail="페이지를 찾을 수 없습니다.")
        return {
            "doc_id": doc_id,
            "doc_title": doc["title"],
            "file_type": doc["file_type"],
            "page_count": doc["page_count"],
            "page_no": page_no,
            "is_ocr": bool(page["is_ocr"]),
            "text": page["text"],
        }

    # ---- Forms & Tables Vault + AI Autofill ----
    @app.get("/api/notebooks/{notebook_id}/forms")
    def list_forms(
        notebook_id: str,
        request: Request,
        q: str = "",
        _: AuthUser = Depends(require_user),
    ) -> list[dict[str, Any]]:
        return request.app.state.db.list_forms(notebook_id, query=q)

    @app.get("/api/forms/{form_id}/download/{fmt}")
    def download_form(
        form_id: str,
        fmt: str,
        request: Request,
        _: AuthUser = Depends(require_user),
    ) -> FileResponse:
        db: Database = request.app.state.db
        form = db.get_form(form_id)
        if not form:
            raise HTTPException(status_code=404, detail="서식을 찾을 수 없습니다.")
        fmt_low = fmt.lower()
        if fmt_low == "pdf":
            out = export_original_pdf(form)
            media = "application/pdf"
        elif fmt_low == "docx":
            out = export_editable_docx(form)
            media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        elif fmt_low == "xlsx":
            out = export_table_xlsx(form)
            media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            raise HTTPException(status_code=400, detail="지원 형식: pdf, docx, xlsx")
        encoded = quote(out.name)
        return FileResponse(
            path=str(out),
            media_type=media,
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
        )

    @app.post("/api/forms/{form_id}/autofill")
    async def autofill_form(
        form_id: str,
        body: AutofillReq,
        request: Request,
        _: AuthUser = Depends(require_user),
    ) -> dict[str, Any]:
        db: Database = request.app.state.db
        q_mgr: QueryQueueManager = request.app.state.queue
        form = db.get_form(form_id)
        if not form:
            raise HTTPException(status_code=404, detail="서식을 찾을 수 없습니다.")

        ai_cfg = load_ai_config(db)
        provider_id = ai_cfg.cli_provider
        failover_enabled = ai_cfg.failover_enabled
        ticket = "af_" + uuid.uuid4().hex[:8]
        acquired = False
        try:
            if body.use_cli:
                async for st in q_mgr.wait_turn(ticket):
                    if st["stage"] == "acquired":
                        acquired = True
            structured = await generate_autofill_structure(
                provider_id=provider_id,
                form=form,
                user_instruction=body.instruction,
                use_cli=body.use_cli,
                failover_enabled=failover_enabled,
                profile=body.profile,
                ai_config=ai_cfg,
            )
            out_docx = export_editable_docx(form, filled_data=structured)
            return {
                "ok": True,
                "filename": out_docx.name,
                "download_url": f"/api/exports/autofill/{quote(out_docx.name)}",
                "structured": structured,
            }
        finally:
            if acquired:
                await q_mgr.release()

    @app.post("/api/forms/{form_id}/render-docx")
    def render_edited_form_docx(
        form_id: str,
        body: FormRenderDocxReq,
        request: Request,
        _: AuthUser = Depends(require_user),
    ) -> dict[str, Any]:
        """Instant 100% offline DOCX rendering directly from the user's live edited A4 preview."""
        db: Database = request.app.state.db
        form = db.get_form(form_id)
        if not form:
            raise HTTPException(status_code=404, detail="서식을 찾을 수 없습니다.")
        structured = {
            "document_title": body.document_title,
            "fields": body.fields,
            "body_paragraphs": body.body_paragraphs,
            "date_line": body.date_line,
            "signer_line": body.signer_line,
            "recipient_line": body.recipient_line,
        }
        out_docx = export_editable_docx(form, filled_data=structured)
        return {
            "ok": True,
            "filename": out_docx.name,
            "download_url": f"/api/exports/autofill/{quote(out_docx.name)}",
        }

    @app.get("/api/exports/autofill/{filename}")
    def download_autofill_file(
        filename: str,
        request: Request,
        _: AuthUser = Depends(require_user),
    ) -> FileResponse:
        safe_name = Path(filename).name
        target = get_exports_dir() / "autofill" / safe_name
        if not target.exists():
            raise HTTPException(status_code=404, detail="생성된 파일을 찾을 수 없습니다.")
        encoded = quote(safe_name)
        return FileResponse(
            path=str(target),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
        )

    # ---- 1-Click Executive Meeting Report Export (.docx) ----
    @app.post("/api/reports/export-docx")
    def export_report(
        body: ReportExportReq,
        request: Request,
        user: AuthUser = Depends(require_user),
    ) -> dict[str, Any]:
        out = export_qa_report_docx(
            notebook_name=body.notebook_name,
            question=body.question,
            answer=body.answer,
            mode=body.mode,
            citations=body.citations,
            verification=body.verification,
            author_label=user.label,
        )
        return {
            "ok": True,
            "filename": out.name,
            "download_url": f"/api/exports/reports/{quote(out.name)}",
        }

    @app.get("/api/exports/reports/{filename}")
    def download_report_file(
        filename: str,
        request: Request,
        _: AuthUser = Depends(require_user),
    ) -> FileResponse:
        safe_name = Path(filename).name
        target = get_exports_dir() / "reports" / safe_name
        if not target.exists():
            raise HTTPException(status_code=404, detail="보고서 파일을 찾을 수 없습니다.")
        encoded = quote(safe_name)
        return FileResponse(
            path=str(target),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
        )

    # ---- Chat Sessions (Private + Team-Shared) & Streaming Grounded QA ----
    def _can_access_session(sess: dict[str, Any], user: AuthUser) -> bool:
        if user.role == "admin":
            return bool(sess.get("is_shared")) or sess.get("owner_id", "") in ("", user.owner_id)
        return bool(sess.get("is_shared")) or sess.get("owner_id", "") == user.owner_id

    def _can_modify_session(sess: dict[str, Any], user: AuthUser) -> bool:
        if user.role == "admin":
            return True
        return sess.get("owner_id", "") == user.owner_id

    @app.get("/api/notebooks/{notebook_id}/sessions")
    def list_sessions(
        notebook_id: str,
        request: Request,
        user: AuthUser = Depends(require_user),
    ) -> list[dict[str, Any]]:
        return request.app.state.db.list_sessions(
            notebook_id,
            owner_id=user.owner_id,
            is_admin=(user.role == "admin"),
        )

    @app.get("/api/sessions/{session_id}/messages")
    def get_messages(
        session_id: str,
        request: Request,
        user: AuthUser = Depends(require_user),
    ) -> list[dict[str, Any]]:
        db: Database = request.app.state.db
        sess = db.get_session(session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="대화 기록을 찾을 수 없습니다.")
        if not _can_access_session(sess, user):
            raise HTTPException(status_code=403, detail="비공개 대화에 접근할 권한이 없습니다.")
        return db.get_session_messages(session_id)

    @app.patch("/api/sessions/{session_id}")
    def update_session_route(
        session_id: str,
        body: SessionUpdateReq,
        request: Request,
        user: AuthUser = Depends(require_user),
    ) -> dict[str, Any]:
        db: Database = request.app.state.db
        sess = db.get_session(session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="대화 기록을 찾을 수 없습니다.")
        if not _can_modify_session(sess, user):
            raise HTTPException(status_code=403, detail="본인 대화 또는 관리자만 수정할 수 있습니다.")
        updated = db.update_session(session_id, title=body.title, is_shared=body.is_shared)
        if not updated:
            raise HTTPException(status_code=404, detail="대화 기록을 찾을 수 없습니다.")
        return updated

    @app.delete("/api/sessions/{session_id}")
    def delete_session(
        session_id: str,
        request: Request,
        user: AuthUser = Depends(require_user),
    ) -> dict[str, bool]:
        db: Database = request.app.state.db
        sess = db.get_session(session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="대화 기록을 찾을 수 없습니다.")
        if not _can_modify_session(sess, user):
            raise HTTPException(status_code=403, detail="본인 대화 또는 관리자만 삭제할 수 있습니다.")
        db.delete_session(session_id)
        return {"ok": True}

    @app.post("/api/chat/stream")
    async def chat_stream(
        body: ChatStreamReq,
        request: Request,
        user: AuthUser = Depends(require_user),
    ) -> StreamingResponse:
        db: Database = request.app.state.db
        q_mgr: QueryQueueManager = request.app.state.queue
        nb = db.get_notebook(body.notebook_id)
        if not nb:
            raise HTTPException(status_code=404, detail="노트북을 찾을 수 없습니다.")

        default_shared = db.get_setting("default_chat_shared", "0") == "1"
        session_id = body.session_id or ("sess_" + uuid.uuid4().hex[:10])
        existing_sess = db.get_session(session_id)
        if existing_sess and not _can_access_session(existing_sess, user):
            session_id = "sess_" + uuid.uuid4().hex[:10]
        db.create_session(
            session_id,
            body.notebook_id,
            user_label=user.label,
            title=body.query[:36],
            owner_id=user.owner_id,
            is_shared=default_shared,
        )
        history = db.get_session_messages(session_id)
        effective_mode = "instant" if body.instant else body.mode
        db.add_message(session_id, "user", body.query, mode=effective_mode)

        ai_cfg = load_ai_config(db)
        provider_id = body.provider or (
            f"api:{ai_cfg.api_provider}" if ai_cfg.connection_mode == "api" else ai_cfg.cli_provider
        )
        cli_model = ai_cfg.api_model if provider_id.startswith("api:") else ai_cfg.cli_model
        failover_enabled = ai_cfg.failover_enabled
        client_ip = get_client_ip(request)

        def _sse(event: str, payload: dict[str, Any]) -> str:
            return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

        async def event_gen():
            ticket = "q_" + uuid.uuid4().hex[:8]
            acquired = False
            try:
                yield _sse("meta", {"session_id": session_id, "provider": "local-instant" if body.instant else provider_id})
                yield _sse("status", {"stage": "searching", "message": "선택된 문서에서 근거 조항과 서식을 검색 중..."})

                retrieval = await asyncio.to_thread(
                    retrieve,
                    db,
                    body.notebook_id,
                    body.query,
                    body.doc_ids,
                    8,
                )

                citations = [
                    {
                        "chunk_id": c["id"],
                        "doc_id": c["doc_id"],
                        "doc_title": c["doc_title"],
                        "doc_category": c["doc_category"],
                        "heading": c["heading"],
                        "section_path": c["section_path"],
                        "page_start": c["page_start"],
                        "page_end": c["page_end"],
                        "excerpt": c["content"][:550],
                        "score": c["score"],
                    }
                    for c in retrieval.chunks
                ]
                forms_payload = [
                    {
                        "id": f["id"],
                        "doc_id": f["doc_id"],
                        "doc_title": f["doc_title"],
                        "title": f["title"],
                        "category": f["category"],
                        "form_type": f["form_type"],
                        "page_start": f["page_start"],
                        "page_end": f["page_end"],
                        "fields": f["fields"],
                    }
                    for f in retrieval.forms
                ]

                yield _sse(
                    "evidence",
                    {
                        "has_evidence": retrieval.has_evidence,
                        "confidence": retrieval.confidence,
                        "citations": citations,
                        "forms": forms_payload,
                        "searched_docs": retrieval.searched_doc_titles,
                    },
                )

                # Grounding Gate: block hallucination immediately if no supporting evidence exists
                if not retrieval.has_evidence:
                    v_empty = {"status": "no_evidence", "verified_count": 0, "unverified_refs": [], "summary": "근거 미발견 차단"}
                    db.add_message(
                        session_id,
                        "assistant",
                        NO_EVIDENCE_MESSAGE,
                        mode=effective_mode,
                        citations=[],
                        forms=[],
                        verification=v_empty,
                        provider="grounding-gate",
                    )
                    db.log_audit("query_blocked", user.role, user.label, client_ip, f"근거 없음 차단 ({effective_mode})")
                    yield _sse("delta", {"text": NO_EVIDENCE_MESSAGE})
                    yield _sse("verification", v_empty)
                    yield _sse("done", {"has_evidence": False, "provider": "grounding-gate", "verification": v_empty})
                    return

                # Instant Local Search Mode (<50ms, 100% offline, zero LLM wait)
                if body.instant:
                    instant_md = format_instant_search_answer(body.query, retrieval)
                    v_inst = {
                        "status": "verified",
                        "verified_count": len(citations),
                        "unverified_refs": [],
                        "summary": f"원문 직접 추출 {len(citations)}건 (오프라인 즉시 검색)",
                    }
                    db.add_message(
                        session_id,
                        "assistant",
                        instant_md,
                        mode="instant",
                        citations=citations,
                        forms=forms_payload,
                        verification=v_inst,
                        provider="local-instant",
                    )
                    db.log_audit("query_instant", user.role, user.label, client_ip, f"즉시 원문 검색 ({len(citations)}건)")
                    yield _sse("delta", {"text": instant_md})
                    yield _sse("verification", v_inst)
                    yield _sse("done", {"has_evidence": True, "provider": "local-instant", "verification": v_inst})
                    return

                # Enter multi-user CLI worker queue
                async for q_state in q_mgr.wait_turn(ticket):
                    if q_state["stage"] == "queued":
                        yield _sse(
                            "status",
                            {
                                "stage": "queued",
                                "position": q_state["position"],
                                "message": f"다른 팀원의 질문 처리 중 — 대기열 {q_state['position']}번째...",
                            },
                        )
                    elif q_state["stage"] == "acquired":
                        acquired = True

                engine_display = (
                    f"{provider_id[4:].upper()} API"
                    if provider_id.startswith("api:")
                    else f"{provider_id.upper()} CLI"
                )
                yield _sse("status", {"stage": "generating", "message": f"{engine_display}로 근거 기반 답변 생성 중..."})

                prompt = build_grounded_prompt(
                    notebook=nb,
                    query=body.query,
                    retrieval=retrieval,
                    mode=body.mode,
                    history=[{"role": m["role"], "content": m["content"]} for m in history],
                )

                active_provider = provider_id
                switch_queue: list[str] = []

                async def _on_switch(old_p: str, new_p: str) -> None:
                    switch_queue.append(f"{old_p.upper()} 지연/오류 → {new_p.upper()} 자동 전환 중...")

                full_parts: list[str] = []
                offline_fallback_used = False
                try:
                    async for used_pid, piece in stream_cli_with_failover(
                        provider_id,
                        prompt,
                        model=cli_model or None,
                        failover_enabled=failover_enabled,
                        on_switch=_on_switch,
                        ai_config=ai_cfg,
                    ):
                        while switch_queue:
                            yield _sse("status", {"stage": "failover", "message": switch_queue.pop(0)})
                        active_provider = used_pid
                        if await request.is_disconnected():
                            break
                        full_parts.append(piece)
                        yield _sse("delta", {"text": piece})
                except Exception:
                    if full_parts:
                        raise
                    # Seamless 100% offline fallback: never break when internet or CLI/API is unavailable
                    offline_fallback_used = True
                    active_provider = "local-offline-fallback"
                    yield _sse(
                        "status",
                        {
                            "stage": "offline_fallback",
                            "message": "오프라인/AI 연결 불가 → PC 내장 즉시 원문 검색으로 자동 전환됨",
                        },
                    )
                    instant_md = (
                        "> **오프라인 원문 검색 자동 전환**: 현재 인터넷 또는 AI 엔진(CLI/API)에 연결할 수 없어, "
                        "PC 내부 색인에서 관련 원문 조항을 즉시 추출했습니다.\n\n"
                        + format_instant_search_answer(body.query, retrieval)
                    )
                    full_parts.append(instant_md)
                    yield _sse("delta", {"text": instant_md})

                full_text = "".join(full_parts).strip() or NO_EVIDENCE_MESSAGE
                is_negative = (not offline_fallback_used) and (
                    "찾을 수 없습니다" in full_text[:120] or "정보가 없습니다" in full_text[:120]
                )

                # Optional 2-Pass AI Strict Verification against raw RAG excerpts
                double_verified = False
                if body.double_verify and not is_negative and not offline_fallback_used and not await request.is_disconnected():
                    yield _sse("status", {"stage": "verifying", "message": "이중 원문 재대조 수행 중 (조항·숫자·쪽수 검수)..."})
                    v_prompt = build_double_verify_prompt(body.query, full_text, retrieval)
                    v_parts: list[str] = []
                    try:
                        async for _, v_piece in stream_cli_with_failover(
                            active_provider,
                            v_prompt,
                            model=cli_model or None,
                            failover_enabled=failover_enabled,
                            timeout_sec=120,
                            ai_config=ai_cfg,
                        ):
                            v_parts.append(v_piece)
                        refined = "".join(v_parts).strip()
                        if len(refined) > 30:
                            full_text = refined
                            double_verified = True
                            yield _sse("replace", {"text": full_text})
                    except Exception:
                        pass

                # Deterministic Post-Generation Citation Verifier
                if offline_fallback_used:
                    verification = {
                        "status": "verified",
                        "verified_count": len(citations),
                        "unverified_refs": [],
                        "summary": f"오프라인 자동 전환 · 원문 직접 추출 {len(citations)}건",
                    }
                elif not is_negative:
                    verification = verify_citations(full_text, retrieval)
                else:
                    verification = {
                        "status": "no_evidence",
                        "verified_count": 0,
                        "unverified_refs": [],
                        "summary": "근거 미발견 안내",
                    }
                if double_verified and verification.get("status") == "verified":
                    verification["summary"] = f"이중 원문 대조 완료 · {verification['summary']}"
                verification["double_verified"] = double_verified

                db.add_message(
                    session_id,
                    "assistant",
                    full_text,
                    mode=body.mode,
                    citations=[] if is_negative else citations,
                    forms=[] if is_negative else forms_payload,
                    verification=verification,
                    provider=active_provider,
                )
                db.log_audit(
                    "query_ai",
                    user.role,
                    user.label,
                    client_ip,
                    f"모드={body.mode} 엔진={active_provider} 검증={verification.get('status')}",
                )
                yield _sse("verification", verification)
                yield _sse(
                    "done",
                    {
                        "has_evidence": not is_negative,
                        "provider": active_provider,
                        "verification": verification,
                    },
                )
            except Exception as exc:
                yield _sse("error", {"message": str(exc)})
            finally:
                if acquired:
                    await q_mgr.release()

        return StreamingResponse(
            event_gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ---- Admin Settings, CLI/API Engines, Security, Audit Logs & Backups ----
    @app.get("/api/admin/cli")
    def get_cli_settings(request: Request, _: AuthUser = Depends(require_user)) -> dict[str, Any]:
        db: Database = request.app.state.db
        q_mgr: QueryQueueManager = request.app.state.queue
        auth: PinAuthManager = request.app.state.auth
        ai_cfg = load_ai_config(db)
        cli_list = detect_cli_providers()
        providers = [p.__dict__ for p in cli_list]
        api_providers = get_api_providers_status(db)

        avail_cli = [p for p in cli_list if p.available]
        sel_api = next((a for a in api_providers if a["id"] == ai_cfg.api_provider), None)
        if ai_cfg.connection_mode == "api":
            if sel_api and sel_api["configured"]:
                active_summary = f"API 직접 연결 · {sel_api['name']} ({ai_cfg.effective_api_model()})"
            else:
                active_summary = "API 직접 연결 (API 키 미입력 — 오프라인 원문 검색 동작 중)"
        elif ai_cfg.connection_mode == "cli":
            if avail_cli:
                sel_c = next((c for c in avail_cli if c.id == ai_cfg.cli_provider), avail_cli[0])
                active_summary = f"구독 CLI · {sel_c.name}"
            else:
                active_summary = "구독 CLI 미감지 (오프라인 원문 검색 동작 중)"
        else:
            if avail_cli:
                sel_c = next((c for c in avail_cli if c.id == ai_cfg.cli_provider), avail_cli[0])
                extra = f" + {sel_api['name']} 백업" if (sel_api and sel_api["has_key"]) else ""
                active_summary = f"자동 모드 · {sel_c.name}{extra}"
            elif sel_api and sel_api["has_key"]:
                active_summary = f"자동 모드 · {sel_api['name']} ({ai_cfg.effective_api_model()})"
            else:
                active_summary = "오프라인 즉시 원문 검색 (CLI · API 키 미설정)"

        return {
            "connection_mode": ai_cfg.connection_mode,
            "provider": ai_cfg.cli_provider,
            "model": ai_cfg.cli_model,
            "api_provider": ai_cfg.api_provider,
            "api_model": ai_cfg.api_model,
            "api_base_url": ai_cfg.api_base_url,
            "active_engine_summary": active_summary,
            "max_concurrent": q_mgr.max_concurrent,
            "custom_public_url": db.get_setting("custom_public_url", ""),
            "cli_failover_enabled": ai_cfg.failover_enabled,
            "default_double_verify": db.get_setting("default_double_verify", "0") == "1",
            "default_chat_shared": db.get_setting("default_chat_shared", "0") == "1",
            "audit_log_enabled": db.get_setting("audit_log_enabled", "1") == "1",
            "is_default_pin": auth.is_using_default_pins(),
            "queue": q_mgr.status(),
            "providers": providers,
            "api_providers": api_providers,
        }

    @app.put("/api/admin/cli")
    async def update_cli_settings(
        body: CliSettingsReq,
        request: Request,
        user: AuthUser = Depends(require_admin),
    ) -> dict[str, Any]:
        db: Database = request.app.state.db
        q_mgr: QueryQueueManager = request.app.state.queue
        mode = body.connection_mode if body.connection_mode in {"auto", "cli", "api"} else "auto"
        db.set_setting("ai_connection_mode", mode)
        db.set_setting("cli_provider", body.provider)
        db.set_setting("cli_model", body.model.strip())
        db.set_setting("ai_api_provider", body.api_provider)
        db.set_setting("ai_api_model", body.api_model.strip())
        db.set_setting("ai_api_base_url", body.api_base_url.strip())
        if body.clear_api_key:
            save_ai_api_key(db, body.api_provider, "")
        elif body.api_key is not None and body.api_key.strip():
            save_ai_api_key(db, body.api_provider, body.api_key.strip())
        db.set_setting("max_concurrent_cli", str(max(1, min(6, body.max_concurrent))))
        db.set_setting("custom_public_url", body.custom_public_url.strip())
        db.set_setting("cli_failover_enabled", "1" if body.cli_failover_enabled else "0")
        db.set_setting("default_double_verify", "1" if body.default_double_verify else "0")
        db.set_setting("default_chat_shared", "1" if body.default_chat_shared else "0")
        db.set_setting("audit_log_enabled", "1" if body.audit_log_enabled else "0")
        await q_mgr.set_max_concurrent(body.max_concurrent)
        db.log_audit(
            "settings_updated",
            user.role,
            user.label,
            get_client_ip(request),
            f"방식={mode} CLI={body.provider} API={body.api_provider} 폴백={body.cli_failover_enabled}",
        )
        return {"ok": True}

    @app.post("/api/admin/ai/test")
    async def test_ai_connection_route(
        body: AiConnectionTestReq,
        request: Request,
        _: AuthUser = Depends(require_admin),
    ) -> dict[str, Any]:
        db: Database = request.app.state.db
        ai_cfg = load_ai_config(db)
        return await test_ai_connection(
            ai_config=ai_cfg,
            mode=body.mode,
            provider_id=body.provider,
            override_api_key=body.api_key,
            override_model=body.model,
            override_base_url=body.base_url,
        )

    # ---- Opt-In Auto-Update (GitHub Releases + Custom Feed + Offline Patch ZIP) ----
    @app.get("/api/updates/check")
    async def check_updates_route(
        request: Request,
        force: bool = False,
        _: AuthUser = Depends(require_user),
    ) -> dict[str, Any]:
        updater: UpdateManager = request.app.state.updater
        return await updater.check_for_updates(request.app.state.db, force=force)

    @app.get("/api/updates/status")
    def update_status_route(
        request: Request,
        _: AuthUser = Depends(require_user),
    ) -> dict[str, Any]:
        updater: UpdateManager = request.app.state.updater
        return {
            "current_version": APP_VERSION,
            "progress": updater.get_progress_dict(),
        }

    @app.put("/api/updates/settings")
    def update_settings_route(
        body: UpdateSettingsReq,
        request: Request,
        user: AuthUser = Depends(require_admin),
    ) -> dict[str, Any]:
        updater: UpdateManager = request.app.state.updater
        cfg = updater.save_settings(
            request.app.state.db,
            channel=body.channel,
            github_repo=body.github_repo,
            custom_url=body.custom_url,
            auto_check=body.auto_check,
            skipped_version=body.skipped_version,
        )
        request.app.state.db.log_audit(
            "update_settings",
            user.role,
            user.label,
            get_client_ip(request),
            f"채널={cfg['channel']} 자동확인={cfg['auto_check']}",
        )
        return {"ok": True, "settings": cfg}

    @app.post("/api/updates/skip")
    def skip_update_version_route(
        body: UpdateSkipReq,
        request: Request,
        user: AuthUser = Depends(require_user),
    ) -> dict[str, Any]:
        updater: UpdateManager = request.app.state.updater
        if user.role == "admin":
            updater.save_settings(request.app.state.db, skipped_version=body.version)
        return {"ok": True, "skipped_version": body.version.strip().lstrip("vV")}

    @app.post("/api/updates/download")
    async def download_update_route(
        request: Request,
        user: AuthUser = Depends(require_admin),
    ) -> dict[str, Any]:
        updater: UpdateManager = request.app.state.updater
        try:
            res = await updater.start_download(request.app.state.db)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        request.app.state.db.log_audit(
            "update_download",
            user.role,
            user.label,
            get_client_ip(request),
            f"대상={updater.state.target_version}",
        )
        return res

    @app.post("/api/updates/upload-patch")
    async def upload_offline_patch_route(
        request: Request,
        file: UploadFile = File(...),
        user: AuthUser = Depends(require_admin),
    ) -> dict[str, Any]:
        if not (file.filename or "").lower().endswith(".zip"):
            raise HTTPException(status_code=400, detail=".zip 형식의 업데이트 패치 파일만 업로드할 수 있습니다.")
        updater: UpdateManager = request.app.state.updater
        tmp_zip = get_updates_dir() / f"uploaded_{uuid.uuid4().hex[:8]}.zip"
        try:
            with tmp_zip.open("wb") as out_f:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    out_f.write(chunk)
            res = await asyncio.to_thread(updater.stage_local_patch_zip, tmp_zip, Path(file.filename or "").stem)
            request.app.state.db.log_audit(
                "update_upload_patch",
                user.role,
                user.label,
                get_client_ip(request),
                f"로컬 패치 검증 완료 ({res['version']})",
            )
            return res
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            tmp_zip.unlink(missing_ok=True)

    @app.post("/api/updates/apply")
    def apply_update_route(
        request: Request,
        user: AuthUser = Depends(require_admin),
    ) -> dict[str, Any]:
        updater: UpdateManager = request.app.state.updater
        db: Database = request.app.state.db
        try:
            res = updater.apply_staged_update(db)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        db.log_audit(
            "update_apply",
            user.role,
            user.label,
            get_client_ip(request),
            f"v{APP_VERSION} -> v{updater.state.target_version} ({res.get('install_mode')})",
        )
        return res

    @app.get("/api/updates/local-manifest.json")
    def serve_local_update_manifest() -> FileResponse:
        manifest_path = get_local_releases_dir() / "update-manifest.json"
        if not manifest_path.exists():
            raise HTTPException(status_code=404, detail="로컬 릴리즈 매니페스트가 아직 생성되지 않았습니다.")
        return FileResponse(path=str(manifest_path), media_type="application/json")

    @app.get("/api/updates/local-assets/{filename}")
    def serve_local_update_asset(filename: str) -> FileResponse:
        safe = Path(filename).name
        target = get_local_releases_dir() / safe
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="릴리즈 파일을 찾을 수 없습니다.")
        return FileResponse(path=str(target), media_type="application/octet-stream", filename=safe)

    @app.get("/api/admin/audit-logs")
    def get_audit_logs(request: Request, limit: int = 80, _: AuthUser = Depends(require_admin)) -> list[dict[str, Any]]:
        return request.app.state.db.list_audit_logs(limit=min(300, max(10, limit)))

    @app.delete("/api/admin/audit-logs")
    def clear_audit_logs(request: Request, _: AuthUser = Depends(require_admin)) -> dict[str, bool]:
        request.app.state.db.clear_audit_logs()
        return {"ok": True}

    @app.get("/api/admin/backups")
    def get_backups_route(_: AuthUser = Depends(require_admin)) -> list[dict[str, Any]]:
        return list_backups()

    @app.post("/api/admin/backups")
    def create_backup_route(request: Request, user: AuthUser = Depends(require_admin)) -> dict[str, Any]:
        db: Database = request.app.state.db
        info = create_backup(db.db_path, reason="manual")
        db.log_audit("backup_created", user.role, user.label, get_client_ip(request), info["name"])
        return info

    @app.get("/api/admin/backups/{name}/download")
    def download_backup_route(name: str, _: AuthUser = Depends(require_admin)) -> FileResponse:
        path = get_backup_path(name)
        if not path:
            raise HTTPException(status_code=404, detail="백업 파일을 찾을 수 없습니다.")
        return FileResponse(path=str(path), media_type="application/octet-stream", filename=path.name)

    @app.post("/api/admin/backups/{name}/restore")
    def restore_backup_route(
        name: str,
        request: Request,
        user: AuthUser = Depends(require_admin),
    ) -> dict[str, Any]:
        db: Database = request.app.state.db
        try:
            res = restore_backup(db.db_path, name)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="백업 파일을 찾을 수 없습니다.")
        db.log_audit("backup_restored", user.role, user.label, get_client_ip(request), f"복구: {name}")
        return {"ok": True, **res}

    @app.get("/api/admin/network")
    def get_network(request: Request, _: AuthUser = Depends(require_user)) -> dict[str, Any]:
        db: Database = request.app.state.db
        tunnel: NetworkTunnelManager = request.app.state.tunnel
        custom_url = db.get_setting("custom_public_url", "") or ""
        apk = _find_apk_path()
        return tunnel.get_network_summary(custom_public_url=custom_url, apk_available=bool(apk))

    @app.post("/api/admin/tunnel/start")
    def start_tunnel(body: TunnelActionReq, request: Request, _: AuthUser = Depends(require_admin)) -> dict[str, Any]:
        tunnel: NetworkTunnelManager = request.app.state.tunnel
        if body.kind == "cloudflare":
            return tunnel.start_cloudflare_tunnel(named_token=body.token)
        return tunnel.start_tailscale_funnel()

    @app.post("/api/admin/tunnel/stop")
    def stop_tunnel(body: TunnelActionReq, request: Request, _: AuthUser = Depends(require_admin)) -> dict[str, Any]:
        tunnel: NetworkTunnelManager = request.app.state.tunnel
        if body.kind == "cloudflare":
            tunnel.stop_cloudflare_tunnel()
            return {"ok": True, "message": "Cloudflare 터널을 중지했습니다."}
        return tunnel.stop_tailscale_funnel()

    # ---- Creator-Only Feedback / Bug / Improvement Reporting ----
    def _relay_feedback_to_creator(relay_url: str, relay_token: str, payload: dict[str, Any]) -> bool:
        if not relay_url.strip() or not relay_token.strip():
            return False
        target = relay_url.strip().rstrip("/")
        if not target.endswith("/api/feedback/relay"):
            target = target + "/api/feedback/relay"
        try:
            req = urllib.request.Request(
                target,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "X-Creator-Token": relay_token.strip(),
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                return 200 <= resp.status < 300
        except Exception:
            return False

    @app.post("/api/feedback")
    async def submit_feedback(
        body: FeedbackCreateReq,
        request: Request,
        user: AuthUser = Depends(require_user),
    ) -> dict[str, Any]:
        """Any authenticated user can submit a report; only the Creator can read the inbox."""
        db: Database = request.app.state.db
        ip = get_client_ip(request)
        rec = db.create_feedback(
            category=body.category,
            title=body.title,
            description=body.description,
            reporter_label=user.label,
            reporter_role=user.role,
            client_ip=ip,
            device_info=body.device_info,
            app_version=APP_VERSION,
            context_info=body.context_info,
            relayed_remote=False,
        )
        relay_url = (db.get_setting("creator_relay_url", "") or "").strip()
        relay_tok = (db.get_setting("creator_relay_token_out", "") or "").strip()
        relayed = False
        if relay_url and relay_tok:
            relayed = await asyncio.to_thread(
                _relay_feedback_to_creator,
                relay_url,
                relay_tok,
                {
                    "category": rec["category"],
                    "title": rec["title"],
                    "description": rec["description"],
                    "reporter_label": rec["reporter_label"],
                    "reporter_role": rec["reporter_role"],
                    "device_info": rec["device_info"],
                    "app_version": rec["app_version"],
                    "context_info": f"[원격 PC 전달] {rec['context_info']}".strip(),
                },
            )
            if relayed:
                db.update_feedback(rec["id"], relayed_remote=True)
        db.log_audit("feedback_submitted", user.role, user.label, ip, f"[{rec['category']}] {rec['title'][:80]}")
        return {
            "ok": True,
            "id": rec["id"],
            "relayed_remote": relayed,
            "created_at": rec["created_at"],
        }

    @app.post("/api/feedback/relay")
    def receive_relayed_feedback(body: dict[str, Any], request: Request) -> dict[str, Any]:
        """Receive feedback forwarded from other PC installations strictly via Creator secret token."""
        auth: PinAuthManager = request.app.state.auth
        db: Database = request.app.state.db
        token = request.headers.get("X-Creator-Token", "")
        if not auth.verify_relay_token(token):
            raise HTTPException(status_code=403, detail="유효하지 않은 제작자 수신 토큰입니다.")
        title = str(body.get("title", "")).strip()
        desc = str(body.get("description", "")).strip()
        if len(title) < 2 or len(desc) < 4:
            raise HTTPException(status_code=400, detail="제보 제목과 내용이 필요합니다.")
        rec = db.create_feedback(
            category=str(body.get("category", "bug")),
            title=title,
            description=desc,
            reporter_label=str(body.get("reporter_label", "원격 사용자")),
            reporter_role=str(body.get("reporter_role", "member")),
            client_ip=get_client_ip(request),
            device_info=str(body.get("device_info", "")),
            app_version=str(body.get("app_version", "")),
            context_info=str(body.get("context_info", "[원격 PC 전달]")),
            relayed_remote=True,
        )
        return {"ok": True, "id": rec["id"]}

    @app.get("/api/admin/feedback")
    def list_feedback_creator(
        request: Request,
        status: str = "",
        user: AuthUser = Depends(require_admin),
    ) -> dict[str, Any]:
        auth: PinAuthManager = request.app.state.auth
        auth.verify_creator_pin(request.headers.get("X-Creator-Pin"), get_client_ip(request), user.label)
        db: Database = request.app.state.db
        items = db.list_feedback(status=status)
        return {
            "items": items,
            "open_count": db.count_open_feedback(),
            "has_custom_creator_pin": auth.has_custom_creator_pin(),
            "creator_relay_token": auth.get_or_create_relay_token(),
            "creator_relay_url": db.get_setting("creator_relay_url", "") or "",
            "creator_relay_token_out": db.get_setting("creator_relay_token_out", "") or "",
        }

    @app.patch("/api/admin/feedback/{feedback_id}")
    def update_feedback_creator(
        feedback_id: int,
        body: FeedbackUpdateReq,
        request: Request,
        user: AuthUser = Depends(require_admin),
    ) -> dict[str, Any]:
        auth: PinAuthManager = request.app.state.auth
        auth.verify_creator_pin(request.headers.get("X-Creator-Pin"), get_client_ip(request), user.label)
        updated = request.app.state.db.update_feedback(feedback_id, status=body.status, creator_note=body.creator_note)
        if not updated:
            raise HTTPException(status_code=404, detail="제보 항목을 찾을 수 없습니다.")
        return updated

    @app.delete("/api/admin/feedback/{feedback_id}")
    def delete_feedback_creator(
        feedback_id: int,
        request: Request,
        user: AuthUser = Depends(require_admin),
    ) -> dict[str, bool]:
        auth: PinAuthManager = request.app.state.auth
        auth.verify_creator_pin(request.headers.get("X-Creator-Pin"), get_client_ip(request), user.label)
        ok = request.app.state.db.delete_feedback(feedback_id)
        if not ok:
            raise HTTPException(status_code=404, detail="제보 항목을 찾을 수 없습니다.")
        return {"ok": True}

    @app.put("/api/admin/creator-settings")
    def update_creator_settings(
        body: CreatorSettingsReq,
        request: Request,
        user: AuthUser = Depends(require_admin),
    ) -> dict[str, Any]:
        auth: PinAuthManager = request.app.state.auth
        auth.verify_creator_pin(request.headers.get("X-Creator-Pin"), get_client_ip(request), user.label)
        db: Database = request.app.state.db
        if body.new_creator_pin:
            auth.set_creator_pin(body.new_creator_pin)
        if body.creator_relay_url is not None:
            db.set_setting("creator_relay_url", body.creator_relay_url.strip())
        if body.creator_relay_token_out is not None:
            db.set_setting("creator_relay_token_out", body.creator_relay_token_out.strip())
        db.log_audit("creator_settings", user.role, user.label, get_client_ip(request), "제작자 제보함 설정 변경")
        return {"ok": True, "has_custom_creator_pin": auth.has_custom_creator_pin()}

    # ---- Android APK direct download (supports both legacy & branded paths) ----
    @app.get("/downloads/church-search.apk")
    @app.get("/downloads/mokpo-sarang-qa.apk")
    def download_apk() -> FileResponse:
        apk = _find_apk_path()
        if not apk:
            raise HTTPException(status_code=404, detail="안드로이드 APK 파일이 아직 빌드되지 않았습니다.")
        encoded = quote("목포사랑의교회-행정Q&A.apk")
        return FileResponse(
            path=str(apk),
            media_type="application/vnd.android.package-archive",
            headers={"Content-Disposition": f"attachment; filename=\"mokpo-sarang-qa.apk\"; filename*=UTF-8''{encoded}"},
        )

    # ---- Frontend SPA Static Serving ----
    dist_dir = _find_frontend_dist()
    if dist_dir:
        assets_dir = dist_dir / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/{full_path:path}")
        def serve_spa(full_path: str):
            if full_path.startswith("api/") or full_path.startswith("downloads/"):
                raise HTTPException(status_code=404, detail="Not found")
            candidate = dist_dir / full_path
            if full_path and candidate.exists() and candidate.is_file():
                return FileResponse(str(candidate))
            return FileResponse(str(dist_dir / "index.html"))
    else:
        @app.get("/")
        def root_placeholder() -> HTMLResponse:
            return HTMLResponse("<h3>프론트엔드 빌드 대기 중 (frontend/dist 없음)</h3>")

    return app


app = create_app()
