from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from core.config import (
    DEFAULT_HIERARCHY,
    DEFAULT_NOTEBOOK_DESC,
    DEFAULT_NOTEBOOK_ID,
    DEFAULT_NOTEBOOK_NAME,
    DEFAULT_SYSTEM_RULES,
    get_db_path,
    resolve_stored_path,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


_KOR_PARTICLES = re.compile(
    r"(으로서|으로써|에서부터|으로부터|에게는|에서는|으로는|이라도|까지도|"
    r"에서|에게|으로|부터|까지|처럼|만큼|보다|라도|마저|조차|이나|든지|"
    r"은|는|이|가|을|를|의|에|로|과|와|도|만|께|며|고|서)$"
)
_WORD_RE = re.compile(r"[가-힣A-Za-z0-9]+")


def build_search_tokens(text: str) -> str:
    """Create hybrid Korean word + stem + character bigram tokens for FTS5."""
    if not text:
        return ""
    tokens: list[str] = []
    seen_bigrams: set[str] = set()
    for raw in _WORD_RE.findall(text):
        w = raw.lower()
        tokens.append(w)
        if len(w) >= 3 and any("\uac00" <= ch <= "\ud7a3" for ch in w):
            stem = _KOR_PARTICLES.sub("", w)
            if stem and stem != w and len(stem) >= 2:
                tokens.append(stem)
        # Add Korean character bigrams for compound-word & OCR-typo resilience
        kor_only = "".join(ch for ch in w if "\uac00" <= ch <= "\ud7a3")
        if len(kor_only) >= 2:
            for i in range(len(kor_only) - 1):
                bg = "bg_" + kor_only[i : i + 2]
                if bg not in seen_bigrams:
                    seen_bigrams.add(bg)
                    tokens.append(bg)
    return " ".join(tokens)


SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS notebooks (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    system_rules TEXT NOT NULL DEFAULT '',
    hierarchy_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    notebook_id TEXT NOT NULL,
    title TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    file_type TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '일반 자료',
    priority INTEGER NOT NULL DEFAULT 50,
    page_count INTEGER NOT NULL DEFAULT 0,
    ocr_pages INTEGER NOT NULL DEFAULT 0,
    total_chars INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'ready',
    error_msg TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (notebook_id) REFERENCES notebooks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL,
    notebook_id TEXT NOT NULL,
    page_no INTEGER NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    is_ocr INTEGER NOT NULL DEFAULT 0,
    has_table INTEGER NOT NULL DEFAULT 0,
    has_form INTEGER NOT NULL DEFAULT 0,
    UNIQUE (doc_id, page_no),
    FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL,
    notebook_id TEXT NOT NULL,
    page_start INTEGER NOT NULL,
    page_end INTEGER NOT NULL,
    heading TEXT NOT NULL DEFAULT '',
    section_path TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    search_tokens TEXT NOT NULL DEFAULT '',
    char_len INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    content,
    heading,
    search_tokens,
    doc_id UNINDEXED,
    notebook_id UNINDEXED,
    chunk_id UNINDEXED,
    tokenize='unicode61'
);

CREATE TABLE IF NOT EXISTS forms_catalog (
    id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    notebook_id TEXT NOT NULL,
    title TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '서식',
    form_type TEXT NOT NULL DEFAULT 'form',
    page_start INTEGER NOT NULL,
    page_end INTEGER NOT NULL,
    has_table INTEGER NOT NULL DEFAULT 0,
    sample_text TEXT NOT NULL DEFAULT '',
    fields_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id TEXT PRIMARY KEY,
    notebook_id TEXT NOT NULL,
    user_label TEXT NOT NULL DEFAULT '팀원',
    owner_id TEXT NOT NULL DEFAULT '',
    is_shared INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL DEFAULT '새 대화',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (notebook_id) REFERENCES notebooks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    actor_role TEXT NOT NULL DEFAULT '',
    actor_label TEXT NOT NULL DEFAULT '',
    client_ip TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'practical',
    citations_json TEXT NOT NULL DEFAULT '[]',
    forms_json TEXT NOT NULL DEFAULT '[]',
    verification_json TEXT NOT NULL DEFAULT '{}',
    provider TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL DEFAULT 'bug',
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    reporter_label TEXT NOT NULL DEFAULT '사용자',
    reporter_role TEXT NOT NULL DEFAULT 'member',
    client_ip TEXT NOT NULL DEFAULT '',
    device_info TEXT NOT NULL DEFAULT '',
    app_version TEXT NOT NULL DEFAULT '',
    context_info TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    creator_note TEXT NOT NULL DEFAULT '',
    relayed_remote INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS member_directory (
    owner_id TEXT PRIMARY KEY,
    label TEXT NOT NULL DEFAULT '교역자',
    role TEXT NOT NULL DEFAULT 'member',
    can_create_group INTEGER NOT NULL DEFAULT 0,
    recovery_code_hash TEXT NOT NULL DEFAULT '',
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collab_groups (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    invite_code TEXT NOT NULL UNIQUE,
    created_by_owner_id TEXT NOT NULL DEFAULT '',
    created_by_label TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collab_group_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    member_label TEXT NOT NULL DEFAULT '교역자',
    role TEXT NOT NULL DEFAULT 'member',
    joined_at TEXT NOT NULL,
    UNIQUE (group_id, owner_id),
    FOREIGN KEY (group_id) REFERENCES collab_groups(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_docs_notebook ON documents(notebook_id);
CREATE INDEX IF NOT EXISTS idx_pages_doc ON pages(doc_id, page_no);
CREATE INDEX IF NOT EXISTS idx_chunks_notebook_doc ON chunks(notebook_id, doc_id);
CREATE INDEX IF NOT EXISTS idx_forms_notebook ON forms_catalog(notebook_id);
CREATE INDEX IF NOT EXISTS idx_messages_session ON chat_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback_reports(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_group_members_owner ON collab_group_members(owner_id);
"""


class Database:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or get_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)
            # Safe idempotent column migrations for pre-existing DBs
            doc_cols = {r["name"] for r in conn.execute("PRAGMA table_info(documents)").fetchall()}
            if "is_pinned_default" not in doc_cols:
                conn.execute("ALTER TABLE documents ADD COLUMN is_pinned_default INTEGER NOT NULL DEFAULT 0")
                # Pin high-priority core church books by default on first upgrade
                conn.execute("UPDATE documents SET is_pinned_default = 1 WHERE priority >= 70")
            if "tags_json" not in doc_cols:
                conn.execute("ALTER TABLE documents ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]'")
            sess_cols = {r["name"] for r in conn.execute("PRAGMA table_info(chat_sessions)").fetchall()}
            if "owner_id" not in sess_cols:
                conn.execute("ALTER TABLE chat_sessions ADD COLUMN owner_id TEXT NOT NULL DEFAULT ''")
            if "is_shared" not in sess_cols:
                conn.execute("ALTER TABLE chat_sessions ADD COLUMN is_shared INTEGER NOT NULL DEFAULT 1")
            if "group_id" not in sess_cols:
                conn.execute("ALTER TABLE chat_sessions ADD COLUMN group_id TEXT NOT NULL DEFAULT ''")
            msg_cols = {r["name"] for r in conn.execute("PRAGMA table_info(chat_messages)").fetchall()}
            if "verification_json" not in msg_cols:
                conn.execute("ALTER TABLE chat_messages ADD COLUMN verification_json TEXT NOT NULL DEFAULT '{}'")
            if "author_label" not in msg_cols:
                conn.execute("ALTER TABLE chat_messages ADD COLUMN author_label TEXT NOT NULL DEFAULT ''")
            if "author_owner_id" not in msg_cols:
                conn.execute("ALTER TABLE chat_messages ADD COLUMN author_owner_id TEXT NOT NULL DEFAULT ''")

    def ensure_default_notebook(self) -> dict[str, Any]:
        nb = self.get_notebook(DEFAULT_NOTEBOOK_ID)
        if nb:
            return nb
        return self.create_notebook(
            notebook_id=DEFAULT_NOTEBOOK_ID,
            name=DEFAULT_NOTEBOOK_NAME,
            description=DEFAULT_NOTEBOOK_DESC,
            system_rules=DEFAULT_SYSTEM_RULES,
            hierarchy=DEFAULT_HIERARCHY,
        )

    # ---- Settings ----
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO app_settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # ---- Notebooks ----
    def list_notebooks(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT n.*,
                       (SELECT COUNT(*) FROM documents d WHERE d.notebook_id = n.id) AS doc_count,
                       (SELECT COUNT(*) FROM forms_catalog f WHERE f.notebook_id = n.id) AS form_count
                FROM notebooks n
                ORDER BY CASE WHEN n.id = ? THEN 0 ELSE 1 END, n.created_at ASC
                """,
                (DEFAULT_NOTEBOOK_ID,),
            ).fetchall()
            return [self._row_to_notebook(r) for r in rows]

    def get_notebook(self, notebook_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT n.*,
                       (SELECT COUNT(*) FROM documents d WHERE d.notebook_id = n.id) AS doc_count,
                       (SELECT COUNT(*) FROM forms_catalog f WHERE f.notebook_id = n.id) AS form_count
                FROM notebooks n WHERE n.id = ?
                """,
                (notebook_id,),
            ).fetchone()
            return self._row_to_notebook(row) if row else None

    def create_notebook(
        self,
        notebook_id: str,
        name: str,
        description: str = "",
        system_rules: str = "",
        hierarchy: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        ts = now_iso()
        rules = system_rules.strip() or (
            "반드시 제공된 [근거 자료] 안에서만 답변하세요. "
            "자료에 없는 내용은 지어내지 말고 '제공된 자료에서 해당 정보를 찾을 수 없습니다.'라고 명확히 답하세요. "
            "근거가 있다면 실무적으로 이해하기 쉽게 정리하고 정확한 출처(문서명, 페이지/항목)를 밝히세요."
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO notebooks(id, name, description, system_rules, hierarchy_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (notebook_id, name, description, rules, json.dumps(hierarchy or [], ensure_ascii=False), ts, ts),
            )
        return self.get_notebook(notebook_id)  # type: ignore[return-value]

    def update_notebook(
        self,
        notebook_id: str,
        name: str | None = None,
        description: str | None = None,
        system_rules: str | None = None,
        hierarchy: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        existing = self.get_notebook(notebook_id)
        if not existing:
            return None
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE notebooks
                SET name = ?, description = ?, system_rules = ?, hierarchy_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    name if name is not None else existing["name"],
                    description if description is not None else existing["description"],
                    system_rules if system_rules is not None else existing["system_rules"],
                    json.dumps(hierarchy if hierarchy is not None else existing["hierarchy"], ensure_ascii=False),
                    now_iso(),
                    notebook_id,
                ),
            )
        return self.get_notebook(notebook_id)

    def delete_notebook(self, notebook_id: str) -> bool:
        with self.connect() as conn:
            conn.execute("DELETE FROM chunks_fts WHERE notebook_id = ?", (notebook_id,))
            cur = conn.execute("DELETE FROM notebooks WHERE id = ?", (notebook_id,))
            return cur.rowcount > 0

    def _row_to_notebook(self, row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["hierarchy"] = json.loads(d.pop("hierarchy_json", "[]") or "[]")
        return d

    # ---- Documents ----
    def upsert_document(self, doc: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO documents(
                    id, notebook_id, title, original_filename, stored_path, file_type,
                    category, priority, page_count, ocr_pages, total_chars, status, error_msg, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    original_filename=excluded.original_filename,
                    stored_path=excluded.stored_path,
                    file_type=excluded.file_type,
                    category=excluded.category,
                    priority=excluded.priority,
                    page_count=excluded.page_count,
                    ocr_pages=excluded.ocr_pages,
                    total_chars=excluded.total_chars,
                    status=excluded.status,
                    error_msg=excluded.error_msg
                """,
                (
                    doc["id"],
                    doc["notebook_id"],
                    doc["title"],
                    doc["original_filename"],
                    doc["stored_path"],
                    doc["file_type"],
                    doc.get("category", "일반 자료"),
                    doc.get("priority", 50),
                    doc.get("page_count", 0),
                    doc.get("ocr_pages", 0),
                    doc.get("total_chars", 0),
                    doc.get("status", "ready"),
                    doc.get("error_msg", ""),
                    doc.get("created_at") or now_iso(),
                ),
            )

    def list_documents(self, notebook_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT d.*,
                       (SELECT COUNT(*) FROM chunks c WHERE c.doc_id = d.id) AS chunk_count,
                       (SELECT COUNT(*) FROM forms_catalog f WHERE f.doc_id = d.id) AS form_count
                FROM documents d
                WHERE d.notebook_id = ?
                ORDER BY d.priority DESC, d.created_at ASC
                """,
                (notebook_id,),
            ).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d["stored_path"] = resolve_stored_path(d.get("stored_path", ""), d.get("notebook_id"))
                d["tags"] = json.loads(d.pop("tags_json", "[]") or "[]")
                d["is_pinned_default"] = int(d.get("is_pinned_default", 0) or 0)
                out.append(d)
            return out

    def get_document(self, doc_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
            if not row:
                return None
            d = dict(row)
            d["stored_path"] = resolve_stored_path(d.get("stored_path", ""), d.get("notebook_id"))
            d["tags"] = json.loads(d.pop("tags_json", "[]") or "[]")
            d["is_pinned_default"] = int(d.get("is_pinned_default", 0) or 0)
            return d

    def update_document_library_meta(
        self,
        doc_id: str,
        is_pinned_default: bool | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any] | None:
        existing = self.get_document(doc_id)
        if not existing:
            return None
        new_pin = int(bool(is_pinned_default)) if is_pinned_default is not None else int(existing.get("is_pinned_default", 0))
        new_tags = [str(t).strip()[:24] for t in tags if str(t).strip()][:12] if tags is not None else existing.get("tags", [])
        with self.connect() as conn:
            conn.execute(
                "UPDATE documents SET is_pinned_default = ?, tags_json = ? WHERE id = ?",
                (new_pin, json.dumps(new_tags, ensure_ascii=False), doc_id),
            )
        return self.get_document(doc_id)

    def delete_document(self, doc_id: str) -> bool:
        with self.connect() as conn:
            conn.execute("DELETE FROM chunks_fts WHERE doc_id = ?", (doc_id,))
            cur = conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
            return cur.rowcount > 0

    def replace_document_content(
        self,
        doc_id: str,
        notebook_id: str,
        pages: list[dict[str, Any]],
        chunks: list[dict[str, Any]],
    ) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM pages WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM chunks_fts WHERE doc_id = ?", (doc_id,))

            conn.executemany(
                """
                INSERT INTO pages(doc_id, notebook_id, page_no, text, is_ocr, has_table, has_form)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        doc_id,
                        notebook_id,
                        p["page_no"],
                        p["text"],
                        int(bool(p.get("is_ocr"))),
                        int(bool(p.get("has_table"))),
                        int(bool(p.get("has_form"))),
                    )
                    for p in pages
                ],
            )

            for ch in chunks:
                tok = build_search_tokens(f"{ch.get('heading', '')} {ch.get('section_path', '')} {ch['content']}")
                cur = conn.execute(
                    """
                    INSERT INTO chunks(doc_id, notebook_id, page_start, page_end, heading, section_path, content, search_tokens, char_len)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id,
                        notebook_id,
                        ch["page_start"],
                        ch["page_end"],
                        ch.get("heading", ""),
                        ch.get("section_path", ""),
                        ch["content"],
                        tok,
                        len(ch["content"]),
                    ),
                )
                chunk_id = cur.lastrowid
                conn.execute(
                    """
                    INSERT INTO chunks_fts(content, heading, search_tokens, doc_id, notebook_id, chunk_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ch["content"],
                        f"{ch.get('heading', '')} {ch.get('section_path', '')}".strip(),
                        tok,
                        doc_id,
                        notebook_id,
                        chunk_id,
                    ),
                )

    def get_page_text(self, doc_id: str, page_no: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM pages WHERE doc_id = ? AND page_no = ?",
                (doc_id, page_no),
            ).fetchone()
            return dict(row) if row else None

    def get_document_pages(self, doc_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM pages WHERE doc_id = ? ORDER BY page_no ASC",
                (doc_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ---- Forms Catalog ----
    def replace_document_forms(self, doc_id: str, notebook_id: str, forms: list[dict[str, Any]]) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM forms_catalog WHERE doc_id = ?", (doc_id,))
            ts = now_iso()
            conn.executemany(
                """
                INSERT INTO forms_catalog(
                    id, doc_id, notebook_id, title, category, form_type,
                    page_start, page_end, has_table, sample_text, fields_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        f["id"],
                        doc_id,
                        notebook_id,
                        f["title"],
                        f.get("category", "서식"),
                        f.get("form_type", "form"),
                        f["page_start"],
                        f["page_end"],
                        int(bool(f.get("has_table"))),
                        f.get("sample_text", ""),
                        json.dumps(f.get("fields", []), ensure_ascii=False),
                        ts,
                    )
                    for f in forms
                ],
            )

    def list_forms(self, notebook_id: str, query: str = "", doc_ids: list[str] | None = None) -> list[dict[str, Any]]:
        with self.connect() as conn:
            sql = """
                SELECT f.*, d.title AS doc_title, d.file_type AS doc_file_type, d.stored_path AS doc_path
                FROM forms_catalog f
                JOIN documents d ON d.id = f.doc_id
                WHERE f.notebook_id = ?
            """
            params: list[Any] = [notebook_id]
            if doc_ids:
                placeholders = ",".join("?" for _ in doc_ids)
                sql += f" AND f.doc_id IN ({placeholders})"
                params.extend(doc_ids)
            if query.strip():
                sql += " AND (f.title LIKE ? OR f.category LIKE ? OR f.sample_text LIKE ?)"
                q = f"%{query.strip()}%"
                params.extend([q, q, q])
            sql += " ORDER BY d.priority DESC, f.page_start ASC"
            rows = conn.execute(sql, params).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d["fields"] = json.loads(d.pop("fields_json", "[]") or "[]")
                d["doc_path"] = resolve_stored_path(d.get("doc_path", ""), d.get("notebook_id"))
                out.append(d)
            return out

    def get_form(self, form_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT f.*, d.title AS doc_title, d.file_type AS doc_file_type, d.stored_path AS doc_path
                FROM forms_catalog f
                JOIN documents d ON d.id = f.doc_id
                WHERE f.id = ?
                """,
                (form_id,),
            ).fetchone()
            if not row:
                return None
            d = dict(row)
            d["fields"] = json.loads(d.pop("fields_json", "[]") or "[]")
            d["doc_path"] = resolve_stored_path(d.get("doc_path", ""), d.get("notebook_id"))
            return d

    # ---- Chat History (Private + Group Collaborative + Team-Shared) ----
    def create_session(
        self,
        session_id: str,
        notebook_id: str,
        user_label: str = "팀원",
        title: str = "새 대화",
        owner_id: str = "",
        is_shared: bool = False,
        group_id: str = "",
    ) -> dict[str, Any]:
        ts = now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO chat_sessions(id, notebook_id, user_label, owner_id, is_shared, group_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, notebook_id, user_label, owner_id, int(bool(is_shared)), group_id or "", title, ts, ts),
            )
            row = conn.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
            return dict(row)

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT s.*, COALESCE(g.name, '') AS group_name
                FROM chat_sessions s
                LEFT JOIN collab_groups g ON g.id = s.group_id
                WHERE s.id = ?
                """,
                (session_id,),
            ).fetchone()
            return dict(row) if row else None

    def list_sessions(
        self,
        notebook_id: str,
        owner_id: str = "",
        is_admin: bool = False,
        limit: int = 80,
    ) -> list[dict[str, Any]]:
        group_ids = list(self.get_user_group_ids(owner_id)) if owner_id else []
        with self.connect() as conn:
            if is_admin:
                rows = conn.execute(
                    """
                    SELECT s.*,
                           COALESCE(g.name, '') AS group_name,
                           (SELECT COUNT(*) FROM chat_messages m WHERE m.session_id = s.id) AS message_count
                    FROM chat_sessions s
                    LEFT JOIN collab_groups g ON g.id = s.group_id
                    WHERE s.notebook_id = ?
                      AND (s.is_shared = 1 OR s.group_id != '' OR s.owner_id = '' OR s.owner_id = ?)
                    ORDER BY CASE WHEN s.group_id != '' THEN 0 WHEN s.is_shared = 1 THEN 1 ELSE 2 END, s.updated_at DESC
                    LIMIT ?
                    """,
                    (notebook_id, owner_id, limit),
                ).fetchall()
            elif group_ids:
                ph = ",".join("?" for _ in group_ids)
                rows = conn.execute(
                    f"""
                    SELECT s.*,
                           COALESCE(g.name, '') AS group_name,
                           (SELECT COUNT(*) FROM chat_messages m WHERE m.session_id = s.id) AS message_count
                    FROM chat_sessions s
                    LEFT JOIN collab_groups g ON g.id = s.group_id
                    WHERE s.notebook_id = ?
                      AND (s.is_shared = 1 OR s.owner_id = ? OR s.group_id IN ({ph}))
                    ORDER BY CASE WHEN s.group_id != '' THEN 0 WHEN s.is_shared = 1 THEN 1 ELSE 2 END, s.updated_at DESC
                    LIMIT ?
                    """,
                    (notebook_id, owner_id, *group_ids, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT s.*,
                           COALESCE(g.name, '') AS group_name,
                           (SELECT COUNT(*) FROM chat_messages m WHERE m.session_id = s.id) AS message_count
                    FROM chat_sessions s
                    LEFT JOIN collab_groups g ON g.id = s.group_id
                    WHERE s.notebook_id = ?
                      AND (s.is_shared = 1 OR s.owner_id = ?)
                    ORDER BY s.is_shared DESC, s.updated_at DESC
                    LIMIT ?
                    """,
                    (notebook_id, owner_id, limit),
                ).fetchall()
            return [dict(r) for r in rows]

    def update_session(
        self,
        session_id: str,
        title: str | None = None,
        is_shared: bool | None = None,
        group_id: str | None = None,
    ) -> dict[str, Any] | None:
        existing = self.get_session(session_id)
        if not existing:
            return None
        new_title = title.strip()[:80] if title is not None and title.strip() else existing["title"]
        new_group = group_id.strip() if group_id is not None else str(existing.get("group_id") or "")
        if new_group:
            # Group-scoped chat should not simultaneously be leaked to non-members via team-wide flag
            new_shared = 0
        else:
            new_shared = int(bool(is_shared)) if is_shared is not None else int(existing.get("is_shared", 0))
        with self.connect() as conn:
            conn.execute(
                "UPDATE chat_sessions SET title = ?, is_shared = ?, group_id = ?, updated_at = ? WHERE id = ?",
                (new_title, new_shared, new_group, now_iso(), session_id),
            )
        return self.get_session(session_id)

    def rename_session(self, session_id: str, title: str) -> dict[str, Any] | None:
        return self.update_session(session_id, title=title)

    def delete_session(self, session_id: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
            return cur.rowcount > 0

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        mode: str = "practical",
        citations: list[dict[str, Any]] | None = None,
        forms: list[dict[str, Any]] | None = None,
        verification: dict[str, Any] | None = None,
        provider: str = "",
        author_label: str = "",
        author_owner_id: str = "",
    ) -> int:
        ts = now_iso()
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO chat_messages(
                    session_id, role, content, mode, citations_json, forms_json,
                    verification_json, provider, author_label, author_owner_id, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    role,
                    content,
                    mode,
                    json.dumps(citations or [], ensure_ascii=False),
                    json.dumps(forms or [], ensure_ascii=False),
                    json.dumps(verification or {}, ensure_ascii=False),
                    provider,
                    author_label[:60],
                    author_owner_id[:48],
                    ts,
                ),
            )
            conn.execute("UPDATE chat_sessions SET updated_at = ? WHERE id = ?", (ts, session_id))
            return int(cur.lastrowid)

    def get_session_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d["citations"] = json.loads(d.pop("citations_json", "[]") or "[]")
                d["forms"] = json.loads(d.pop("forms_json", "[]") or "[]")
                v_raw = d.pop("verification_json", "{}") or "{}"
                d["verification"] = json.loads(v_raw) if v_raw else {}
                out.append(d)
            return out

    # ---- Security Audit Logs ----
    def log_audit(
        self,
        event_type: str,
        actor_role: str = "",
        actor_label: str = "",
        client_ip: str = "",
        detail: str = "",
    ) -> None:
        if self.get_setting("audit_log_enabled", "1") != "1":
            return
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_logs(event_type, actor_role, actor_label, client_ip, detail, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (event_type, actor_role, actor_label, client_ip, detail[:300], now_iso()),
            )
            # Keep audit table bounded to latest 1000 entries
            conn.execute(
                "DELETE FROM audit_logs WHERE id NOT IN (SELECT id FROM audit_logs ORDER BY id DESC LIMIT 1000)"
            )

    def list_audit_logs(self, limit: int = 80) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def clear_audit_logs(self) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM audit_logs")

    # ---- Creator-Only Feedback / Bug / Improvement Reports ----
    def create_feedback(
        self,
        category: str,
        title: str,
        description: str,
        reporter_label: str = "사용자",
        reporter_role: str = "member",
        client_ip: str = "",
        device_info: str = "",
        app_version: str = "",
        context_info: str = "",
        relayed_remote: bool = False,
    ) -> dict[str, Any]:
        ts = now_iso()
        cat = category if category in ("bug", "ux", "feature", "doc") else "bug"
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO feedback_reports(
                    category, title, description, reporter_label, reporter_role,
                    client_ip, device_info, app_version, context_info,
                    status, creator_note, relayed_remote, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', '', ?, ?, ?)
                """,
                (
                    cat,
                    title.strip()[:160],
                    description.strip()[:5000],
                    reporter_label[:60],
                    reporter_role[:20],
                    client_ip[:60],
                    device_info[:300],
                    app_version[:40],
                    context_info[:500],
                    int(bool(relayed_remote)),
                    ts,
                    ts,
                ),
            )
            row = conn.execute("SELECT * FROM feedback_reports WHERE id = ?", (cur.lastrowid,)).fetchone()
            return dict(row)

    def list_feedback(self, status: str = "", limit: int = 200) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if status in ("open", "reviewing", "resolved"):
                rows = conn.execute(
                    "SELECT * FROM feedback_reports WHERE status = ? ORDER BY id DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM feedback_reports ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    def update_feedback(
        self,
        feedback_id: int,
        status: str | None = None,
        creator_note: str | None = None,
        relayed_remote: bool | None = None,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM feedback_reports WHERE id = ?", (feedback_id,)).fetchone()
            if not row:
                return None
            cur_d = dict(row)
            new_status = status if status in ("open", "reviewing", "resolved") else cur_d["status"]
            new_note = creator_note[:2000] if creator_note is not None else cur_d["creator_note"]
            new_relay = int(bool(relayed_remote)) if relayed_remote is not None else cur_d["relayed_remote"]
            conn.execute(
                "UPDATE feedback_reports SET status = ?, creator_note = ?, relayed_remote = ?, updated_at = ? WHERE id = ?",
                (new_status, new_note, new_relay, now_iso(), feedback_id),
            )
            out = conn.execute("SELECT * FROM feedback_reports WHERE id = ?", (feedback_id,)).fetchone()
            return dict(out) if out else None

    def delete_feedback(self, feedback_id: int) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM feedback_reports WHERE id = ?", (feedback_id,))
            return cur.rowcount > 0

    def count_open_feedback(self) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM feedback_reports WHERE status != 'resolved'").fetchone()
            return int(row["c"]) if row else 0

    # ---- Member Directory, Group Creator Grants & Collaboration Groups ----
    def upsert_member(self, owner_id: str, label: str, role: str = "member") -> dict[str, Any]:
        oid = (owner_id or "").strip()[:48]
        if not oid:
            return {"owner_id": "", "label": label, "role": role, "can_create_group": int(role == "admin")}
        ts = now_iso()
        clean_label = (label or "교역자").strip()[:40]
        clean_role = "admin" if role == "admin" else "member"
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO member_directory(owner_id, label, role, can_create_group, last_seen_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(owner_id) DO UPDATE SET
                    label = CASE WHEN excluded.label != '' THEN excluded.label ELSE member_directory.label END,
                    role = excluded.role,
                    last_seen_at = excluded.last_seen_at
                """,
                (oid, clean_label, clean_role, 1 if clean_role == "admin" else 0, ts),
            )
            row = conn.execute("SELECT * FROM member_directory WHERE owner_id = ?", (oid,)).fetchone()
            return dict(row)

    def get_member(self, owner_id: str) -> dict[str, Any] | None:
        if not owner_id:
            return None
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM member_directory WHERE owner_id = ?", (owner_id,)).fetchone()
            return dict(row) if row else None

    def list_members(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT m.owner_id, m.label, m.role, m.can_create_group,
                       (CASE WHEN m.recovery_code_hash != '' THEN 1 ELSE 0 END) AS has_recovery_code,
                       m.last_seen_at,
                       (SELECT COUNT(*) FROM collab_group_members gm WHERE gm.owner_id = m.owner_id) AS group_count
                FROM member_directory m
                ORDER BY CASE WHEN m.role = 'admin' THEN 0 ELSE 1 END, m.last_seen_at DESC
                """
            ).fetchall()
            return [dict(r) for r in rows]

    def set_member_group_permission(self, owner_id: str, can_create_group: bool) -> dict[str, Any] | None:
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE member_directory SET can_create_group = ? WHERE owner_id = ?",
                (int(bool(can_create_group)), owner_id),
            )
            if cur.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT owner_id, label, role, can_create_group, last_seen_at FROM member_directory WHERE owner_id = ?",
                (owner_id,),
            ).fetchone()
            return dict(row) if row else None

    def can_user_create_group(self, owner_id: str, role: str) -> bool:
        if role == "admin":
            return True
        m = self.get_member(owner_id)
        return bool(m and int(m.get("can_create_group", 0)) == 1)

    def set_member_recovery_hash(self, owner_id: str, code_hash: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE member_directory SET recovery_code_hash = ? WHERE owner_id = ?",
                (code_hash, owner_id),
            )

    def find_member_by_recovery_code(self, verifier: Any) -> dict[str, Any] | None:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM member_directory WHERE recovery_code_hash != ''"
            ).fetchall()
            for r in rows:
                d = dict(r)
                if verifier(d["recovery_code_hash"]):
                    return d
            return None

    @staticmethod
    def _gen_invite_code() -> str:
        import secrets as _sec
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        return "".join(_sec.choice(alphabet) for _ in range(6))

    def create_group(
        self,
        name: str,
        description: str,
        creator_owner_id: str,
        creator_label: str,
    ) -> dict[str, Any]:
        import uuid as _uuid
        gid = "grp_" + _uuid.uuid4().hex[:10]
        ts = now_iso()
        with self.connect() as conn:
            code = self._gen_invite_code()
            for _ in range(10):
                exists = conn.execute("SELECT 1 FROM collab_groups WHERE invite_code = ?", (code,)).fetchone()
                if not exists:
                    break
                code = self._gen_invite_code()
            conn.execute(
                """
                INSERT INTO collab_groups(id, name, description, invite_code, created_by_owner_id, created_by_label, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (gid, name.strip()[:60], description.strip()[:300], code, creator_owner_id, creator_label[:40], ts, ts),
            )
            if creator_owner_id:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO collab_group_members(group_id, owner_id, member_label, role, joined_at)
                    VALUES (?, ?, ?, 'leader', ?)
                    """,
                    (gid, creator_owner_id, creator_label[:40], ts),
                )
        return self.get_group(gid)  # type: ignore[return-value]

    def get_group(self, group_id: str) -> dict[str, Any] | None:
        if not group_id:
            return None
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM collab_groups WHERE id = ?", (group_id,)).fetchone()
            if not row:
                return None
            d = dict(row)
            mrows = conn.execute(
                "SELECT owner_id, member_label, role, joined_at FROM collab_group_members WHERE group_id = ? ORDER BY CASE WHEN role='leader' THEN 0 ELSE 1 END, joined_at ASC",
                (group_id,),
            ).fetchall()
            d["members"] = [dict(m) for m in mrows]
            d["member_count"] = len(d["members"])
            return d

    def get_group_by_invite_code(self, code: str) -> dict[str, Any] | None:
        clean = re.sub(r"[^A-Za-z0-9]", "", (code or "").strip()).upper()
        if not clean:
            return None
        with self.connect() as conn:
            row = conn.execute("SELECT id FROM collab_groups WHERE UPPER(invite_code) = ?", (clean,)).fetchone()
            return self.get_group(row["id"]) if row else None

    def get_user_group_ids(self, owner_id: str) -> set[str]:
        if not owner_id:
            return set()
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT group_id FROM collab_group_members WHERE owner_id = ?",
                (owner_id,),
            ).fetchall()
            return {str(r["group_id"]) for r in rows}

    def is_group_member(self, group_id: str, owner_id: str) -> bool:
        if not group_id or not owner_id:
            return False
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM collab_group_members WHERE group_id = ? AND owner_id = ?",
                (group_id, owner_id),
            ).fetchone()
            return row is not None

    def get_group_member_role(self, group_id: str, owner_id: str) -> str:
        if not group_id or not owner_id:
            return ""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT role FROM collab_group_members WHERE group_id = ? AND owner_id = ?",
                (group_id, owner_id),
            ).fetchone()
            return str(row["role"]) if row else ""

    def list_groups(self, owner_id: str, is_admin: bool = False) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if is_admin:
                rows = conn.execute("SELECT id FROM collab_groups ORDER BY updated_at DESC").fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT g.id FROM collab_groups g
                    JOIN collab_group_members gm ON gm.group_id = g.id
                    WHERE gm.owner_id = ?
                    ORDER BY g.updated_at DESC
                    """,
                    (owner_id,),
                ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            g = self.get_group(r["id"])
            if g:
                my_m = next((m for m in g["members"] if m["owner_id"] == owner_id), None)
                g["is_member"] = bool(my_m)
                g["my_role"] = my_m["role"] if my_m else ("admin" if is_admin else "")
                out.append(g)
        return out

    def add_group_member(
        self,
        group_id: str,
        owner_id: str,
        member_label: str,
        role: str = "member",
    ) -> dict[str, Any] | None:
        ts = now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO collab_group_members(group_id, owner_id, member_label, role, joined_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(group_id, owner_id) DO UPDATE SET
                    member_label = CASE WHEN excluded.member_label != '' THEN excluded.member_label ELSE collab_group_members.member_label END
                """,
                (group_id, owner_id, member_label[:40], role if role in ("leader", "member") else "member", ts),
            )
            conn.execute("UPDATE collab_groups SET updated_at = ? WHERE id = ?", (ts, group_id))
        return self.get_group(group_id)

    def remove_group_member(self, group_id: str, owner_id: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                "DELETE FROM collab_group_members WHERE group_id = ? AND owner_id = ?",
                (group_id, owner_id),
            )
            conn.execute("UPDATE collab_groups SET updated_at = ? WHERE id = ?", (now_iso(), group_id))
            return cur.rowcount > 0

    def regenerate_group_invite_code(self, group_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            code = self._gen_invite_code()
            for _ in range(10):
                if not conn.execute("SELECT 1 FROM collab_groups WHERE invite_code = ?", (code,)).fetchone():
                    break
                code = self._gen_invite_code()
            cur = conn.execute(
                "UPDATE collab_groups SET invite_code = ?, updated_at = ? WHERE id = ?",
                (code, now_iso(), group_id),
            )
            if cur.rowcount == 0:
                return None
        return self.get_group(group_id)

    def delete_group(self, group_id: str) -> bool:
        with self.connect() as conn:
            # Unlink sessions so chats aren't broken when a group is deleted
            conn.execute("UPDATE chat_sessions SET group_id = '' WHERE group_id = ?", (group_id,))
            try:
                conn.execute("UPDATE std_boards SET group_id = '' WHERE group_id = ?", (group_id,))
            except sqlite3.OperationalError:
                pass
            cur = conn.execute("DELETE FROM collab_groups WHERE id = ?", (group_id,))
            return cur.rowcount > 0

    # ---- Compact Offline Bundle Export (for iOS PWA IndexedDB & Android APK) ----
    def export_offline_bundle(self, notebook_id: str) -> dict[str, Any] | None:
        nb = self.get_notebook(notebook_id)
        if not nb:
            return None
        docs = [
            {
                "id": d["id"],
                "title": d["title"],
                "category": d["category"],
                "file_type": d["file_type"],
                "page_count": d["page_count"],
                "priority": d["priority"],
                "status": d["status"],
            }
            for d in self.list_documents(notebook_id)
            if d["status"] == "ready"
        ]
        with self.connect() as conn:
            chunk_rows = conn.execute(
                """
                SELECT c.id, c.doc_id, c.page_start, c.page_end, c.heading, c.section_path, c.content
                FROM chunks c
                JOIN documents d ON d.id = c.doc_id
                WHERE c.notebook_id = ? AND d.status = 'ready'
                ORDER BY d.priority DESC, c.doc_id ASC, c.id ASC
                """,
                (notebook_id,),
            ).fetchall()
            chunks = [dict(r) for r in chunk_rows]
        forms = [
            {
                "id": f["id"],
                "doc_id": f["doc_id"],
                "doc_title": f["doc_title"],
                "title": f["title"],
                "category": f["category"],
                "form_type": f["form_type"],
                "page_start": f["page_start"],
                "page_end": f["page_end"],
                "fields": f["fields"],
                "sample_text": (f.get("sample_text") or "")[:1200],
            }
            for f in self.list_forms(notebook_id)
        ]
        return {
            "version": 1,
            "generated_at": now_iso(),
            "notebook": {
                "id": nb["id"],
                "name": nb["name"],
                "description": nb["description"],
            },
            "documents": docs,
            "chunks": chunks,
            "forms": forms,
        }
