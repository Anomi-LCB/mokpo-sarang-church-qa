from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_SKILL = ROOT / "skills" / "grounded-doc-search"


def main() -> None:
    targets = [
        ROOT / ".agents" / "skills" / "grounded-doc-search",
        Path.home() / ".gemini" / "config" / "skills" / "grounded-doc-search",
        Path.home() / ".claude" / "skills" / "grounded-doc-search",
    ]
    for dst in targets:
        if dst.exists():
            shutil.rmtree(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(SRC_SKILL, dst)
        print(f"Installed skill -> {dst}")


if __name__ == "__main__":
    main()
