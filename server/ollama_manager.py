from __future__ import annotations

import asyncio
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

OLLAMA_DEFAULT_HOST = "http://127.0.0.1:11434"
OLLAMA_OPENAI_BASE = "http://localhost:11434/v1"
OLLAMA_WIN_SETUP_URL = "https://ollama.com/download/OllamaSetup.exe"

RECOMMENDED_OLLAMA_MODELS: list[dict[str, Any]] = [
    {
        "id": "gemma3:4b",
        "name": "Gemma 3 4B (추천)",
        "size_label": "약 3.3 GB",
        "min_ram_gb": 8,
        "badge": "균형 · 추천",
        "desc": "구글 오픈소스 모델 · 한국어 문서 요약이 자연스럽고 일반 사무용 PC에서도 쾌적합니다.",
    },
    {
        "id": "qwen2.5:3b",
        "name": "Qwen 2.5 3B (초경량)",
        "size_label": "약 1.9 GB",
        "min_ram_gb": 6,
        "badge": "초경량 · 빠름",
        "desc": "저사양·구형 사무용 노트북에서도 빠르게 동작하는 가벼운 다국어 모델입니다.",
    },
    {
        "id": "qwen2.5:7b",
        "name": "Qwen 2.5 7B (정밀)",
        "size_label": "약 4.7 GB",
        "min_ram_gb": 16,
        "badge": "정밀 요약",
        "desc": "긴 조항·표 정리에 강점이 있는 중형 모델입니다. (메모리 16GB 이상 PC 권장)",
    },
    {
        "id": "gemma3:12b",
        "name": "Gemma 3 12B (고성능)",
        "size_label": "약 8.1 GB",
        "min_ram_gb": 24,
        "badge": "최고 품질",
        "desc": "고성능 PC·외장 그래픽카드 환경에서 클라우드에 근접한 고품질 답변을 제공합니다.",
    },
]


def _get_system_ram_gb() -> int:
    """Return total installed system RAM in GB (best-effort, zero external dependencies)."""
    if sys.platform == "win32":
        try:
            class _MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = _MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return max(1, int(round(stat.ullTotalPhys / (1024 ** 3))))
        except Exception:
            pass
    return 16


def find_ollama_binary() -> str:
    """Locate ollama executable in PATH or standard Windows install directories."""
    found = shutil.which("ollama")
    if found:
        return found
    local_app = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        Path(local_app) / "Programs" / "Ollama" / "ollama.exe" if local_app else Path(),
        Path(r"C:\Program Files\Ollama\ollama.exe"),
    ]
    for c in candidates:
        if c and c.is_file():
            return str(c)
    return ""


def _recommended_model_for_ram(ram_gb: int) -> str:
    if ram_gb >= 16:
        return "gemma3:4b"
    if ram_gb >= 8:
        return "gemma3:4b"
    return "qwen2.5:3b"


@dataclass
class OllamaSetupState:
    status: str = "idle"  # idle | installing | starting | pulling | ready | error
    progress: int = 0
    model: str = ""
    message: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "progress": self.progress,
            "model": self.model,
            "message": self.message,
            "error": self.error,
        }


class OllamaManager:
    """Detect, auto-install, start, pull Korean models, and activate 100% free local Ollama AI."""

    def __init__(self, host: str = OLLAMA_DEFAULT_HOST) -> None:
        self.host = host.rstrip("/")
        self.state = OllamaSetupState()
        self._task: asyncio.Task[None] | None = None
        self._ram_gb = _get_system_ram_gb()

    async def probe_running(self) -> tuple[bool, list[dict[str, Any]]]:
        """Return (is_running, installed_models) within ~1s without using system proxies."""
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=1.0, read=2.0, write=2.0, pool=1.0),
                trust_env=False,
            ) as client:
                resp = await client.get(f"{self.host}/api/tags")
                if resp.status_code != 200:
                    return False, []
                data = resp.json()
                models_out: list[dict[str, Any]] = []
                for m in data.get("models") or []:
                    name = str(m.get("name") or m.get("model") or "").strip()
                    if not name:
                        continue
                    size_b = int(m.get("size") or 0)
                    models_out.append(
                        {
                            "name": name,
                            "size_gb": round(size_b / (1024 ** 3), 2) if size_b > 0 else 0.0,
                        }
                    )
                return True, models_out
        except Exception:
            return False, []

    async def get_status(self) -> dict[str, Any]:
        bin_path = find_ollama_binary()
        running, models = await self.probe_running()
        return {
            "installed": bool(bin_path) or running,
            "binary_path": bin_path,
            "running": running,
            "host": self.host,
            "openai_base_url": OLLAMA_OPENAI_BASE,
            "ram_gb": self._ram_gb,
            "recommended_default": _recommended_model_for_ram(self._ram_gb),
            "installed_models": models,
            "recommended_models": RECOMMENDED_OLLAMA_MODELS,
            "setup_state": self.state.to_dict(),
        }

    async def ensure_running(self, wait_sec: int = 15) -> bool:
        running, _ = await self.probe_running()
        if running:
            return True
        bin_path = find_ollama_binary()
        if not bin_path:
            return False
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            subprocess.Popen(
                [bin_path, "serve"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
                close_fds=True,
            )
        except Exception:
            return False
        for _ in range(wait_sec * 2):
            await asyncio.sleep(0.5)
            running, _ = await self.probe_running()
            if running:
                return True
        return False

    async def _install_ollama_windows(self) -> str:
        """Install Ollama silently via winget or official OllamaSetup.exe download."""
        self.state.status = "installing"
        self.state.progress = 5
        self.state.message = "무료 로컬 AI 엔진(Ollama)을 설치하고 있습니다..."

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        winget = shutil.which("winget")
        if winget:
            try:
                self.state.progress = 10
                self.state.message = "Windows 패키지 도구(winget)로 Ollama 자동 설치 중..."
                proc = await asyncio.create_subprocess_exec(
                    winget,
                    "install",
                    "--id",
                    "Ollama.Ollama",
                    "--silent",
                    "--accept-package-agreements",
                    "--accept-source-agreements",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    creationflags=creationflags,
                )
                await asyncio.wait_for(proc.wait(), timeout=240)
                bin_path = find_ollama_binary()
                if bin_path:
                    return bin_path
            except Exception:
                pass

        # Fallback: direct download of official OllamaSetup.exe and silent install
        self.state.progress = 14
        self.state.message = "공식 Ollama 설치 파일을 다운로드하고 있습니다..."
        tmp_setup = Path(tempfile.gettempdir()) / "OllamaSetup_ChurchQA.exe"
        try:
            def _download() -> None:
                req = urllib.request.Request(
                    OLLAMA_WIN_SETUP_URL,
                    headers={"User-Agent": "MokpoSarangChurchQA/4.3"},
                )
                with urllib.request.urlopen(req, timeout=120) as resp, tmp_setup.open("wb") as out_f:
                    total = int(resp.headers.get("Content-Length") or 0)
                    done = 0
                    while True:
                        chunk = resp.read(256 * 1024)
                        if not chunk:
                            break
                        out_f.write(chunk)
                        done += len(chunk)
                        if total > 0:
                            pct = 14 + int((done / total) * 14)
                            self.state.progress = min(28, pct)

            await asyncio.to_thread(_download)
            self.state.progress = 30
            self.state.message = "Ollama 엔진을 PC에 설치하는 중..."
            proc = await asyncio.create_subprocess_exec(
                str(tmp_setup),
                "/VERYSILENT",
                "/NORESTART",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=creationflags,
            )
            await asyncio.wait_for(proc.wait(), timeout=240)
        finally:
            try:
                tmp_setup.unlink(missing_ok=True)
            except Exception:
                pass

        bin_path = find_ollama_binary()
        if not bin_path:
            raise RuntimeError(
                "Ollama 자동 설치를 완료하지 못했습니다. https://ollama.com/download 에서 직접 설치한 뒤 다시 눌러 주세요."
            )
        return bin_path

    async def _pull_model(self, model: str) -> None:
        self.state.status = "pulling"
        self.state.progress = max(self.state.progress, 35)
        self.state.message = f"무료 한국어 AI 모델({model}) 다운로드를 시작합니다..."
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=15.0, read=1800.0, write=30.0, pool=15.0),
            trust_env=False,
        ) as client:
            async with client.stream("POST", f"{self.host}/api/pull", json={"name": model, "stream": True}) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", errors="replace")
                    raise RuntimeError(f"모델 다운로드 실패 (HTTP {resp.status_code}): {body[:200]}")
                async for line in resp.aiter_lines():
                    raw = line.strip()
                    if not raw:
                        continue
                    try:
                        ev = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if ev.get("error"):
                        raise RuntimeError(f"모델 다운로드 오류: {ev['error']}")
                    st_txt = str(ev.get("status") or "")
                    total = int(ev.get("total") or 0)
                    completed = int(ev.get("completed") or 0)
                    if total > 0 and completed >= 0:
                        ratio = min(1.0, completed / total)
                        pct = 35 + int(ratio * 60)
                        done_gb = completed / (1024 ** 3)
                        tot_gb = total / (1024 ** 3)
                        self.state.progress = min(96, pct)
                        self.state.message = f"{model} 다운로드 중 ({done_gb:.2f} / {tot_gb:.2f} GB · {int(ratio * 100)}%)"
                    elif st_txt:
                        if "verifying" in st_txt.lower():
                            self.state.progress = 97
                            self.state.message = f"{model} 무결성 확인 중..."
                        elif "success" in st_txt.lower():
                            self.state.progress = 99
                            self.state.message = f"{model} 준비 완료!"

    def activate_in_db(self, db: Any, model: str) -> None:
        """Configure the church app to use local 0-won Ollama seamlessly."""
        db.set_setting("ai_connection_mode", "api")
        db.set_setting("ai_api_provider", "openai_compatible")
        db.set_setting("ai_api_base_url", OLLAMA_OPENAI_BASE)
        db.set_setting("ai_api_model", model.strip())

    def start_setup(self, db: Any, model: str) -> dict[str, Any]:
        """Launch 1-click background setup: install Ollama -> start -> pull model -> activate."""
        clean_model = (model or "").strip() or _recommended_model_for_ram(self._ram_gb)
        if self._task and not self._task.done():
            return {"ok": True, "already_running": True, "setup_state": self.state.to_dict()}

        self.state = OllamaSetupState(
            status="installing",
            progress=3,
            model=clean_model,
            message=f"로컬 무료 AI({clean_model}) 준비를 시작합니다...",
            error="",
        )

        async def _runner() -> None:
            try:
                if not find_ollama_binary():
                    running, _ = await self.probe_running()
                    if not running:
                        await self._install_ollama_windows()

                self.state.status = "starting"
                self.state.progress = max(self.state.progress, 32)
                self.state.message = "로컬 AI 엔진(Ollama)을 시작하고 있습니다..."
                ok_run = await self.ensure_running(wait_sec=20)
                if not ok_run:
                    raise RuntimeError("Ollama 엔진을 시작하지 못했습니다. PC를 재시작하거나 Ollama 앱을 한 번 실행해 주세요.")

                # Skip pull if model is already present locally
                _, existing = await self.probe_running()
                existing_names = {m["name"] for m in existing}
                already_has = clean_model in existing_names or f"{clean_model}:latest" in existing_names
                if not already_has:
                    await self._pull_model(clean_model)

                self.activate_in_db(db, clean_model)
                self.state.status = "ready"
                self.state.progress = 100
                self.state.message = f"완료! 이제 인터넷·토큰 비용 없이 '{clean_model}' 로컬 무료 AI로 답변합니다."
                self.state.error = ""
            except Exception as exc:
                self.state.status = "error"
                self.state.error = str(exc)
                self.state.message = "로컬 AI 준비 중 문제가 발생했습니다."

        self._task = asyncio.create_task(_runner())
        return {"ok": True, "started": True, "setup_state": self.state.to_dict()}
