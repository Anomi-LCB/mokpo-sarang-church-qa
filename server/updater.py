from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from core.config import (
    APP_NAME,
    APP_VERSION,
    DEFAULT_PORT,
    DEFAULT_UPDATE_MANIFEST_URL,
    DEFAULT_UPDATE_RELEASES_API,
    DEFAULT_UPDATE_REPO,
    get_base_dir,
    get_data_dir,
)
from server.backup import create_backup

APP_EXEC_FILENAME = "목포사랑의교회 행정Q&A.exe"


def parse_version(ver: str) -> tuple[int, ...]:
    clean = (ver or "").strip().lstrip("vV")
    clean = clean.split("-", 1)[0].split("+", 1)[0]
    nums: list[int] = []
    for part in clean.split("."):
        m = re.match(r"(\d+)", part.strip())
        nums.append(int(m.group(1)) if m else 0)
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums[:4])


def is_newer_version(remote_ver: str, current_ver: str = APP_VERSION) -> bool:
    if not (remote_ver or "").strip():
        return False
    return parse_version(remote_ver) > parse_version(current_ver)


def get_updates_dir() -> Path:
    p = get_data_dir() / "updates"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_local_releases_dir() -> Path:
    p = get_data_dir() / "releases"
    p.mkdir(parents=True, exist_ok=True)
    return p


def detect_install_mode() -> str:
    if not getattr(sys, "frozen", False):
        return "source"
    base = get_base_dir()
    if (base / "unins000.exe").exists() or "program files" in str(base).lower():
        return "frozen_installed"
    return "frozen_portable"


def _is_safe_download_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme == "https":
        return bool(parsed.netloc)
    if parsed.scheme == "http":
        host = (parsed.hostname or "").lower()
        return (
            host in {"localhost", "127.0.0.1"}
            or host.startswith("192.168.")
            or host.startswith("10.")
            or host.startswith("100.")
            or host.endswith(".ts.net")
        )
    return False


def _extract_highlights(notes_md: str) -> list[str]:
    out: list[str] = []
    for ln in (notes_md or "").splitlines():
        s = ln.strip()
        if s.startswith(("- ", "* ", "• ")):
            item = re.sub(r"^[-*•]\s+", "", s).strip()
            item = re.sub(r"\*\*(.+?)\*\*", r"\1", item)
            if item and len(out) < 6:
                out.append(item[:140])
    return out


def _normalize_github_release(rel: dict[str, Any]) -> dict[str, Any]:
    tag = str(rel.get("tag_name") or "").strip().lstrip("vV")
    body = str(rel.get("body") or "").strip()
    assets = rel.get("assets") or []

    patch_zip: dict[str, Any] | None = None
    installer_exe: dict[str, Any] | None = None
    android_apk: dict[str, Any] | None = None

    for a in assets:
        name = str(a.get("name") or "")
        low = name.lower()
        url = str(a.get("browser_download_url") or "")
        size = int(a.get("size") or 0)
        entry = {"name": name, "url": url, "sha256": "", "size_bytes": size}
        if low.endswith(".zip") and ("update" in low or "win" in low or "patch" in low):
            patch_zip = entry
        elif low.endswith(".exe") and ("setup" in low or "설치" in low or "installer" in low):
            installer_exe = entry
        elif low.endswith(".apk") and "lite" not in low:
            android_apk = entry

    return {
        "version": tag,
        "published_at": str(rel.get("published_at") or ""),
        "title": str(rel.get("name") or f"{APP_NAME} v{tag}"),
        "highlights": _extract_highlights(body),
        "notes_md": body or "새로운 기능 개선 및 안정성 업데이트가 포함되어 있습니다.",
        "release_url": str(rel.get("html_url") or ""),
        "assets": {
            "win_patch_zip": patch_zip,
            "win_installer_exe": installer_exe,
            "android_apk": android_apk,
        },
    }


def _normalize_manifest(data: dict[str, Any], repo: str = DEFAULT_UPDATE_REPO) -> dict[str, Any]:
    version = str(data.get("version") or "").strip().lstrip("vV")
    notes_md = str(data.get("notes_md") or data.get("notes") or "").strip()
    highlights = data.get("highlights")
    if not isinstance(highlights, list) or not highlights:
        highlights = _extract_highlights(notes_md)
    assets = data.get("assets") if isinstance(data.get("assets"), dict) else {}
    return {
        "version": version,
        "published_at": str(data.get("published_at") or ""),
        "title": str(data.get("title") or f"{APP_NAME} v{version}"),
        "highlights": [str(h) for h in highlights[:8]],
        "notes_md": notes_md or "새로운 기능 개선 및 안정성 업데이트가 포함되어 있습니다.",
        "release_url": str(
            data.get("release_url")
            or f"https://github.com/{repo}/releases/tag/v{version}"
        ),
        "assets": {
            "win_patch_zip": assets.get("win_patch_zip"),
            "win_installer_exe": assets.get("win_installer_exe"),
            "android_apk": assets.get("android_apk"),
        },
    }


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def validate_and_extract_patch_zip(zip_path: Path, staging_dir: Path) -> dict[str, Any]:
    """Validate patch ZIP against ZipSlip and user-data overwrites, then extract safely."""
    if not zip_path.exists() or not zipfile.is_zipfile(zip_path):
        raise ValueError("유효한 업데이트 ZIP 파일이 아닙니다.")

    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)

    has_app_payload = False
    extracted_files = 0
    detected_version = ""

    with zipfile.ZipFile(zip_path, "r") as zf:
        infos = zf.infolist()
        if not infos:
            raise ValueError("비어 있는 업데이트 패키지입니다.")

        # Detect optional single top-level wrapper folder
        top_dirs = {
            PurePathStr.split("/")[0]
            for info in infos
            for PurePathStr in [info.filename.replace("\\", "/").strip("/")]
            if PurePathStr
        }
        strip_prefix = ""
        if len(top_dirs) == 1:
            only_top = next(iter(top_dirs))
            if only_top not in {"_internal", "data"} and any(
                i.filename.replace("\\", "/").startswith(f"{only_top}/") for i in infos
            ):
                strip_prefix = f"{only_top}/"

        for info in infos:
            norm = info.filename.replace("\\", "/")
            if strip_prefix and norm.startswith(strip_prefix):
                norm = norm[len(strip_prefix) :]
            norm = norm.lstrip("/")
            if not norm or norm.endswith("/"):
                continue

            parts = [p for p in norm.split("/") if p]
            if not parts or any(p in {"..", "."} for p in parts) or ":" in parts[0]:
                raise ValueError(f"안전하지 않은 경로가 포함된 업데이트 패키지입니다: {info.filename}")

            # CRITICAL SAFETY: NEVER allow an update archive to overwrite user data/ directly!
            if parts[0].lower() == "data":
                raise ValueError(f"사용자 데이터 보호 위반: data/ 경로는 업데이트로 덮어쓸 수 없습니다 ({norm}).")

            low_first = parts[0].lower()
            if low_first.endswith(".exe") or low_first == "_internal" or low_first == "update-manifest.json":
                has_app_payload = True

            target = (staging_dir / Path(*parts)).resolve()
            if not str(target).startswith(str(staging_dir.resolve())):
                raise ValueError("경로 이탈이 감지되어 업데이트를 중단했습니다.")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info, "r") as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            extracted_files += 1

            if low_first == "update-manifest.json":
                try:
                    meta = json.loads(target.read_text(encoding="utf-8"))
                    detected_version = str(meta.get("version") or "").strip().lstrip("vV")
                except Exception:
                    pass

    if not has_app_payload:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise ValueError("업데이트 패키지에 프로그램 실행 파일(.exe 또는 _internal)이 포함되어 있지 않습니다.")

    return {
        "staging_dir": str(staging_dir),
        "file_count": extracted_files,
        "detected_version": detected_version,
    }


def _build_windows_swap_script(
    pid: int,
    app_dir: Path,
    staging_dir: Path,
    rollback_dir: Path,
    log_file: Path,
    port: int,
    exe_name: str = APP_EXEC_FILENAME,
) -> str:
    """Generate a UTF-8 BOM PowerShell script for atomic swap + health check + auto-rollback."""
    def _ps(p: Path) -> str:
        return str(p).replace("'", "''")

    return f"""$ErrorActionPreference = 'Stop'
$TargetPid = {pid}
$AppDir = '{_ps(app_dir)}'
$StageDir = '{_ps(staging_dir)}'
$RollbackDir = '{_ps(rollback_dir)}'
$LogFile = '{_ps(log_file)}'
$ExeName = '{exe_name.replace("'", "''")}'
$HealthUrl = 'http://127.0.0.1:{port}/api/health'

function Write-Log([string]$Msg) {{
    try {{
        $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
        Add-Content -Path $LogFile -Value "[$ts] $Msg" -Encoding UTF8 -ErrorAction SilentlyContinue
    }} catch {{}}
}}

function Move-WithRetry([string]$Src, [string]$Dst) {{
    for ($try = 0; $try -lt 8; $try++) {{
        try {{
            if (Test-Path -LiteralPath $Dst) {{
                Remove-Item -LiteralPath $Dst -Recurse -Force -ErrorAction Stop
            }}
            Move-Item -LiteralPath $Src -Destination $Dst -Force -ErrorAction Stop
            return
        }} catch {{
            if ($try -eq 7) {{ throw }}
            Start-Sleep -Milliseconds 800
        }}
    }}
}}

Write-Log "Update script started (waiting for PID $TargetPid to exit)..."

# Wait up to 15s for current server process to terminate cleanly
for ($i = 0; $i -lt 30; $i++) {{
    $proc = Get-Process -Id $TargetPid -ErrorAction SilentlyContinue
    if (-not $proc) {{ break }}
    Start-Sleep -Milliseconds 500
}}
$still = Get-Process -Id $TargetPid -ErrorAction SilentlyContinue
if ($still) {{
    Write-Log "Force stopping lingering PID $TargetPid"
    Stop-Process -Id $TargetPid -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}}
# Also stop any duplicate app instances holding _internal locks
$baseProcName = [System.IO.Path]::GetFileNameWithoutExtension($ExeName)
Get-Process -Name $baseProcName -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 600

# Ensure write permission to AppDir; if Program Files requires UAC, self-elevate cleanly using ASCII script path
$NeedAdmin = $false
try {{
    $probe = Join-Path $AppDir '.update_write_test'
    Set-Content -LiteralPath $probe -Value 'ok' -ErrorAction Stop
    Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue
}} catch {{
    $NeedAdmin = $true
}}

if ($NeedAdmin) {{
    $isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {{
        Write-Log "Requesting UAC elevation for Program Files swap..."
        try {{
            Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Hidden','-File',$PSCommandPath) -ErrorAction Stop
            exit 0
        }} catch {{
            Write-Log "UAC elevation cancelled or failed: $($_.Exception.Message). Restarting existing app..."
            $oldExe = Join-Path $AppDir $ExeName
            if (Test-Path -LiteralPath $oldExe) {{ Start-Process -FilePath $oldExe -WorkingDirectory $AppDir }}
            exit 3
        }}
    }}
}}

# Prepare rollback backup of old binaries ONLY (never touch data/)
if (Test-Path -LiteralPath $RollbackDir) {{ Remove-Item -LiteralPath $RollbackDir -Recurse -Force }}
New-Item -ItemType Directory -Path $RollbackDir -Force | Out-Null

$SwapItems = @($ExeName, '_internal', '사용안내.txt')
try {{
    foreach ($item in $SwapItems) {{
        $src = Join-Path $AppDir $item
        if (Test-Path -LiteralPath $src) {{
            Move-WithRetry $src (Join-Path $RollbackDir $item)
        }}
    }}

    Get-ChildItem -LiteralPath $StageDir -Force | ForEach-Object {{
        if ($_.Name -ieq 'data' -or $_.Name -ieq 'update-manifest.json') {{ return }}
        $dest = Join-Path $AppDir $_.Name
        Move-WithRetry $_.FullName $dest
    }}
    Write-Log "New binaries moved into $AppDir successfully."
}} catch {{
    Write-Log "Swap failed: $($_.Exception.Message). Rolling back immediately..."
    foreach ($item in $SwapItems) {{
        $rb = Join-Path $RollbackDir $item
        $dest = Join-Path $AppDir $item
        if (Test-Path -LiteralPath $rb) {{
            try {{ Move-WithRetry $rb $dest }} catch {{}}
        }}
    }}
    $oldExe = Join-Path $AppDir $ExeName
    if (Test-Path -LiteralPath $oldExe) {{ Start-Process -FilePath $oldExe -WorkingDirectory $AppDir }}
    exit 1
}}

# Launch updated app and verify health endpoint within 25s
$newExe = Join-Path $AppDir $ExeName
if (Test-Path -LiteralPath $newExe) {{
    Write-Log "Starting updated executable: $newExe"
    Start-Process -FilePath $newExe -WorkingDirectory $AppDir
}}

$healthy = $false
for ($j = 0; $j -lt 25; $j++) {{
    Start-Sleep -Seconds 1
    try {{
        $res = Invoke-WebRequest -Uri $HealthUrl -TimeoutSec 2 -UseBasicParsing
        if ($res.StatusCode -eq 200) {{
            $healthy = $true
            break
        }}
    }} catch {{}}
}}

if ($healthy) {{
    Write-Log "Health check PASSED! Cleaning up staging directory."
    Remove-Item -LiteralPath $StageDir -Recurse -Force -ErrorAction SilentlyContinue
    exit 0
}} else {{
    Write-Log "Health check FAILED after 25s! Performing automatic rollback..."
    Get-Process -Name $baseProcName -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
    foreach ($item in $SwapItems) {{
        $rb = Join-Path $RollbackDir $item
        $dest = Join-Path $AppDir $item
        if (Test-Path -LiteralPath $rb) {{
            try {{ Move-WithRetry $rb $dest }} catch {{}}
        }}
    }}
    if (Test-Path -LiteralPath $newExe) {{ Start-Process -FilePath $newExe -WorkingDirectory $AppDir }}
    exit 2
}}
"""


@dataclass
class UpdateState:
    status: str = "idle"  # idle | checking | downloading | verifying | ready | applying | error
    progress_pct: int = 0
    downloaded_bytes: int = 0
    total_bytes: int = 0
    target_version: str = ""
    staged_dir: str = ""
    staged_file_count: int = 0
    message: str = ""
    error: str = ""
    last_checked_at: str = ""
    latest_manifest: dict[str, Any] | None = None
    _last_check_ts: float = 0.0
    _download_task: asyncio.Task[Any] | None = field(default=None, repr=False)


class UpdateManager:
    def __init__(self, port: int = DEFAULT_PORT, on_shutdown: Callable[[], None] | None = None) -> None:
        self.port = port
        self.on_shutdown = on_shutdown
        self.state = UpdateState()

    def get_settings(self, db: Any) -> dict[str, Any]:
        channel = (db.get_setting("update_channel", "github") or "github").strip().lower()
        if channel not in {"github", "custom"}:
            channel = "github"
        repo = (db.get_setting("update_github_repo", DEFAULT_UPDATE_REPO) or DEFAULT_UPDATE_REPO).strip()
        custom_url = (db.get_setting("update_custom_url", "") or "").strip()
        auto_check = (db.get_setting("update_auto_check", "1") or "1") == "1"
        skipped = (db.get_setting("update_skipped_version", "") or "").strip()
        return {
            "channel": channel,
            "github_repo": repo,
            "custom_url": custom_url,
            "auto_check": auto_check,
            "skipped_version": skipped,
        }

    def save_settings(
        self,
        db: Any,
        channel: str | None = None,
        github_repo: str | None = None,
        custom_url: str | None = None,
        auto_check: bool | None = None,
        skipped_version: str | None = None,
    ) -> dict[str, Any]:
        if channel in {"github", "custom"}:
            db.set_setting("update_channel", channel)
        if github_repo is not None:
            clean_repo = github_repo.strip().strip("/")
            if clean_repo:
                db.set_setting("update_github_repo", clean_repo)
        if custom_url is not None:
            db.set_setting("update_custom_url", custom_url.strip())
        if auto_check is not None:
            db.set_setting("update_auto_check", "1" if auto_check else "0")
        if skipped_version is not None:
            db.set_setting("update_skipped_version", skipped_version.strip().lstrip("vV"))
        # Invalidate cache so next check uses new feed immediately
        self.state._last_check_ts = 0.0
        return self.get_settings(db)

    async def check_for_updates(self, db: Any, force: bool = False) -> dict[str, Any]:
        cfg = self.get_settings(db)
        now = time.time()
        if not force and self.state.latest_manifest and (now - self.state._last_check_ts) < 1200:
            return self._build_check_response(cfg, self.state.latest_manifest, ok=True, offline=False, err="")

        manifest: dict[str, Any] | None = None
        err_msg = ""
        offline = False

        timeout = httpx.Timeout(connect=6.0, read=12.0, write=6.0, pool=6.0)
        headers = {"User-Agent": f"MokpoSarangChurchQA/{APP_VERSION}", "Accept": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
                if cfg["channel"] == "custom" and cfg["custom_url"]:
                    url = cfg["custom_url"]
                    if not _is_safe_download_url(url):
                        raise RuntimeError("안전한 HTTPS 또는 로컬/Tailscale 업데이트 주소만 허용됩니다.")
                    resp = await client.get(url)
                    if resp.status_code >= 400:
                        raise RuntimeError(f"업데이트 서버 응답 오류 (HTTP {resp.status_code})")
                    manifest = _normalize_manifest(resp.json(), repo=cfg["github_repo"])
                else:
                    repo = cfg["github_repo"] or DEFAULT_UPDATE_REPO
                    manifest_url = f"https://github.com/{repo}/releases/latest/download/update-manifest.json"
                    resp = await client.get(manifest_url)
                    if resp.status_code == 200:
                        manifest = _normalize_manifest(resp.json(), repo=repo)
                    else:
                        api_url = f"https://api.github.com/repos/{repo}/releases/latest"
                        resp2 = await client.get(api_url)
                        if resp2.status_code == 200:
                            manifest = _normalize_github_release(resp2.json())
                        elif resp2.status_code == 404:
                            err_msg = "아직 등록된 공식 릴리즈가 없습니다."
                        else:
                            raise RuntimeError(f"GitHub 릴리즈 조회 실패 (HTTP {resp2.status_code})")
        except (httpx.ConnectError, httpx.TimeoutException, OSError):
            offline = True
            err_msg = "현재 오프라인 상태이거나 업데이트 서버에 연결할 수 없습니다."
        except Exception as exc:
            err_msg = str(exc)

        self.state.last_checked_at = datetime.now(timezone.utc).isoformat()
        if manifest:
            self.state.latest_manifest = manifest
            self.state._last_check_ts = now

        return self._build_check_response(cfg, manifest or self.state.latest_manifest, ok=bool(manifest), offline=offline, err=err_msg)

    def _build_check_response(
        self,
        cfg: dict[str, Any],
        manifest: dict[str, Any] | None,
        ok: bool,
        offline: bool,
        err: str,
    ) -> dict[str, Any]:
        latest_ver = str((manifest or {}).get("version") or "")
        avail = bool(latest_ver and is_newer_version(latest_ver, APP_VERSION))
        skipped = bool(avail and cfg["skipped_version"] and parse_version(cfg["skipped_version"]) >= parse_version(latest_ver))
        return {
            "ok": ok,
            "offline": offline,
            "error": err,
            "current_version": APP_VERSION,
            "install_mode": detect_install_mode(),
            "update_available": avail,
            "should_notify": avail and not skipped,
            "is_skipped": skipped,
            "last_checked_at": self.state.last_checked_at,
            "settings": cfg,
            "latest": manifest,
            "progress": self.get_progress_dict(),
        }

    def get_progress_dict(self) -> dict[str, Any]:
        return {
            "status": self.state.status,
            "progress_pct": self.state.progress_pct,
            "downloaded_bytes": self.state.downloaded_bytes,
            "total_bytes": self.state.total_bytes,
            "target_version": self.state.target_version,
            "staged_ready": bool(self.state.staged_dir and Path(self.state.staged_dir).exists()),
            "staged_file_count": self.state.staged_file_count,
            "message": self.state.message,
            "error": self.state.error,
        }

    async def start_download(self, db: Any, manifest_override: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.state._download_task and not self.state._download_task.done():
            return {"ok": True, "already_running": True, "progress": self.get_progress_dict()}

        manifest = manifest_override or self.state.latest_manifest
        if not manifest:
            res = await self.check_for_updates(db, force=True)
            manifest = res.get("latest")
        if not manifest:
            raise RuntimeError("최신 업데이트 정보를 먼저 확인하지 못했습니다.")

        assets = manifest.get("assets") or {}
        patch = assets.get("win_patch_zip")
        if not patch or not patch.get("url"):
            raise RuntimeError("이 릴리즈에는 자동 적용 가능한 Windows 업데이트 패키지(.zip)가 없습니다.")

        url = str(patch["url"])
        if not _is_safe_download_url(url):
            raise RuntimeError("안전하지 않은 업데이트 다운로드 주소입니다.")

        target_ver = str(manifest.get("version") or "latest")
        expected_sha = str(patch.get("sha256") or "").strip().lower()
        expected_size = int(patch.get("size_bytes") or 0)

        self.state.status = "downloading"
        self.state.progress_pct = 0
        self.state.downloaded_bytes = 0
        self.state.total_bytes = expected_size
        self.state.target_version = target_ver
        self.state.staged_dir = ""
        self.state.error = ""
        self.state.message = f"v{target_ver} 업데이트 패키지 다운로드 중..."

        async def _runner() -> None:
            dl_dir = get_updates_dir()
            zip_path = dl_dir / f"patch_v{target_ver}.zip"
            staging_dir = dl_dir / f"staging_v{target_ver}"
            try:
                timeout = httpx.Timeout(connect=15.0, read=120.0, write=30.0, pool=15.0)
                headers = {"User-Agent": f"MokpoSarangChurchQA/{APP_VERSION}"}
                h = hashlib.sha256()
                async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
                    async with client.stream("GET", url) as resp:
                        if resp.status_code >= 400:
                            raise RuntimeError(f"업데이트 파일 다운로드 실패 (HTTP {resp.status_code})")
                        total = int(resp.headers.get("content-length") or expected_size or 0)
                        self.state.total_bytes = total
                        done = 0
                        with zip_path.open("wb") as out_f:
                            async for chunk in resp.aiter_bytes(chunk_size=131072):
                                out_f.write(chunk)
                                h.update(chunk)
                                done += len(chunk)
                                self.state.downloaded_bytes = done
                                if total > 0:
                                    self.state.progress_pct = min(99, int(done * 100 / total))

                self.state.status = "verifying"
                self.state.progress_pct = 99
                self.state.message = "SHA-256 무결성 검증 및 안전 압축 해제 중..."
                actual_sha = h.hexdigest().lower()
                if expected_sha and actual_sha != expected_sha:
                    zip_path.unlink(missing_ok=True)
                    raise RuntimeError(
                        f"보안 무결성 검증 실패(SHA-256 불일치): 파일이 손상되었을 수 있어 적용을 중단했습니다."
                    )

                info = await asyncio.to_thread(validate_and_extract_patch_zip, zip_path, staging_dir)
                self.state.staged_dir = info["staging_dir"]
                self.state.staged_file_count = info["file_count"]
                self.state.status = "ready"
                self.state.progress_pct = 100
                self.state.message = f"v{target_ver} 검증 완료 ({info['file_count']}개 파일 준비됨 — 기존 DB·문서 100% 유지)"
            except Exception as exc:
                self.state.status = "error"
                self.state.error = str(exc)
                self.state.message = f"업데이트 준비 실패: {exc}"

        self.state._download_task = asyncio.create_task(_runner())
        return {"ok": True, "already_running": False, "progress": self.get_progress_dict()}

    def stage_local_patch_zip(self, zip_path: Path, version_hint: str = "") -> dict[str, Any]:
        staging_dir = get_updates_dir() / f"staging_local_{int(time.time())}"
        info = validate_and_extract_patch_zip(zip_path, staging_dir)
        ver = info["detected_version"] or version_hint or "local-patch"
        self.state.status = "ready"
        self.state.progress_pct = 100
        self.state.target_version = ver
        self.state.staged_dir = info["staging_dir"]
        self.state.staged_file_count = info["file_count"]
        self.state.error = ""
        self.state.message = f"로컬 업데이트 패키지({ver}) 검증 완료 ({info['file_count']}개 파일 준비됨)"
        return {"ok": True, "version": ver, "progress": self.get_progress_dict()}

    def apply_staged_update(self, db: Any) -> dict[str, Any]:
        if not self.state.staged_dir or not Path(self.state.staged_dir).exists():
            raise RuntimeError("적용할 업데이트 패키지가 준비되지 않았습니다. 먼저 다운로드를 완료하세요.")

        # 1. Always create an automatic safety DB backup before touching binaries
        backup_info = create_backup(db.db_path, reason=f"pre_update_v{APP_VERSION}")
        install_mode = detect_install_mode()

        if install_mode == "source" or sys.platform != "win32":
            self.state.message = (
                f"사전 DB 백업({backup_info['name']})과 업데이트 패키지 검증이 완료되었습니다. "
                "(소스 개발 실행 환경에서는 EXE 자가 교체 대신 git pull로 반영하세요.)"
            )
            return {
                "ok": True,
                "restarting": False,
                "install_mode": install_mode,
                "backup": backup_info,
                "message": self.state.message,
            }

        # 2. Frozen Windows EXE atomic swap with automatic health-check rollback
        app_dir = get_base_dir()
        updates_dir = get_updates_dir()
        rollback_dir = updates_dir / "rollback_prev"
        log_file = updates_dir / "update_apply.log"
        # Place swap script in pure-ASCII %TEMP% path (zero spaces / '&' / directory handle lock on AppDir!)
        temp_dir = Path(tempfile.gettempdir())
        ps_script = temp_dir / f"church_qa_apply_update_{os.getpid()}.ps1"

        script_body = _build_windows_swap_script(
            pid=os.getpid(),
            app_dir=app_dir,
            staging_dir=Path(self.state.staged_dir),
            rollback_dir=rollback_dir,
            log_file=log_file,
            port=self.port,
        )
        # UTF-8 with BOM ensures Windows PowerShell 5.1 reads Korean filenames cleanly!
        ps_script.write_text(script_body, encoding="utf-8-sig")

        self.state.status = "applying"
        self.state.message = "DB 백업 완료 — 새 버전 적용 후 프로그램을 자동 재시작합니다... (Windows 권한 확인 창이 뜨면 [예]를 눌러 주세요)"

        # CRITICAL: NEVER combine DETACHED_PROCESS with CREATE_NO_WINDOW on Windows — powershell.exe silently aborts!
        creationflags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-File",
                str(ps_script),
            ],
            cwd=str(temp_dir),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=True,
        )

        # Schedule graceful shutdown right after HTTP response flushes
        def _delayed_exit() -> None:
            time.sleep(1.2)
            if self.on_shutdown:
                try:
                    self.on_shutdown()
                except Exception:
                    pass
            os._exit(0)

        threading.Thread(target=_delayed_exit, daemon=True).start()

        return {
            "ok": True,
            "restarting": True,
            "install_mode": install_mode,
            "backup": backup_info,
            "message": self.state.message,
        }
