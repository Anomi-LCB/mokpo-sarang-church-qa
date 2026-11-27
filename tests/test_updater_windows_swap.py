from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from server.updater import _build_windows_swap_script


def test_updater_does_not_combine_detached_and_create_no_window() -> None:
    """Regression test: Windows powershell.exe silently aborts when DETACHED_PROCESS | CREATE_NO_WINDOW are combined."""
    updater_src = (Path(__file__).resolve().parent.parent / "server" / "updater.py").read_text(encoding="utf-8")
    ollama_src = (Path(__file__).resolve().parent.parent / "server" / "ollama_manager.py").read_text(encoding="utf-8")
    assert '"DETACHED_PROCESS"' not in updater_src and ".DETACHED_PROCESS" not in updater_src
    assert '"DETACHED_PROCESS"' not in ollama_src and ".DETACHED_PROCESS" not in ollama_src
    assert "CREATE_NEW_PROCESS_GROUP" in updater_src


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only PowerShell swap test")
def test_windows_swap_script_executes_cleanly_with_korean_and_ampersand_path(tmp_path: Path) -> None:
    """Verify the generated PowerShell swap script runs cleanly via CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    on a real path containing Korean characters, spaces, and '&' (목포사랑의교회 행정Q&A), preserving data/ untouched."""
    app_dir = tmp_path / "목포사랑의교회 행정Q&A"
    internal_dir = app_dir / "_internal"
    data_dir = app_dir / "data"
    updates_dir = data_dir / "updates"
    stage_dir = updates_dir / "staging_v4.3.1"
    rollback_dir = updates_dir / "rollback_prev"
    log_file = updates_dir / "update_apply.log"

    internal_dir.mkdir(parents=True)
    updates_dir.mkdir(parents=True)
    stage_dir.mkdir(parents=True)

    # Seed old binaries + precious user DB
    (app_dir / "목포사랑의교회 행정Q&A.exe").write_text("OLD_EXE", encoding="utf-8")
    (internal_dir / "ver.txt").write_text("4.0.0", encoding="utf-8")
    (app_dir / "사용안내.txt").write_text("OLD_README", encoding="utf-8")
    (data_dir / "church_search.db").write_text("PRECIOUS_USER_DATA", encoding="utf-8")

    # Seed new staged binaries
    (stage_dir / "목포사랑의교회 행정Q&A.exe").write_text("NEW_EXE_431", encoding="utf-8")
    (stage_dir / "_internal").mkdir()
    (stage_dir / "_internal" / "ver.txt").write_text("4.3.1", encoding="utf-8")
    (stage_dir / "사용안내.txt").write_text("NEW_README_431", encoding="utf-8")

    # Build swap script using a fake dead PID & an existing dummy executable name that won't launch a GUI
    # We test swap + log execution directly by replacing Start-Process of the fake exe with a benign no-op
    script = _build_windows_swap_script(
        pid=999999,
        app_dir=app_dir,
        staging_dir=stage_dir,
        rollback_dir=rollback_dir,
        log_file=log_file,
        port=19999,
        exe_name="목포사랑의교회 행정Q&A.exe",
    )
    # In this unit test, make health check pass immediately so we verify the swap without starting a dummy text file as exe
    script = script.replace(
        "Start-Process -FilePath $newExe -WorkingDirectory $AppDir",
        "Write-Log 'Test mock launch OK'",
    ).replace(
        "$healthy = $false",
        "$healthy = $true",
    ).replace(
        "for ($j = 0; $j -lt 25; $j++) {",
        "for ($j = 0; $j -lt 0; $j++) {",
    )

    ps_file = Path(tempfile.gettempdir()) / f"church_qa_test_swap_{tmp_path.name}.ps1"
    ps_file.write_text(script, encoding="utf-8-sig")
    try:
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        proc = subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-File",
                str(ps_file),
            ],
            cwd=tempfile.gettempdir(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
        )
        rc = proc.wait(timeout=20)
        assert rc == 0, f"Swap script failed rc={rc}, log={log_file.read_text('utf-8') if log_file.exists() else 'NONE'}"
        assert log_file.exists(), "Swap script did not execute (update_apply.log missing!)"
        log_txt = log_file.read_text(encoding="utf-8")
        assert "Health check PASSED!" in log_txt
        # Verify atomic binary replacement succeeded
        assert (app_dir / "목포사랑의교회 행정Q&A.exe").read_text(encoding="utf-8") == "NEW_EXE_431"
        assert (app_dir / "_internal" / "ver.txt").read_text(encoding="utf-8") == "4.3.1"
        assert (app_dir / "사용안내.txt").read_text(encoding="utf-8") == "NEW_README_431"
        # Verify user data/ is 100% untouched!
        assert (data_dir / "church_search.db").read_text(encoding="utf-8") == "PRECIOUS_USER_DATA"
    finally:
        ps_file.unlink(missing_ok=True)
