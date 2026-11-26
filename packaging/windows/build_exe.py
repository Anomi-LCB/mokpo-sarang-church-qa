from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
APP_EXEC_NAME = "목포사랑의교회 행정Q&A"


def main() -> None:
    venv_py = ROOT / ".venv" / "Scripts" / "python.exe"
    py = str(venv_py if venv_py.exists() else sys.executable)

    frontend_dist = ROOT / "frontend" / "dist"
    if not (frontend_dist / "index.html").exists():
        raise RuntimeError("frontend/dist 가 없습니다. 먼저 프론트엔드를 빌드하세요.")

    icon_ico = ROOT / "packaging" / "windows" / "app_icon.ico"
    icon_png = ROOT / "packaging" / "windows" / "app_icon.png"
    dist_dir = ROOT / "dist"
    build_dir = ROOT / "build"

    cmd = [
        py,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--noconsole",
        "--name",
        APP_EXEC_NAME,
        "--icon",
        str(icon_ico),
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(build_dir),
        "--add-data",
        f"{frontend_dist};frontend/dist",
        "--add-data",
        f"{icon_png};packaging/windows",
        "--hidden-import",
        "uvicorn.logging",
        "--hidden-import",
        "uvicorn.loops.auto",
        "--hidden-import",
        "uvicorn.protocols.http.auto",
        "--hidden-import",
        "uvicorn.protocols.websockets.auto",
        "--hidden-import",
        "uvicorn.lifespan.on",
        "--hidden-import",
        "pystray._win32",
        "--hidden-import",
        "multipart",
        "--hidden-import",
        "python_multipart",
        "--hidden-import",
        "email.mime.multipart",
        str(ROOT / "packaging" / "windows" / "launcher.py"),
    ]
    print("Running PyInstaller:", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=str(ROOT), check=True)

    # Copy pre-indexed data/ (DB, PDFs, exports, APK) next to the .exe for instant portable startup
    out_app_dir = dist_dir / APP_EXEC_NAME
    src_data = ROOT / "data"
    dst_data = out_app_dir / "data"
    if src_data.exists():
        if dst_data.exists():
            shutil.rmtree(dst_data)
        shutil.copytree(
            src_data,
            dst_data,
            ignore=shutil.ignore_patterns("page_previews", "*.tmp", "*_SKILL.md", "_unzip_*"),
        )
        print(f"Copied pre-indexed data/ to {dst_data}", flush=True)

    # Ensure branded APK is inside data/downloads/
    apk_src = dist_dir / "목포사랑의교회-행정Q&A.apk"
    if apk_src.exists():
        dl_dir = dst_data / "downloads"
        dl_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(apk_src, dl_dir / "목포사랑의교회-행정Q&A.apk")
        shutil.copy2(apk_src, dl_dir / "church-search.apk")

    readme = out_app_dir / "사용안내.txt"
    readme.write_text(
        "========================================================\n"
        "  목포사랑의교회 행정Q&A (v3.0.0)\n"
        "========================================================\n\n"
        "1. 실행 방법:\n"
        "   - '목포사랑의교회 행정Q&A.exe' 를 더블클릭하면 앱 창이 열리며 백그라운드 팀 서버가 시작됩니다.\n"
        "   - 앱 창을 닫아도 우측 하단 작업표시줄(트레이 아이콘)에서 서버가 유지되어\n"
        "     교역자/행정팀 스마트폰 접속이 끊어지지 않습니다.\n\n"
        "2. 자료 라이브러리(서고) · 작업대 · 빠른 검색(Ctrl+K):\n"
        "   - 왼쪽 [자료 라이브러리]에서 수십~수백 건의 자료를 검색·분류·고정(Pin)하여 작업대에 불러올 수 있습니다.\n"
        "   - 작업대에서 체크(파란 선택 표시)한 자료만 검색 범위로 사용되며, 작업대에서 내려도 라이브러리에는 안전하게 보관됩니다.\n"
        "   - Ctrl+K로 전체 문서·서식·대화·표준화실 게시글을 한 번에 찾아 이동할 수 있습니다.\n\n"
        "3. 협업 그룹 · 공동 대화 · 그룹 전용 표준화실 (실시간 자동 동기화):\n"
        "   - 상단 [그룹] 메뉴에서 6자리 초대 코드·링크(QR) 또는 직접 초대로 그룹에 참여할 수 있습니다.\n"
        "   - 그룹 개설은 관리자 및 관리자에게 '그룹 개설 권한'을 위임받은 교역자만 가능합니다.\n"
        "   - 그룹 공동 대화와 그룹 전용 표준화실은 참여자 모두가 실시간으로 함께 질문·투표·검수할 수 있습니다.\n\n"
        "4. AI 연결 방식 자유 선택 (CLI · API · 오프라인) 및 선택형 자동 업데이트:\n"
        "   - [설정 → 화면 · AI 엔진]에서 구독 CLI(Claude/Codex/Gemini) 또는 API 키 직접 연결(Anthropic/OpenAI/Gemini/로컬 Ollama)을 자유롭게 선택할 수 있습니다.\n"
        "   - 새 버전 출시 시 상단 배지에서 변경 내역을 확인한 뒤 원하실 때만 1클릭으로 안전 업데이트할 수 있습니다.\n\n"
        "5. 초기 PIN 번호 (설정 → 보안 탭에서 즉시 변경 가능):\n"
        "   - 교역자/행정팀 PIN: 1234\n"
        "   - 관리자 PIN: 0000\n",
        encoding="utf-8",
    )
    print(f"Windows portable package ready: {out_app_dir / (APP_EXEC_NAME + '.exe')}", flush=True)


if __name__ == "__main__":
    main()
