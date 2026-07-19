"""SQLite storage backend — wraps existing SessionStore behind StorageBackend.

This is a thin adapter that converts ``SessionStore`` method calls to the
``StorageBackend`` protocol.  No new SQL or table logic lives here — it
delegates entirely to ``agent/session/session_store.py``.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from agent.session.models import (
    AgentCompletionNotification,
    AgentKind,
    AgentRunResult,
    SessionMode,
    SessionRecord,
    SessionStatus,
)
from agent.session.session_store import SessionStore
from llm.base import LLMMessage

from .protocol import StorageBackend, StorageStats

logger = logging.getLogger(__name__)


class SqliteStorageBackend(StorageBackend):
    """SQLite implementation of StorageBackend.

    Wraps ``SessionStore`` from ``agent/session/session_store.py``.
    The database location is determined by ``default_session_db_path(repo_path)``.

    Usage::

        backend = SqliteStorageBackend(db_path)
        session = backend.create_session(
            agent_name="build", mode=SessionMode.PRIMARY,
            repo_path="/repo", title="My Session",
        )
    """

    def __init__(self, db_path: str) -> None:
        self._store = SessionStore(db_path)
        self._start_time = time.time()
        self._db_path = db_path
        self._init_stats_tables()
        self._init_memory_tables()
        logger.debug("SqliteStorageBackend initialized: %s", db_path)

    def _init_stats_tables(self) -> None:
        """Create stats/diff/review tables if they don't exist."""
        try:
            with self._store._connect() as conn:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS session_stats (
                        session_id TEXT PRIMARY KEY,
                        agent_name TEXT NOT NULL,
                        total_steps INTEGER NOT NULL DEFAULT 0,
                        total_tokens INTEGER NOT NULL DEFAULT 0,
                        total_duration_ms INTEGER NOT NULL DEFAULT 0,
                        status TEXT NOT NULL,
                        tool_summary TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS step_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        step_number INTEGER NOT NULL,
                        tool_name TEXT NOT NULL,
                        tool_params TEXT NOT NULL DEFAULT '{}',
                        status TEXT NOT NULL DEFAULT 'success',
                        duration_ms INTEGER NOT NULL DEFAULT 0,
                        tokens INTEGER NOT NULL DEFAULT 0,
                        timestamp TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_step_log_session
                        ON step_log(session_id, step_number);

                    CREATE TABLE IF NOT EXISTS session_diffs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        step_number INTEGER NOT NULL DEFAULT 0,
                        file_path TEXT NOT NULL,
                        diff_content TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending',
                        review_comment TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_session_diffs_session
                        ON session_diffs(session_id);

                    CREATE TABLE IF NOT EXISTS daily_rollup (
                        date TEXT PRIMARY KEY,
                        session_count INTEGER NOT NULL DEFAULT 0,
                        total_tokens INTEGER NOT NULL DEFAULT 0,
                        total_duration_ms INTEGER NOT NULL DEFAULT 0,
                        tool_summary TEXT NOT NULL DEFAULT '{}',
                        status_summary TEXT NOT NULL DEFAULT '{}'
                    );
                """)
        except Exception:
            logger.exception("Failed to create stats tables")

    def _init_memory_tables(self) -> None:
        """Create memory store tables if they don't exist."""
        try:
            with self._store._connect() as conn:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS memory_entries (
                        name TEXT PRIMARY KEY,
                        description TEXT NOT NULL,
                        content TEXT NOT NULL DEFAULT '',
                        type TEXT NOT NULL DEFAULT 'project',
                        status TEXT NOT NULL DEFAULT 'active',
                        scope TEXT NOT NULL DEFAULT 'project',
                        confidence REAL NOT NULL DEFAULT 0.7,
                        access_count INTEGER NOT NULL DEFAULT 0,
                        source TEXT NOT NULL DEFAULT '',
                        source_session_id TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS memory_anchors (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        memory_name TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        path TEXT,
                        symbol_name TEXT,
                        task_value TEXT,
                        content_hash TEXT,
                        FOREIGN KEY (memory_name) REFERENCES memory_entries(name) ON DELETE CASCADE
                    );

                    CREATE INDEX IF NOT EXISTS idx_memory_type ON memory_entries(type);
                    CREATE INDEX IF NOT EXISTS idx_memory_status ON memory_entries(status);
                    CREATE INDEX IF NOT EXISTS idx_memory_scope ON memory_entries(scope);
                    CREATE INDEX IF NOT EXISTS idx_memory_confidence ON memory_entries(confidence DESC);
                    CREATE INDEX IF NOT EXISTS idx_memory_anchors_name ON memory_anchors(memory_name);
                """)
        except Exception:
            logger.exception("Failed to create memory tables")

    @property
    def store(self) -> SessionStore:
        """Access the underlying SessionStore (for advanced operations)."""
        return self._store

    # ── Session CRUD ──────────────────────────────────────────────────────

    def create_session(
        self,
        *,
        agent_name: str,
        mode: SessionMode,
        repo_path: str,
        title: str,
        agent_kind: AgentKind = AgentKind.PRIMARY,
        parent_id: str | None = None,
        root_id: str | None = None,
        metadata: dict | None = None,
    ) -> SessionRecord:
        return self._store.create_session(
            agent_name=agent_name,
            mode=mode,
            agent_kind=agent_kind,
            repo_path=repo_path,
            title=title,
            parent_id=parent_id,
            root_id=root_id,
            metadata=metadata,
        )

    def get_session(self, session_id: str) -> SessionRecord | None:
        return self._store.get_session(session_id)

    def list_sessions(
        self, limit: int = 50, offset: int = 0,
    ) -> list[SessionRecord]:
        return self._store.list_sessions(limit=limit, offset=offset)

    def update_status(
        self, session_id: str, status: SessionStatus, error: str = "",
    ) -> None:
        self._store.update_status(session_id, status, error=error)

    def set_summary(
        self, session_id: str, summary: str, *, status: SessionStatus,
    ) -> None:
        self._store.set_summary(session_id, summary, status=status)

    def delete_session(self, session_id: str) -> bool:
        session = self._store.get_session(session_id)
        if session is None:
            return False
        try:
            with self._store._connect() as conn:
                conn.execute("DELETE FROM session_messages WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM agent_notifications WHERE parent_session_id = ?", (session_id,))
                conn.execute("DELETE FROM agent_notifications WHERE child_session_id = ?", (session_id,))
                conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            return True
        except Exception:
            logger.exception("Failed to delete session %s", session_id)
            return False

    def delete_sessions_batch(self, session_ids: list[str]) -> int:
        """Delete multiple sessions in one transaction. Returns count deleted."""
        if not session_ids:
            return 0
        deleted = 0
        try:
            with self._store._connect() as conn:
                for sid in session_ids:
                    conn.execute("DELETE FROM session_messages WHERE session_id = ?", (sid,))
                    conn.execute("DELETE FROM agent_notifications WHERE parent_session_id = ?", (sid,))
                    conn.execute("DELETE FROM agent_notifications WHERE child_session_id = ?", (sid,))
                    c = conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))
                    if c.rowcount > 0:
                        deleted += 1
            logger.info("Batch deleted %d/%d sessions", deleted, len(session_ids))
            return deleted
        except Exception:
            logger.exception("Failed to batch delete sessions")
            return deleted

    def update_title(self, session_id: str, title: str) -> bool:
        """Update a session's title. Returns True if updated."""
        session = self._store.get_session(session_id)
        if session is None:
            return False
        try:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()
            with self._store._connect() as conn:
                conn.execute(
                    "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
                    (title[:200], now, session_id),
                )
            return True
        except Exception:
            logger.exception("Failed to update title for %s", session_id)
            return False

    def update_agent_name(self, session_id: str, agent_name: str) -> bool:
        """Update a session's agent_name. Returns True if updated."""
        session = self._store.get_session(session_id)
        if session is None:
            return False
        try:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()
            with self._store._connect() as conn:
                conn.execute(
                    "UPDATE sessions SET agent_name = ?, updated_at = ? WHERE id = ?",
                    (agent_name, now, session_id),
                )
            return True
        except Exception:
            logger.exception("Failed to update agent_name for %s", session_id)
            return False

    # ── Messages ──────────────────────────────────────────────────────────

    def append_message(
        self, session_id: str, message: LLMMessage,
    ) -> None:
        self._store.append_message(session_id, message)

    def list_messages(self, session_id: str) -> list[LLMMessage]:
        return self._store.list_messages(session_id)

    def count_messages(self, session_id: str) -> int:
        session = self._store.get_session(session_id)
        if session is None:
            return 0
        return len(self._store.list_messages(session_id))

    # ── Child / fork sessions ────────────────────────────────────────────

    def list_child_sessions(self, parent_id: str) -> list[SessionRecord]:
        return self._store.list_child_sessions(parent_id)

    # ── Agent notifications ──────────────────────────────────────────────

    def append_notification(
        self, notification: AgentCompletionNotification,
    ) -> None:
        self._store.append_agent_notification(notification)

    def claim_pending_notifications(
        self, parent_session_id: str,
    ) -> tuple[AgentCompletionNotification, ...]:
        return self._store.claim_pending_agent_notifications(parent_session_id)

    # ── Session resume ────────────────────────────────────────────────────

    def prepare_resume(
        self, session_id: str, message: LLMMessage,
    ) -> SessionRecord:
        return self._store.prepare_session_resume(session_id, message)

    # ── Agent result ──────────────────────────────────────────────────────

    def set_agent_result(
        self, session_id: str, result: AgentRunResult,
    ) -> None:
        self._store.set_agent_result(session_id, result)

    # ── Execution stats ──────────────────────────────────────────────────

    def upsert_session_stats(
        self, session_id: str, *, agent_name: str, total_steps: int,
        total_tokens: int, total_duration_ms: int, status: str,
        tool_summary: str,
    ) -> None:
        try:
            with self._store._connect() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO session_stats
                       (session_id, agent_name, total_steps, total_tokens,
                        total_duration_ms, status, tool_summary, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                    (session_id, agent_name, total_steps, total_tokens,
                     total_duration_ms, status, tool_summary),
                )
        except Exception:
            logger.exception("Failed to upsert session_stats %s", session_id)

    def insert_step_log(
        self, session_id: str, *, step_number: int, tool_name: str,
        tool_params: str, status: str, duration_ms: int, tokens: int,
        timestamp: str,
    ) -> None:
        try:
            with self._store._connect() as conn:
                conn.execute(
                    """INSERT INTO step_log
                       (session_id, step_number, tool_name, tool_params,
                        status, duration_ms, tokens, timestamp)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (session_id, step_number, tool_name, tool_params,
                     status, duration_ms, tokens, timestamp),
                )
        except Exception:
            logger.exception("Failed to insert step_log %s step=%d",
                             session_id, step_number)

    def insert_session_diff(
        self, session_id: str, *, step_number: int, file_path: str,
        diff_content: str,
    ) -> int:
        try:
            with self._store._connect() as conn:
                cur = conn.execute(
                    """INSERT INTO session_diffs
                       (session_id, step_number, file_path, diff_content,
                        status, created_at)
                       VALUES (?, ?, ?, ?, 'pending', datetime('now'))""",
                    (session_id, step_number, file_path, diff_content),
                )
                return cur.lastrowid or 0
        except Exception:
            logger.exception("Failed to insert session_diff %s", session_id)
            return 0

    def get_session_diffs(
        self, session_id: str, status: str | None = None,
    ) -> list[dict]:
        try:
            with self._store._connect() as conn:
                if status:
                    rows = conn.execute(
                        "SELECT * FROM session_diffs WHERE session_id=? AND status=? ORDER BY id",
                        (session_id, status),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM session_diffs WHERE session_id=? ORDER BY id",
                        (session_id,),
                    ).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            logger.exception("Failed to get_session_diffs %s", session_id)
            return []

    def update_diff_status(
        self, diff_id: int, status: str, comment: str = "",
    ) -> bool:
        try:
            with self._store._connect() as conn:
                cur = conn.execute(
                    "UPDATE session_diffs SET status=?, review_comment=? WHERE id=?",
                    (status, comment, diff_id),
                )
                return cur.rowcount > 0
        except Exception:
            logger.exception("Failed to update_diff_status %d", diff_id)
            return False

    def upsert_daily_rollup(
        self, date: str, *, session_count: int, total_tokens: int,
        total_duration_ms: int, tool_summary: str, status_summary: str,
    ) -> None:
        try:
            with self._store._connect() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO daily_rollup
                       (date, session_count, total_tokens, total_duration_ms,
                        tool_summary, status_summary)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (date, session_count, total_tokens, total_duration_ms,
                     tool_summary, status_summary),
                )
        except Exception:
            logger.exception("Failed to upsert daily_rollup %s", date)

    def get_daily_rollups(self, days: int = 30) -> list[dict]:
        try:
            with self._store._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM daily_rollup ORDER BY date DESC LIMIT ?",
                    (days,),
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            logger.exception("Failed to get_daily_rollups")
            return []

    def get_session_stats(self, session_id: str) -> dict | None:
        try:
            with self._store._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM session_stats WHERE session_id=?",
                    (session_id,),
                ).fetchone()
                return dict(row) if row else None
        except Exception:
            return None

    def get_session_steps(self, session_id: str) -> list[dict]:
        try:
            with self._store._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM step_log WHERE session_id=? ORDER BY step_number",
                    (session_id,),
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []

    # ── Memory store ────────────────────────────────────────────────────

    def upsert_memory_entry(
        self, name: str, *, description: str, content: str,
        type_: str, status: str, scope: str, confidence: float,
        access_count: int = 0, source: str = "", source_session_id: str = "",
    ) -> None:
        """Insert or replace a memory entry in the DB."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self._store._connect() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO memory_entries
                       (name, description, content, type, status, scope,
                        confidence, access_count, source, source_session_id,
                        created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                               COALESCE((SELECT created_at FROM memory_entries WHERE name=?), ?), ?)""",
                    (name, description, content, type_, status, scope,
                     confidence, access_count, source, source_session_id,
                     name, now, now),
                )
        except Exception:
            logger.exception("Failed to upsert memory entry %s", name)

    def set_memory_anchors(self, memory_name: str, anchors: list[dict]) -> None:
        """Replace all anchors for a memory entry."""
        try:
            with self._store._connect() as conn:
                conn.execute("DELETE FROM memory_anchors WHERE memory_name=?", (memory_name,))
                for a in anchors:
                    conn.execute(
                        """INSERT INTO memory_anchors
                           (memory_name, kind, path, symbol_name, task_value, content_hash)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (memory_name, a.get("kind", ""), a.get("path"),
                         a.get("name"), a.get("value"), a.get("content_hash", "")),
                    )
        except Exception:
            logger.exception("Failed to set anchors for %s", memory_name)

    def get_memory_anchors(self, memory_name: str) -> list[dict]:
        """Get all anchors for a memory entry."""
        try:
            with self._store._connect() as conn:
                rows = conn.execute(
                    "SELECT kind, path, symbol_name, task_value, content_hash FROM memory_anchors WHERE memory_name=?",
                    (memory_name,),
                ).fetchall()
                result = []
                for r in rows:
                    item = {"kind": r["kind"]}
                    if r["path"]: item["path"] = r["path"]
                    if r["symbol_name"]: item["name"] = r["symbol_name"]
                    if r["task_value"]: item["value"] = r["task_value"]
                    if r["content_hash"]: item["content_hash"] = r["content_hash"]
                    result.append(item)
                return result
        except Exception:
            return []

    def query_memories(
        self, *, type_: str | None = None, status: str | None = None,
        scope: str | None = None, confidence_min: float | None = None,
        limit: int = 100, offset: int = 0,
    ) -> list[dict]:
        """Query memory entries with filters. Returns full rows."""
        clauses: list[str] = []
        params: list = []
        if type_:
            clauses.append("type = ?"); params.append(type_)
        if status:
            clauses.append("status = ?"); params.append(status)
        if scope:
            clauses.append("scope = ?"); params.append(scope)
        if confidence_min is not None:
            clauses.append("confidence >= ?"); params.append(confidence_min)
        where = " AND ".join(clauses) if clauses else "1"
        try:
            with self._store._connect() as conn:
                rows = conn.execute(
                    f"SELECT * FROM memory_entries WHERE {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                    (*params, limit, offset),
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            logger.exception("Failed to query memories")
            return []

    def get_memory_entry(self, name: str) -> dict | None:
        """Get a single memory entry by name."""
        try:
            with self._store._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM memory_entries WHERE name=?", (name,),
                ).fetchone()
                return dict(row) if row else None
        except Exception:
            return None

    def delete_memory_entry(self, name: str) -> bool:
        """Delete a memory entry and its anchors."""
        try:
            with self._store._connect() as conn:
                conn.execute("DELETE FROM memory_anchors WHERE memory_name=?", (name,))
                cur = conn.execute("DELETE FROM memory_entries WHERE name=?", (name,))
                return cur.rowcount > 0
        except Exception:
            logger.exception("Failed to delete memory entry %s", name)
            return False

    def get_memory_overview(self) -> dict:
        """Return aggregate stats across all memories."""
        try:
            with self._store._connect() as conn:
                total = conn.execute("SELECT COUNT(*) AS c FROM memory_entries").fetchone()["c"]
                active = conn.execute("SELECT COUNT(*) AS c FROM memory_entries WHERE status='active'").fetchone()["c"]
                deprecated_c = conn.execute("SELECT COUNT(*) AS c FROM memory_entries WHERE status='deprecated'").fetchone()["c"]
                archived = conn.execute(
                    "SELECT COUNT(*) AS c FROM memory_entries WHERE status='deprecated'"
                ).fetchone()["c"]
                by_type = {
                    r["type"]: r["cnt"]
                    for r in conn.execute("SELECT type, COUNT(*) AS cnt FROM memory_entries GROUP BY type").fetchall()
                }
                by_scope = {
                    r["scope"]: r["cnt"]
                    for r in conn.execute("SELECT scope, COUNT(*) AS cnt FROM memory_entries GROUP BY scope").fetchall()
                }
                by_layer = {"project": active, "global": 0, "archive": archived}
                expiring = conn.execute(
                    "SELECT COUNT(*) AS c FROM memory_entries WHERE status='active' AND confidence < 0.5"
                ).fetchone()["c"]
                return {
                    "total": total, "active": active, "deprecated": deprecated_c,
                    "archived": archived, "expiring": expiring,
                    "enabled": True, "preview": False,
                    "by_type": by_type, "by_scope": by_scope, "by_layer": by_layer,
                }
        except Exception:
            return {"total": 0, "active": 0, "deprecated": 0, "archived": 0, "expiring": 0,
                    "enabled": True, "preview": False,
                    "by_type": {}, "by_scope": {}, "by_layer": {}}

    def sync_memory_from_files(self, repo_path: str) -> int:
        """Scan file-based MemoryStore and sync entries into DB.

        Returns the number of entries synced.
        """
        try:
            from memory.store import MemoryStore
            store = MemoryStore(repo_path=repo_path)
            summaries = store.list_memories()
            count = 0
            for s in summaries:
                mem = store.read_memory(s.name)
                if mem is None:
                    continue
                self.upsert_memory_entry(
                    name=mem.name,
                    description=mem.description,
                    content=mem.content,
                    type_=mem.metadata.type,
                    status=mem.metadata.status,
                    scope=mem.metadata.scope,
                    confidence=mem.metadata.confidence,
                    access_count=mem.metadata.access_count,
                )
                count += 1
            logger.info("Synced %d memories from files to DB", count)
            return count
        except Exception:
            logger.exception("Failed to sync memories from files")
            return 0

    def decay_confidences(self) -> int:
        """Decay confidence for low-access memories. Auto-deprecates very old ones.

        Rules:
        - access_count < 3 AND updated > 90 days ago → confidence *= 0.9
        - confidence < 0.2 AND status='active' → auto-deprecated
        Returns number of memories updated.
        """
        try:
            with self._store._connect() as conn:
                # Decay
                cur = conn.execute(
                    """UPDATE memory_entries SET confidence = MAX(0.1, confidence * 0.9)
                       WHERE access_count < 3
                       AND updated_at < datetime('now', '-90 days')
                       AND status='active'"""
                )
                decayed = cur.rowcount
                # Auto-deprecate very low confidence
                cur2 = conn.execute(
                    """UPDATE memory_entries SET status='deprecated'
                       WHERE confidence < 0.2 AND status='active'"""
                )
                deprecated = cur2.rowcount
                if decayed or deprecated:
                    logger.info("Decayed %d, auto-deprecated %d memories", decayed, deprecated)
                return decayed + deprecated
        except Exception:
            logger.exception("Failed to decay confidences")
            return 0

    # ── Storage admin ─────────────────────────────────────────────────────

    def get_stats(self) -> StorageStats:
        """Return SQLite backend statistics."""
        db_size = None
        try:
            db_path = Path(self._db_path)
            if db_path.is_file():
                db_size = db_path.stat().st_size
        except OSError:
            pass

        total_sessions = 0
        total_messages = 0
        try:
            with self._store._connect() as conn:
                row = conn.execute("SELECT COUNT(*) AS cnt FROM sessions").fetchone()
                if row:
                    total_sessions = row["cnt"]
        except Exception:
            pass
        try:
            with self._store._connect() as conn:
                row = conn.execute("SELECT COUNT(*) AS cnt FROM session_messages").fetchone()
                if row:
                    total_messages = row["cnt"]
        except Exception:
            pass

        return StorageStats(
            backend="sqlite",
            total_sessions=total_sessions,
            total_messages=total_messages,
            db_size_bytes=db_size,
            uptime_seconds=time.time() - self._start_time,
        )

    def ping(self) -> bool:
        try:
            with self._store._connect():
                return True
        except Exception:
            return False

    def close(self) -> None:
        """SQLite backend does not hold persistent connections — nothing to close."""
        pass
