from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("PYTHONUTF8", "1")

APP_NAME = "목포사랑의교회 행정Q&A"
APP_VERSION = "2.4.1"
DEFAULT_UPDATE_REPO = "Anomi-LCB/mokpo-sarang-church-qa"
DEFAULT_UPDATE_MANIFEST_URL = (
    f"https://github.com/{DEFAULT_UPDATE_REPO}/releases/latest/download/update-manifest.json"
)
DEFAULT_UPDATE_RELEASES_API = (
    f"https://api.github.com/repos/{DEFAULT_UPDATE_REPO}/releases/latest"
)
DEFAULT_PORT = 8765
DEFAULT_NOTEBOOK_ID = "mokpo-sarang-church"
DEFAULT_NOTEBOOK_NAME = "목포사랑의교회 법규·행정"
DEFAULT_NOTEBOOK_DESC = (
    "대한예수교장로회 총회헌법(2000), 총회헌법해설서(2012), "
    "목포사랑의교회 정관, 2025년 사랑의교회 시행세칙 기반 근거 전용 검색기"
)

DEFAULT_SYSTEM_RULES = """당신은 목포사랑의교회 교역자와 행정팀을 돕는 '교회 법규·행정 근거 전용 AI'입니다.
반드시 제공된 [근거 자료]에 있는 내용만을 토대로 답변하세요.

[문서 법규 위계 및 역할]
1. 대한예수교장로회 총회헌법 (최상위 교단 법규: 신조·요리문답, 정치, 권징, 예배모범, 헌법적 규칙)
2. 목포사랑의교회 정관 (개교회 최고 자치법규 — 교회 내 타 규정과 충돌 시 최우선)
3. 2025년 사랑의교회 시행세칙 (행정, 인사·취업규칙, 차량, 교육선교국, 선교·봉사, 셀·목회 매뉴얼)
4. 총회헌법해설서 (헌법 조항의 취지·유권해석·문답 해설 및 권징·행정 서식)

[핵심 원칙]
1. 근거 없는 추측 절대 금지: [근거 자료]에서 답을 뒷받침할 내용을 찾을 수 없으면 지어내지 말고 반드시 "제공된 자료에서 해당 정보를 찾을 수 없습니다."라고 명확히 답하세요.
2. 실무적 명확성: 근거가 있다면 단순히 조문만 기계적으로 나열하지 말고, 질문의 상황에 맞게 알기 쉽게 핵심을 정리하고 관련 법규 간 연결(예: 정관 원칙 + 시행세칙 세부 절차 + 헌법 해설)까지 깔끔하게 안내하세요.
3. 출처 정확성: 모든 핵심 설명에는 반드시 정확한 출처([문서명] 장·조 또는 페이지)를 밝히세요.
4. 가독성: 번호(1., 2.)나 항/호(①, ②)가 나오면 반드시 줄을 바꾸어 보기 좋게 정리하세요.
5. 태그 금지: [source], <cite> 같은 시스템 내부 태그를 출력하지 마세요.
"""

DEFAULT_HIERARCHY = [
    {"key": "헌법", "label": "대한예수교장로회 총회헌법 (2000)", "priority": 100, "category": "교단 헌법"},
    {"key": "정관", "label": "목포사랑의교회 정관", "priority": 90, "category": "개교회 정관"},
    {"key": "시행세칙", "label": "2025년 사랑의교회 시행세칙", "priority": 80, "category": "행정·실무 규정"},
    {"key": "해설서", "label": "총회헌법해설서 (2012)", "priority": 70, "category": "헌법 해설·서식"},
]

SEED_ARCHIVES = [
    {
        "zip_name": "2000-총회헌법-ver.zip",
        "title": "대한예수교장로회 총회헌법 (2000)",
        "category": "교단 헌법",
        "priority": 100,
    },
    {
        "zip_name": "2020-목포사랑의교회-정관-ver.zip",
        "title": "목포사랑의교회 정관",
        "category": "개교회 정관",
        "priority": 90,
    },
    {
        "zip_name": "2025-사랑의교회-시행세칙-ver.zip",
        "title": "2025년 사랑의교회 시행세칙",
        "category": "행정·실무 규정",
        "priority": 80,
    },
    {
        "zip_name": "2012-총회헌법해설서-ver.zip",
        "title": "총회헌법해설서 (2012)",
        "category": "헌법 해설·서식",
        "priority": 70,
    },
]


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_resource_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent.parent


def get_data_dir() -> Path:
    override = os.environ.get("CHURCH_SEARCH_DATA_DIR")
    if override:
        p = Path(override).resolve()
    else:
        p = get_base_dir() / "data"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_db_path() -> Path:
    return get_data_dir() / "church_search.db"


def get_notebooks_dir() -> Path:
    p = get_data_dir() / "notebooks"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_docs_dir(notebook_id: str) -> Path:
    p = get_notebooks_dir() / notebook_id / "docs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_exports_dir() -> Path:
    p = get_data_dir() / "exports"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_ocr_cache_dir() -> Path:
    p = get_data_dir() / "ocr_cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_downloads_dir() -> Path:
    p = get_data_dir() / "downloads"
    p.mkdir(parents=True, exist_ok=True)
    return p


def resolve_stored_path(raw_path: str, notebook_id: str | None = None) -> str:
    """Resolve stored document paths portably across different PCs and install folders."""
    if not raw_path:
        return ""
    p = Path(raw_path)
    if p.exists():
        return str(p)
    data_dir = get_data_dir()
    if not p.is_absolute():
        cand = data_dir / p
        if cand.exists():
            return str(cand)
    norm = raw_path.replace("\\", "/")
    marker = "/notebooks/"
    if marker in norm:
        rel = "notebooks/" + norm.split(marker, 1)[1]
        cand = data_dir / rel
        if cand.exists():
            return str(cand)
    elif norm.startswith("notebooks/"):
        cand = data_dir / norm
        if cand.exists():
            return str(cand)
    if notebook_id:
        cand = data_dir / "notebooks" / notebook_id / "docs" / p.name
        if cand.exists():
            return str(cand)
    return raw_path
