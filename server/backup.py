from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from core.config import get_data_dir

MAX_BACKUPS = 12


def get_backups_dir() -> Path:
    p = get_data_dir() / "backups"
    p.mkdir(parents=True, exist_ok=True)
    return p


def create_backup(db_path: Path, reason: str = "manual") -> dict[str, Any]:
    """Safely snapshot SQLite DB (WAL-safe via sqlite3 online backup API) and rotate old copies."""
    bdir = get_backups_dir()
    safe_reason = re.sub(r"[^a-zA-Z0-9_-]+", "", reason)[:20] or "manual"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = bdir / f"backup_{stamp}_{safe_reason}.db"

    src = sqlite3.connect(str(db_path), timeout=30.0)
    dst = sqlite3.connect(str(out_path))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    # Rotate keeping newest MAX_BACKUPS files
    all_files = sorted(bdir.glob("backup_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in all_files[MAX_BACKUPS:]:
        try:
            old.unlink(missing_ok=True)
        except OSError:
            pass

    st = out_path.stat()
    return {
        "name": out_path.name,
        "size_bytes": st.st_size,
        "created_at": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
    }


def ensure_daily_backup(db_path: Path) -> None:
    if not db_path.exists() or db_path.stat().st_size < 4096:
        return
    today_prefix = f"backup_{datetime.now().strftime('%Y%m%d')}_"
    bdir = get_backups_dir()
    if any(p.name.startswith(today_prefix) for p in bdir.glob("backup_*.db")):
        return
    try:
        create_backup(db_path, reason="daily")
    except Exception:
        pass


def list_backups() -> list[dict[str, Any]]:
    bdir = get_backups_dir()
    files = sorted(bdir.glob("backup_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for f in files:
        st = f.stat()
        out.append(
            {
                "name": f.name,
                "size_bytes": st.st_size,
                "created_at": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            }
        )
    return out


def get_backup_path(name: str) -> Path | None:
    safe_name = Path(name).name
    if not safe_name.startswith("backup_") or not safe_name.endswith(".db"):
        return None
    cand = get_backups_dir() / safe_name
    return cand if cand.exists() and cand.is_file() else None


def restore_backup(db_path: Path, name: str) -> dict[str, Any]:
    target = get_backup_path(name)
    if not target:
        raise FileNotFoundError("백업 파일을 찾을 수 없습니다.")
    # Always snapshot current state before overwriting
    safety = create_backup(db_path, reason="pre_restore")
    src = sqlite3.connect(str(target))
    dst = sqlite3.connect(str(db_path), timeout=30.0)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return {"restored": target.name, "safety_backup": safety["name"]}
