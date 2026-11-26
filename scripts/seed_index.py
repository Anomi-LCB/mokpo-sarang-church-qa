from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.database import Database
from core.ingest import seed_default_church_notebook


def main() -> None:
    t0 = time.perf_counter()
    db = Database()
    print("=== 초기 4대 교회 법규·행정 문서 색인 시작 ===", flush=True)
    seed_default_church_notebook(db, archive_dir=ROOT, progress_cb=lambda m: print(m, flush=True))
    elapsed = time.perf_counter() - t0
    docs = db.list_documents("mokpo-sarang-church")
    forms = db.list_forms("mokpo-sarang-church")
    print(f"\n=== 완료 ({elapsed:.1f}초) ===", flush=True)
    for d in docs:
        print(
            f"  - {d['title']}: {d['page_count']}쪽 | OCR {d['ocr_pages']}쪽 | "
            f"{d['total_chars']:,}자 | 청크 {d['chunk_count']}개 | 서식/표 {d['form_count']}개",
            flush=True,
        )
    print(f"총 서식·표 카탈로그: {len(forms)}개", flush=True)


if __name__ == "__main__":
    main()
