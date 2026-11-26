from __future__ import annotations

import zipfile
from pathlib import Path

import docx
import openpyxl
import pytest

from core.config import DEFAULT_NOTEBOOK_ID
from core.database import Database
from core.ingest import ingest_file
from core.retriever import retrieve


def test_default_church_corpus_indexed_cleanly():
    db = Database()
    docs = db.list_documents(DEFAULT_NOTEBOOK_ID)
    assert len(docs) == 4, f"Expected 4 church PDFs, got {len(docs)}"
    by_title = {d["title"]: d for d in docs}

    assert "대한예수교장로회 총회헌법 (2000)" in by_title
    assert "목포사랑의교회 정관" in by_title
    assert "2025년 사랑의교회 시행세칙" in by_title
    assert "총회헌법해설서 (2012)" in by_title

    const_doc = by_title["대한예수교장로회 총회헌법 (2000)"]
    assert const_doc["page_count"] == 344
    assert const_doc["ocr_pages"] == 344
    assert const_doc["total_chars"] > 180_000

    # Verify zero HWP \x01 control characters remain in chunks
    with db.connect() as conn:
        bad = conn.execute(
            "SELECT COUNT(*) AS cnt FROM chunks WHERE notebook_id = ? AND content LIKE ?",
            (DEFAULT_NOTEBOOK_ID, "%\x01%"),
        ).fetchone()["cnt"]
    assert bad == 0


@pytest.mark.parametrize(
    "query,expected_doc_substr",
    [
        ("무임 장로 제직회 참여 규정", "총회헌법"),
        ("권찰 임기와 구역 심방 임무", "총회헌법"),
        ("장로 후보자 추천 나이", "시행세칙"),
        ("교인의 구분 원입교인 학습교인", "정관"),
        ("유급직원의 조건", "시행세칙"),
        ("재심 청원서 권징 서식", "총회헌법해설서"),
    ],
)
def test_church_retrieval_accuracy(query: str, expected_doc_substr: str):
    db = Database()
    res = retrieve(db, DEFAULT_NOTEBOOK_ID, query, top_k=8)
    assert res.has_evidence is True, f"Expected evidence for: {query}"
    assert len(res.chunks) >= 1
    doc_titles = [c["doc_title"] for c in res.chunks]
    assert any(expected_doc_substr in t for t in doc_titles), f"Expected '{expected_doc_substr}' in {doc_titles}"


def test_universal_multi_format_ingestion(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CHURCH_SEARCH_DATA_DIR", str(tmp_path / "data"))
    db = Database(db_path=tmp_path / "data" / "test.db")
    db.create_notebook("nb-test", "범용 자료실 테스트")

    # 1. TXT
    txt_file = tmp_path / "meeting.txt"
    txt_file.write_text("제1조 (회의 원칙)\n당회 정기 회의는 매월 셋째 주일 오후 2시에 소집한다.\n", encoding="utf-8")

    # 2. DOCX
    docx_file = tmp_path / "guide.docx"
    d = docx.Document()
    d.add_paragraph("차량 운행 안내: 교회 버스는 주일 오전 8시 30분에 출발합니다.")
    d.save(str(docx_file))

    # 3. XLSX
    xlsx_file = tmp_path / "budget.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "예산표"
    ws.append(["부서명", "배정예산", "담당자"])
    ws.append(["청년부", "500만원", "김전도사"])
    wb.save(str(xlsx_file))

    # 4. HWPX (minimal valid ZIP+OWPML XML)
    hwpx_file = tmp_path / "notice.hwpx"
    with zipfile.ZipFile(hwpx_file, "w") as z:
        z.writestr(
            "Contents/section0.xml",
            '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
            'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
            "<hp:p><hp:t>특별새벽기도회는 11월 첫째 주 월요일 오전 5시에 본당에서 열립니다.</hp:t></hp:p>"
            "</hs:sec>",
        )

    for f in (txt_file, docx_file, xlsx_file, hwpx_file):
        ing = ingest_file(db, "nb-test", f)
        assert len(ing) == 1 and ing[0]["status"] == "ready"

    assert retrieve(db, "nb-test", "당회 정기 회의 소집 시간").has_evidence is True
    assert retrieve(db, "nb-test", "교회 버스 주일 출발 시간").has_evidence is True
    assert retrieve(db, "nb-test", "청년부 배정예산 담당자").has_evidence is True
    assert retrieve(db, "nb-test", "특별새벽기도회 본당 시간").has_evidence is True
    assert retrieve(db, "nb-test", "화성 탐사선 발사 일정").has_evidence is False
