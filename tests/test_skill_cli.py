from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL_CLI = ROOT / "skills" / "grounded-doc-search" / "scripts" / "doc_skill_cli.py"


def _run_cli(args: list[str], env: dict[str, str] | None = None) -> dict | list:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    p = subprocess.run(
        [sys.executable, "-X", "utf8", str(SKILL_CLI), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=full_env,
        check=True,
    )
    return json.loads(p.stdout)


def test_skill_cli_custom_notebook_e2e(tmp_path: Path):
    env = {"CHURCH_SEARCH_DATA_DIR": str(tmp_path / "skill_data")}
    sample_dir = tmp_path / "docs"
    sample_dir.mkdir()
    (sample_dir / "policy.txt").write_text(
        "제1조 (휴가 규정)\n전임 교역자는 연 14일의 정기 휴가를 사용할 수 있으며 당회장 승인을 받는다.\n",
        encoding="utf-8",
    )

    init_out = _run_cli(["init-notebook", "샘플 정책실", "--id", "sample-nb"], env=env)
    assert init_out["status"] == "created"

    ing_out = _run_cli(["ingest", str(sample_dir), "--notebook", "sample-nb"], env=env)
    assert ing_out["ingested_count"] == 1

    hit = _run_cli(["search", "전임 교역자 정기 휴가 일수", "--notebook", "sample-nb"], env=env)
    assert hit["has_evidence"] is True
    assert "14일" in hit["chunks"][0]["content"]

    miss = _run_cli(["search", "제주도 항공권 할인 코드", "--notebook", "sample-nb"], env=env)
    assert miss["has_evidence"] is False


def test_skill_cli_against_default_church_corpus(tmp_path: Path):
    hit = _run_cli(["search", "장로 후보자 추천 나이"])
    assert hit["has_evidence"] is True
    assert len(hit["chunks"]) >= 1

    forms = _run_cli(["list-forms", "--query", "신청서"])
    assert len(forms) >= 1
    out_pdf = tmp_path / "skill_form.pdf"
    ext = _run_cli(["extract-form", forms[0]["id"], "--format", "pdf", "--out", str(out_pdf)])
    assert ext["ok"] is True and out_pdf.exists() and out_pdf.stat().st_size > 1000
