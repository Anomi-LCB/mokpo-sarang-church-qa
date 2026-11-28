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
        "--add-data",
        f"{icon_ico};packaging/windows",
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
        "--collect-all",
        "webview",
        "--collect-all",
        "pythonnet",
        "--collect-all",
        "clr_loader",
        "--hidden-import",
        "webview.platforms.winforms",
        "--hidden-import",
        "webview.platforms.edgechromium",
        "--hidden-import",
        "clr",
        "--hidden-import",
        "multipart",
        "--hidden-import",
        "python_multipart",
        "--hidden-import",
        "email.mime.multipart",
        "--hidden-import",
        "kiwipiepy",
        "--hidden-import",
        "kiwipiepy_model",
        "--collect-data",
        "kiwipiepy_model",
        "--collect-binaries",
        "kiwipiepy",
        "--hidden-import",
        "onnxruntime",
        "--hidden-import",
        "tokenizers",
        "--hidden-import",
        "huggingface_hub",
        "--hidden-import",
        "pptx",
        "--hidden-import",
        "pptx.oxml",
        "--collect-data",
        "pptx",
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
            ignore=shutil.ignore_patterns("page_previews", "models", "*.tmp", "*_SKILL.md", "_unzip_*"),
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
        "  목포사랑의교회 행정Q&A (v4.5.0)\n"
        "========================================================\n\n"
        "1. 개인용 로컬 Windows 실행 프로그램:\n"
        "   - '목포사랑의교회 행정Q&A.exe' 를 실행하면 PIN 입력이나 관리자 권한 없이 내 PC에서\n"
        "     전용 독립 Windows 앱 창이 즉시 열리며, 인터넷·API 키 없이도 100% 로컬 검색이 바로 작동합니다.\n"
        "   - 작업표시줄에 고정해도 웹사이트가 아닌 전용 앱 아이콘 그대로 고정되어 실행됩니다.\n"
        "   - 창 우측 상단 닫기(×)를 누르면 일반 PC 프로그램처럼 백그라운드 프로세스 없이 깔끔하게 종료됩니다.\n"
        "     (스마트폰 연결용으로 백그라운드 서버를 유지하려면 [설정 → 화면 · AI 엔진]에서 켤 수 있습니다.)\n\n"
        "2. 토큰 0원 로컬 검색 + 선택형 무료 AI (Google Gemini / 오프라인 Ollama):\n"
        "   - PC 로컬 내장 엔진 v4.0(Kiwi 형태소 · 계층 청킹 · 교차참조 그래프)이 0.04초 만에 원문 조항을 추출합니다.\n"
        "   - 자연스러운 문장 요약이 필요하면 [설정 → 화면 · AI 엔진]에서 무료 Google Gemini API 또는\n"
        "     평생 0원 오프라인 로컬 AI(Ollama)를 1클릭으로 연결할 수 있습니다.\n\n"
        "3. 자료 라이브러리(서고) · 작업대 · 빠른 검색(Ctrl+K) · 다크 모드:\n"
        "   - 왼쪽 [자료 라이브러리]에서 자료를 검색·분류·고정(Pin)하여 작업대에 불러올 수 있습니다.\n"
        "   - 상단 해/달 아이콘으로 라이트·다크 모드를 즉시 전환할 수 있습니다.\n"
        "   - Ctrl+K로 전체 문서·서식·대화·표준화실 게시글을 한 번에 찾아 이동할 수 있습니다.\n\n"
        "4. 선택형 스마트폰 연결 및 협업 그룹 (외부 접속 시 PIN 보안 자동 유지):\n"
        "   - 내 PC에서는 PIN 없이 바로 열리지만, 외부 스마트폰·다른 PC 접속 시에는 항상 PIN 인증이 적용됩니다.\n"
        "   - 초기 외부 접속용 PIN (설정 → 보안 · PIN 탭에서 즉시 변경 가능):\n"
        "     · 교역자/행정팀 PIN: 1234\n"
        "     · 관리자 PIN: 0000\n",
        encoding="utf-8",
    )
    print(f"Windows portable package ready: {out_app_dir / (APP_EXEC_NAME + '.exe')}", flush=True)


if __name__ == "__main__":
    main()
