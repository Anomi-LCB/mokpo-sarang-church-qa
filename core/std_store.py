from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from core.config import get_data_dir, get_db_path, resolve_stored_path


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def get_std_dir() -> Path:
    p = get_data_dir() / "standardization"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_std_uploads_dir(board_id: str) -> Path:
    p = get_std_dir() / "uploads" / board_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_std_publications_dir(board_id: str) -> Path:
    p = get_std_dir() / "publications" / board_id
    p.mkdir(parents=True, exist_ok=True)
    return p


STD_SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS std_boards (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '일반 행정',
    work_type TEXT NOT NULL DEFAULT '규정·서식 표준화',
    description TEXT NOT NULL DEFAULT '',
    guidelines TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'collecting',
    deadline TEXT NOT NULL DEFAULT '',
    vote_visibility TEXT NOT NULL DEFAULT 'named',
    submission_anonymous INTEGER NOT NULL DEFAULT 0,
    allow_vote_change INTEGER NOT NULL DEFAULT 1,
    auto_route_enabled INTEGER NOT NULL DEFAULT 0,
    group_id TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '관리자',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS std_submissions (
    id TEXT PRIMARY KEY,
    board_id TEXT NOT NULL,
    title TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    author_label TEXT NOT NULL DEFAULT '교역자',
    owner_id TEXT NOT NULL DEFAULT '',
    is_anonymous INTEGER NOT NULL DEFAULT 0,
    file_name TEXT NOT NULL DEFAULT '',
    file_type TEXT NOT NULL DEFAULT '',
    stored_path TEXT NOT NULL DEFAULT '',
    extracted_text TEXT NOT NULL DEFAULT '',
    char_len INTEGER NOT NULL DEFAULT 0,
    ai_summary TEXT NOT NULL DEFAULT '',
    ai_tags_json TEXT NOT NULL DEFAULT '[]',
    ai_cluster_key TEXT NOT NULL DEFAULT '',
    source_origin TEXT NOT NULL DEFAULT 'direct',
    origin_submission_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (board_id) REFERENCES std_boards(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS std_cross_memory (
    id TEXT PRIMARY KEY,
    submission_id TEXT NOT NULL,
    source_board_id TEXT NOT NULL,
    target_board_id TEXT NOT NULL DEFAULT '',
    suggested_category TEXT NOT NULL DEFAULT '',
    action_type TEXT NOT NULL DEFAULT 'copy',
    confidence INTEGER NOT NULL DEFAULT 75,
    reason TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    applied_submission_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (submission_id) REFERENCES std_submissions(id) ON DELETE CASCADE,
    FOREIGN KEY (source_board_id) REFERENCES std_boards(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS std_proposals (
    id TEXT PRIMARY KEY,
    board_id TEXT NOT NULL,
    cluster_title TEXT NOT NULL,
    category_tag TEXT NOT NULL DEFAULT '공통 규격',
    summary TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    winning_option_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (board_id) REFERENCES std_boards(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS std_proposal_options (
    id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT 'A안',
    title TEXT NOT NULL,
    content_md TEXT NOT NULL DEFAULT '',
    source_submission_ids_json TEXT NOT NULL DEFAULT '[]',
    is_ai_improved INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (proposal_id) REFERENCES std_proposals(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS std_votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id TEXT NOT NULL,
    option_id TEXT NOT NULL,
    voter_id TEXT NOT NULL,
    voter_label TEXT NOT NULL DEFAULT '교역자',
    comment TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (proposal_id, voter_id),
    FOREIGN KEY (proposal_id) REFERENCES std_proposals(id) ON DELETE CASCADE,
    FOREIGN KEY (option_id) REFERENCES std_proposal_options(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS std_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    board_id TEXT NOT NULL,
    proposal_id TEXT NOT NULL DEFAULT '',
    submission_id TEXT NOT NULL DEFAULT '',
    author_label TEXT NOT NULL DEFAULT '교역자',
    owner_id TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'improvement',
    created_at TEXT NOT NULL,
    FOREIGN KEY (board_id) REFERENCES std_boards(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS std_publications (
    id TEXT PRIMARY KEY,
    board_id TEXT NOT NULL,
    version_label TEXT NOT NULL DEFAULT 'v1.0',
    title TEXT NOT NULL,
    pdf_path TEXT NOT NULL DEFAULT '',
    docx_path TEXT NOT NULL DEFAULT '',
    html_snapshot TEXT NOT NULL DEFAULT '',
    committee_report_json TEXT NOT NULL DEFAULT '{}',
    law_audit_json TEXT NOT NULL DEFAULT '[]',
    published_doc_id TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '관리자',
    created_at TEXT NOT NULL,
    FOREIGN KEY (board_id) REFERENCES std_boards(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_std_sub_board ON std_submissions(board_id, status);
CREATE INDEX IF NOT EXISTS idx_std_mem_status ON std_cross_memory(status, target_board_id);
CREATE INDEX IF NOT EXISTS idx_std_prop_board ON std_proposals(board_id);
CREATE INDEX IF NOT EXISTS idx_std_pub_board ON std_publications(board_id);
"""


class StandardizationStore:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or get_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(STD_SCHEMA_SQL)
            bcols = {r["name"] for r in conn.execute("PRAGMA table_info(std_boards)").fetchall()}
            if "group_id" not in bcols:
                conn.execute("ALTER TABLE std_boards ADD COLUMN group_id TEXT NOT NULL DEFAULT ''")

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

    # ---- Boards ----
    def create_board(
        self,
        title: str,
        category: str = "일반 행정",
        work_type: str = "규정·서식 표준화",
        description: str = "",
        guidelines: str = "",
        deadline: str = "",
        vote_visibility: str = "named",
        submission_anonymous: bool = False,
        allow_vote_change: bool = True,
        auto_route_enabled: bool = False,
        group_id: str = "",
        created_by: str = "관리자",
    ) -> dict[str, Any]:
        bid = "brd_" + uuid.uuid4().hex[:10]
        ts = _now_iso()
        vis = vote_visibility if vote_visibility in ("named", "anonymous") else "named"
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO std_boards(
                    id, title, category, work_type, description, guidelines, status, deadline,
                    vote_visibility, submission_anonymous, allow_vote_change, auto_route_enabled,
                    group_id, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'collecting', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bid,
                    title.strip()[:120],
                    category.strip()[:60] or "일반 행정",
                    work_type.strip()[:60] or "규정·서식 표준화",
                    description.strip()[:2000],
                    guidelines.strip()[:3000],
                    deadline.strip()[:40],
                    vis,
                    int(bool(submission_anonymous)),
                    int(bool(allow_vote_change)),
                    int(bool(auto_route_enabled)),
                    (group_id or "").strip()[:48],
                    created_by[:60],
                    ts,
                    ts,
                ),
            )
        return self.get_board(bid)  # type: ignore[return-value]

    def list_boards(
        self,
        allowed_group_ids: set[str] | None = None,
        is_admin: bool = True,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            has_grp = bool(
                conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='collab_groups'").fetchone()
            )
            grp_col = (
                "COALESCE((SELECT g.name FROM collab_groups g WHERE g.id = b.group_id), '') AS group_name,"
                if has_grp
                else "'' AS group_name,"
            )
            rows = conn.execute(
                f"""
                SELECT b.*,
                       {grp_col}
                       (SELECT COUNT(*) FROM std_submissions s WHERE s.board_id = b.id AND s.status = 'active') AS submission_count,
                       (SELECT COUNT(*) FROM std_proposals p WHERE p.board_id = b.id) AS proposal_count,
                       (SELECT COUNT(*) FROM std_publications pub WHERE pub.board_id = b.id) AS publication_count,
                       (SELECT COUNT(*) FROM std_cross_memory m
                        WHERE m.status = 'pending' AND (m.target_board_id = b.id OR m.source_board_id = b.id)) AS pending_memory_count
                FROM std_boards b
                ORDER BY b.updated_at DESC
                """
            ).fetchall()
            out = [dict(r) for r in rows]
            if not is_admin:
                allowed = allowed_group_ids or set()
                out = [b for b in out if not b.get("group_id") or b.get("group_id") in allowed]
            return out

    def get_board(self, board_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            has_grp = bool(
                conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='collab_groups'").fetchone()
            )
            grp_col = (
                "COALESCE((SELECT g.name FROM collab_groups g WHERE g.id = b.group_id), '') AS group_name,"
                if has_grp
                else "'' AS group_name,"
            )
            row = conn.execute(
                f"""
                SELECT b.*,
                       {grp_col}
                       (SELECT COUNT(*) FROM std_submissions s WHERE s.board_id = b.id AND s.status = 'active') AS submission_count,
                       (SELECT COUNT(*) FROM std_proposals p WHERE p.board_id = b.id) AS proposal_count,
                       (SELECT COUNT(*) FROM std_publications pub WHERE pub.board_id = b.id) AS publication_count,
                       (SELECT COUNT(*) FROM std_cross_memory m
                        WHERE m.status = 'pending' AND (m.target_board_id = b.id OR m.source_board_id = b.id)) AS pending_memory_count
                FROM std_boards b
                WHERE b.id = ?
                """,
                (board_id,),
            ).fetchone()
            return dict(row) if row else None

    def update_board(self, board_id: str, **fields: Any) -> dict[str, Any] | None:
        cur = self.get_board(board_id)
        if not cur:
            return None
        allowed = {
            "title",
            "category",
            "work_type",
            "description",
            "guidelines",
            "status",
            "deadline",
            "vote_visibility",
            "submission_anonymous",
            "allow_vote_change",
            "auto_route_enabled",
            "group_id",
        }
        sets: list[str] = []
        vals: list[Any] = []
        for k, v in fields.items():
            if k not in allowed or v is None:
                continue
            if k in ("submission_anonymous", "allow_vote_change", "auto_route_enabled"):
                v = int(bool(v))
            elif k == "status" and v not in ("collecting", "voting", "published"):
                continue
            elif k == "vote_visibility" and v not in ("named", "anonymous"):
                continue
            sets.append(f"{k} = ?")
            vals.append(v)
        if not sets:
            return cur
        sets.append("updated_at = ?")
        vals.append(_now_iso())
        vals.append(board_id)
        with self.connect() as conn:
            conn.execute(f"UPDATE std_boards SET {', '.join(sets)} WHERE id = ?", vals)
        return self.get_board(board_id)

    def delete_board(self, board_id: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM std_boards WHERE id = ?", (board_id,))
            return cur.rowcount > 0

    # ---- Submissions ----
    def create_submission(
        self,
        board_id: str,
        title: str,
        notes: str = "",
        author_label: str = "교역자",
        owner_id: str = "",
        is_anonymous: bool = False,
        file_name: str = "",
        file_type: str = "",
        stored_path: str = "",
        extracted_text: str = "",
        ai_summary: str = "",
        ai_tags: list[str] | None = None,
        ai_cluster_key: str = "",
        source_origin: str = "direct",
        origin_submission_id: str = "",
    ) -> dict[str, Any]:
        sid = "sub_" + uuid.uuid4().hex[:10]
        ts = _now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO std_submissions(
                    id, board_id, title, notes, author_label, owner_id, is_anonymous,
                    file_name, file_type, stored_path, extracted_text, char_len,
                    ai_summary, ai_tags_json, ai_cluster_key, source_origin, origin_submission_id,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    sid,
                    board_id,
                    title.strip()[:160],
                    notes.strip()[:5000],
                    author_label[:60],
                    owner_id[:60],
                    int(bool(is_anonymous)),
                    file_name[:200],
                    file_type[:20],
                    stored_path,
                    extracted_text,
                    len(extracted_text),
                    ai_summary[:1000],
                    json.dumps(ai_tags or [], ensure_ascii=False),
                    ai_cluster_key[:80],
                    source_origin[:20],
                    origin_submission_id[:40],
                    ts,
                    ts,
                ),
            )
            conn.execute("UPDATE std_boards SET updated_at = ? WHERE id = ?", (ts, board_id))
        return self.get_submission(sid)  # type: ignore[return-value]

    def _row_to_submission(self, row: sqlite3.Row, mask_author: bool = False) -> dict[str, Any]:
        d = dict(row)
        d["ai_tags"] = json.loads(d.pop("ai_tags_json", "[]") or "[]")
        if d.get("stored_path"):
            d["stored_path"] = resolve_stored_path(d["stored_path"])
        if mask_author and d.get("is_anonymous"):
            d["author_label"] = "익명 교역자"
        return d

    def get_submission(self, sub_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM std_submissions WHERE id = ?", (sub_id,)).fetchone()
            return self._row_to_submission(row) if row else None

    def list_submissions(
        self,
        board_id: str,
        include_archived: bool = False,
        mask_anonymous: bool = False,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if include_archived:
                rows = conn.execute(
                    "SELECT * FROM std_submissions WHERE board_id = ? ORDER BY created_at DESC",
                    (board_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM std_submissions WHERE board_id = ? AND status = 'active' ORDER BY created_at DESC",
                    (board_id,),
                ).fetchall()
            return [self._row_to_submission(r, mask_author=mask_anonymous) for r in rows]

    def update_submission_ai(
        self,
        sub_id: str,
        ai_summary: str,
        ai_tags: list[str],
        ai_cluster_key: str,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE std_submissions
                SET ai_summary = ?, ai_tags_json = ?, ai_cluster_key = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    ai_summary[:1000],
                    json.dumps(ai_tags[:12], ensure_ascii=False),
                    ai_cluster_key[:80],
                    _now_iso(),
                    sub_id,
                ),
            )

    def move_submission_board(self, sub_id: str, target_board_id: str, origin_tag: str = "moved") -> dict[str, Any] | None:
        ts = _now_iso()
        with self.connect() as conn:
            conn.execute(
                "UPDATE std_submissions SET board_id = ?, source_origin = ?, updated_at = ? WHERE id = ?",
                (target_board_id, origin_tag, ts, sub_id),
            )
            conn.execute("UPDATE std_boards SET updated_at = ? WHERE id = ?", (ts, target_board_id))
        return self.get_submission(sub_id)

    def set_submission_status(self, sub_id: str, status: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE std_submissions SET status = ?, updated_at = ? WHERE id = ?",
                (status, _now_iso(), sub_id),
            )

    def delete_submission(self, sub_id: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM std_submissions WHERE id = ?", (sub_id,))
            return cur.rowcount > 0

    # ---- Cross-Board Memory (AI Persistent Suggestions & Undo Log) ----
    def create_cross_memory(
        self,
        submission_id: str,
        source_board_id: str,
        target_board_id: str = "",
        suggested_category: str = "",
        action_type: str = "copy",
        confidence: int = 75,
        reason: str = "",
        status: str = "pending",
        applied_submission_id: str = "",
    ) -> dict[str, Any]:
        mid = "mem_" + uuid.uuid4().hex[:10]
        ts = _now_iso()
        act = action_type if action_type in ("move", "copy", "merge", "deferred") else "copy"
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO std_cross_memory(
                    id, submission_id, source_board_id, target_board_id, suggested_category,
                    action_type, confidence, reason, status, applied_submission_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mid,
                    submission_id,
                    source_board_id,
                    target_board_id,
                    suggested_category[:80],
                    act,
                    max(0, min(100, int(confidence))),
                    reason[:600],
                    status,
                    applied_submission_id,
                    ts,
                    ts,
                ),
            )
        return self.get_cross_memory(mid)  # type: ignore[return-value]

    def get_cross_memory(self, mem_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT m.*,
                       s.title AS submission_title,
                       s.file_name AS submission_file_name,
                       s.ai_summary AS submission_summary,
                       sb.title AS source_board_title,
                       sb.category AS source_board_category,
                       COALESCE(tb.title, '') AS target_board_title
                FROM std_cross_memory m
                JOIN std_submissions s ON s.id = m.submission_id
                JOIN std_boards sb ON sb.id = m.source_board_id
                LEFT JOIN std_boards tb ON tb.id = m.target_board_id
                WHERE m.id = ?
                """,
                (mem_id,),
            ).fetchone()
            return dict(row) if row else None

    def list_cross_memories(self, board_id: str = "", status: str = "") -> list[dict[str, Any]]:
        sql = """
            SELECT m.*,
                   s.title AS submission_title,
                   s.file_name AS submission_file_name,
                   s.ai_summary AS submission_summary,
                   sb.title AS source_board_title,
                   sb.category AS source_board_category,
                   COALESCE(tb.title, '') AS target_board_title
            FROM std_cross_memory m
            JOIN std_submissions s ON s.id = m.submission_id
            JOIN std_boards sb ON sb.id = m.source_board_id
            LEFT JOIN std_boards tb ON tb.id = m.target_board_id
            WHERE 1=1
        """
        params: list[Any] = []
        if board_id:
            sql += " AND (m.source_board_id = ? OR m.target_board_id = ?)"
            params.extend([board_id, board_id])
        if status:
            sql += " AND m.status = ?"
            params.append(status)
        sql += " ORDER BY CASE WHEN m.status = 'pending' THEN 0 ELSE 1 END, m.confidence DESC, m.updated_at DESC"
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def update_cross_memory(
        self,
        mem_id: str,
        status: str | None = None,
        target_board_id: str | None = None,
        action_type: str | None = None,
        applied_submission_id: str | None = None,
    ) -> dict[str, Any] | None:
        cur = self.get_cross_memory(mem_id)
        if not cur:
            return None
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE std_cross_memory
                SET status = ?, target_board_id = ?, action_type = ?, applied_submission_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    status if status is not None else cur["status"],
                    target_board_id if target_board_id is not None else cur["target_board_id"],
                    action_type if action_type is not None else cur["action_type"],
                    applied_submission_id if applied_submission_id is not None else cur["applied_submission_id"],
                    _now_iso(),
                    mem_id,
                ),
            )
        return self.get_cross_memory(mem_id)

    # ---- Voting Proposals, Options, Votes, Comments ----
    def create_proposal(
        self,
        board_id: str,
        cluster_title: str,
        category_tag: str = "공통 규격",
        summary: str = "",
        options: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        pid = "prp_" + uuid.uuid4().hex[:10]
        ts = _now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO std_proposals(id, board_id, cluster_title, category_tag, summary, status, winning_option_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'open', '', ?, ?)
                """,
                (pid, board_id, cluster_title.strip()[:140], category_tag.strip()[:60], summary.strip()[:1200], ts, ts),
            )
            for idx, opt in enumerate(options or []):
                oid = "opt_" + uuid.uuid4().hex[:10]
                default_lbl = f"{chr(65 + idx)}안" if idx < 6 else f"안 {idx + 1}"
                conn.execute(
                    """
                    INSERT INTO std_proposal_options(
                        id, proposal_id, label, title, content_md, source_submission_ids_json, is_ai_improved, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        oid,
                        pid,
                        str(opt.get("label") or default_lbl)[:30],
                        str(opt.get("title") or "후보안")[:160],
                        str(opt.get("content_md") or "")[:8000],
                        json.dumps(opt.get("source_submission_ids") or [], ensure_ascii=False),
                        int(bool(opt.get("is_ai_improved"))),
                        ts,
                    ),
                )
        return self.get_proposal(pid)  # type: ignore[return-value]

    def get_proposal(self, proposal_id: str, viewer_voter_id: str = "", anonymous_votes: bool = False) -> dict[str, Any] | None:
        with self.connect() as conn:
            p_row = conn.execute("SELECT * FROM std_proposals WHERE id = ?", (proposal_id,)).fetchone()
            if not p_row:
                return None
            p = dict(p_row)
            opt_rows = conn.execute(
                "SELECT * FROM std_proposal_options WHERE proposal_id = ? ORDER BY is_ai_improved ASC, created_at ASC",
                (proposal_id,),
            ).fetchall()
            vote_rows = conn.execute(
                "SELECT * FROM std_votes WHERE proposal_id = ? ORDER BY updated_at DESC",
                (proposal_id,),
            ).fetchall()

            votes_by_opt: dict[str, list[dict[str, Any]]] = {}
            my_vote_option_id = ""
            for vr in vote_rows:
                vd = dict(vr)
                if vd["voter_id"] == viewer_voter_id:
                    my_vote_option_id = vd["option_id"]
                votes_by_opt.setdefault(vd["option_id"], []).append(
                    {
                        "voter_label": "익명" if anonymous_votes else vd["voter_label"],
                        "comment": vd["comment"],
                        "updated_at": vd["updated_at"],
                    }
                )

            options_out = []
            total_votes = len(vote_rows)
            for orow in opt_rows:
                od = dict(orow)
                od["source_submission_ids"] = json.loads(od.pop("source_submission_ids_json", "[]") or "[]")
                vlist = votes_by_opt.get(od["id"], [])
                od["vote_count"] = len(vlist)
                od["vote_pct"] = round((len(vlist) / total_votes) * 100) if total_votes > 0 else 0
                od["voters"] = vlist
                options_out.append(od)

            p["options"] = options_out
            p["total_votes"] = total_votes
            p["my_vote_option_id"] = my_vote_option_id
            return p

    def list_proposals(self, board_id: str, viewer_voter_id: str = "", anonymous_votes: bool = False) -> list[dict[str, Any]]:
        with self.connect() as conn:
            ids = [
                r["id"]
                for r in conn.execute(
                    "SELECT id FROM std_proposals WHERE board_id = ? ORDER BY created_at ASC",
                    (board_id,),
                ).fetchall()
            ]
        return [
            p
            for pid in ids
            if (p := self.get_proposal(pid, viewer_voter_id=viewer_voter_id, anonymous_votes=anonymous_votes)) is not None
        ]

    def cast_vote(
        self,
        proposal_id: str,
        option_id: str,
        voter_id: str,
        voter_label: str,
        comment: str = "",
        allow_change: bool = True,
    ) -> dict[str, Any]:
        ts = _now_iso()
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT * FROM std_votes WHERE proposal_id = ? AND voter_id = ?",
                (proposal_id, voter_id),
            ).fetchone()
            if existing and not allow_change:
                raise ValueError("이 게시글은 1회 확정 투표 정책이 적용되어 투표를 변경할 수 없습니다.")
            if existing:
                conn.execute(
                    "UPDATE std_votes SET option_id = ?, voter_label = ?, comment = ?, updated_at = ? WHERE id = ?",
                    (option_id, voter_label[:60], comment.strip()[:500], ts, existing["id"]),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO std_votes(proposal_id, option_id, voter_id, voter_label, comment, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (proposal_id, option_id, voter_id[:60], voter_label[:60], comment.strip()[:500], ts, ts),
                )
        return self.get_proposal(proposal_id, viewer_voter_id=voter_id)  # type: ignore[return-value]

    def update_proposal(self, proposal_id: str, status: str | None = None, winning_option_id: str | None = None) -> dict[str, Any] | None:
        cur = self.get_proposal(proposal_id)
        if not cur:
            return None
        new_status = status if status in ("open", "closed", "adopted") else cur["status"]
        new_win = winning_option_id if winning_option_id is not None else cur["winning_option_id"]
        with self.connect() as conn:
            conn.execute(
                "UPDATE std_proposals SET status = ?, winning_option_id = ?, updated_at = ? WHERE id = ?",
                (new_status, new_win, _now_iso(), proposal_id),
            )
        return self.get_proposal(proposal_id)

    def delete_proposal(self, proposal_id: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM std_proposals WHERE id = ?", (proposal_id,))
            return cur.rowcount > 0

    def add_comment(
        self,
        board_id: str,
        content: str,
        author_label: str = "교역자",
        owner_id: str = "",
        proposal_id: str = "",
        submission_id: str = "",
        kind: str = "improvement",
    ) -> dict[str, Any]:
        ts = _now_iso()
        k = kind if kind in ("improvement", "question", "decision") else "improvement"
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO std_comments(board_id, proposal_id, submission_id, author_label, owner_id, content, kind, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (board_id, proposal_id, submission_id, author_label[:60], owner_id[:60], content.strip()[:2000], k, ts),
            )
            row = conn.execute("SELECT * FROM std_comments WHERE id = ?", (cur.lastrowid,)).fetchone()
            return dict(row)

    def list_comments(self, board_id: str, mask_anonymous: bool = False) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM std_comments WHERE board_id = ? ORDER BY id DESC LIMIT 200",
                (board_id,),
            ).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                if mask_anonymous:
                    d["author_label"] = "익명 교역자"
                out.append(d)
            return out

    # ---- Publications ----
    def create_publication(
        self,
        board_id: str,
        version_label: str,
        title: str,
        pdf_path: str,
        docx_path: str,
        html_snapshot: str,
        committee_report: dict[str, Any],
        law_audit: list[dict[str, Any]],
        created_by: str = "관리자",
    ) -> dict[str, Any]:
        pub_id = "pub_" + uuid.uuid4().hex[:10]
        ts = _now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO std_publications(
                    id, board_id, version_label, title, pdf_path, docx_path, html_snapshot,
                    committee_report_json, law_audit_json, published_doc_id, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?)
                """,
                (
                    pub_id,
                    board_id,
                    version_label[:30],
                    title[:160],
                    pdf_path,
                    docx_path,
                    html_snapshot,
                    json.dumps(committee_report, ensure_ascii=False),
                    json.dumps(law_audit, ensure_ascii=False),
                    created_by[:60],
                    ts,
                ),
            )
            conn.execute("UPDATE std_boards SET status = 'published', updated_at = ? WHERE id = ?", (ts, board_id))
        return self.get_publication(pub_id)  # type: ignore[return-value]

    def _row_to_pub(self, row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["committee_report"] = json.loads(d.pop("committee_report_json", "{}") or "{}")
        d["law_audit"] = json.loads(d.pop("law_audit_json", "[]") or "[]")
        return d

    def get_publication(self, pub_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM std_publications WHERE id = ?", (pub_id,)).fetchone()
            return self._row_to_pub(row) if row else None

    def list_publications(self, board_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM std_publications WHERE board_id = ? ORDER BY created_at DESC",
                (board_id,),
            ).fetchall()
            out = []
            for r in rows:
                d = self._row_to_pub(r)
                d.pop("html_snapshot", None)
                out.append(d)
            return out

    def mark_publication_linked_doc(self, pub_id: str, doc_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE std_publications SET published_doc_id = ? WHERE id = ?",
                (doc_id, pub_id),
            )
