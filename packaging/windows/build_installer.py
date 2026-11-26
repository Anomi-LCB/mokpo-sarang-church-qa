from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
BUILD_SEED = ROOT / "build" / "installer_seed"
APP_EXEC_NAME = "목포사랑의교회 행정Q&A"


def _find_iscc() -> Path:
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
    ]
    which = shutil.which("ISCC")
    if which:
        candidates.insert(0, Path(which))
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError("Inno Setup 6 (ISCC.exe)를 찾을 수 없습니다.")


def _prepare_sanitized_seed() -> Path:
    """Create a clean, portable church dataset seed (all 919p OCR + 60 forms, zero personal chats/logs/feedback)."""
    if BUILD_SEED.exists():
        shutil.rmtree(BUILD_SEED)
    BUILD_SEED.mkdir(parents=True, exist_ok=True)

    src_db = ROOT / "data" / "church_search.db"
    if not src_db.exists():
        raise FileNotFoundError(f"기본 색인 DB가 없습니다: {src_db}")

    dst_db = BUILD_SEED / "church_search.db"
    src_conn = sqlite3.connect(str(src_db))
    dst_conn = sqlite3.connect(str(dst_db))
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()

    conn = sqlite3.connect(str(dst_db))
    try:
        conn.execute("DELETE FROM chat_messages")
        conn.execute("DELETE FROM chat_sessions")
        conn.execute("DELETE FROM audit_logs")
        conn.execute("DELETE FROM feedback_reports")
        for tbl in (
            "std_votes",
            "std_proposal_options",
            "std_proposals",
            "std_comments",
            "std_cross_memory",
            "std_publications",
            "std_submissions",
            "std_boards",
            "collab_group_members",
            "collab_groups",
            "member_directory",
        ):
            try:
                conn.execute(f"DELETE FROM {tbl}")
            except sqlite3.OperationalError:
                pass
        conn.execute("DELETE FROM app_settings")
        try:
            conn.execute("UPDATE documents SET is_pinned_default = 1 WHERE priority >= 70")
        except sqlite3.OperationalError:
            pass
        rows = conn.execute("SELECT id, notebook_id, stored_path FROM documents").fetchall()
        for doc_id, nb_id, stored in rows:
            fname = Path(stored).name
            portable_rel = f"notebooks/{nb_id}/docs/{fname}"
            conn.execute("UPDATE documents SET stored_path = ? WHERE id = ?", (portable_rel, doc_id))
        conn.commit()
        conn.execute("VACUUM")
    finally:
        conn.close()

    conn_r = sqlite3.connect(str(dst_db))
    active_names = {Path(r[0]).name for r in conn_r.execute("SELECT stored_path FROM documents").fetchall()}
    conn_r.close()

    src_nb = ROOT / "data" / "notebooks" / "mokpo-sarang-church" / "docs"
    dst_nb = BUILD_SEED / "notebooks" / "mokpo-sarang-church" / "docs"
    dst_nb.mkdir(parents=True, exist_ok=True)
    copied = 0
    for f in src_nb.iterdir():
        if f.is_file() and f.name in active_names:
            shutil.copy2(f, dst_nb / f.name)
            copied += 1

    print(
        f"[installer-seed] sanitized DB ({dst_db.stat().st_size / (1024*1024):.2f} MB) + {copied} docs ready",
        flush=True,
    )
    return BUILD_SEED


def main() -> None:
    exe_dir = ROOT / "dist" / APP_EXEC_NAME
    if not (exe_dir / f"{APP_EXEC_NAME}.exe").exists():
        raise FileNotFoundError(f"dist/{APP_EXEC_NAME}/{APP_EXEC_NAME}.exe 가 없습니다. 먼저 build_exe.py 를 실행하세요.")

    apk_path = ROOT / "dist" / "목포사랑의교회-행정Q&A.apk"
    if not apk_path.exists():
        raise FileNotFoundError(f"{apk_path} 가 없습니다. 먼저 android/build_apk.py 를 실행하세요.")

    tailscale_msi = ROOT / "packaging" / "windows" / "redist" / "tailscale-setup-amd64.msi"
    if not tailscale_msi.exists():
        raise FileNotFoundError(f"오프라인 Tailscale MSI가 없습니다: {tailscale_msi}")

    iscc = _find_iscc()
    _prepare_sanitized_seed()

    # Ensure UTF-8 BOM on installer.iss so Korean renders crisply in Inno Setup UI
    iss_path = ROOT / "packaging" / "windows" / "installer.iss"
    iss_txt = iss_path.read_text(encoding="utf-8-sig")
    iss_path.write_text(iss_txt, encoding="utf-8-sig")

    kor_isl = iscc.parent / "Languages" / "Korean.isl"
    define_args = [
        f"/DProjectRoot={ROOT}",
        f"/DSeedDir={BUILD_SEED}",
        f"/DHasKoreanIsl={'1' if kor_isl.exists() else '0'}",
    ]
    cmd = [str(iscc), *define_args, str(iss_path)]
    print("Running ISCC:", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=str(ROOT), check=True)

    out_setup = ROOT / "dist" / "목포사랑의교회 행정Q&A 설치.exe"
    if not out_setup.exists():
        raise RuntimeError(f"설치 파일이 생성되지 않았습니다: {out_setup}")
    size_mb = out_setup.stat().st_size / (1024 * 1024)
    print(f"\nOfficial Windows Installer ready: {out_setup} ({out_setup.stat().st_size:,} bytes / {size_mb:.2f} MB)", flush=True)


if __name__ == "__main__":
    main()
