"""
memory/store.py

MemoryStore — Facade over memory backends (SQLite or file).

Usage:
    # SQLite mode (primary):
    store = MemoryStore(repo_path=".", db_path="/path/to/sessions.db")

    # File mode (legacy):
    store = MemoryStore(repo_path=".")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from memory.backend import MemoryBackend
from memory.models import Memory, MemorySummary

logger = logging.getLogger(__name__)


def _auto_select_backend(
    repo_path: str,
    db_path: str | None = None,
    base_dir: str | None = None,
    memory_dir: str | None = None,
    max_index_lines: int = 200,
    indexer: Any | None = None,
) -> MemoryBackend:
    """Auto-select backend based on db_path presence."""
    from memory._utils import project_hash as _project_hash

    if db_path:
        from memory.sqlite_backend import SqliteMemoryBackend
        return SqliteMemoryBackend(db_path=db_path, indexer=indexer)

    from memory.file_backend import FileMemoryBackend
    if memory_dir:
        store_dir = Path(memory_dir).expanduser().resolve()
    else:
        base = Path(base_dir or "~/.grace/projects").expanduser()
        store_dir = base / _project_hash(repo_path) / "memory"
    return FileMemoryBackend(store_dir=store_dir, max_index_lines=max_index_lines, indexer=indexer)


class MemoryStore:
    """
    Facade for memory storage. Delegates all operations to a backend.

    Backend is auto-selected based on db_path parameter:
    - db_path set → SqliteMemoryBackend
    - db_path None → FileMemoryBackend (legacy)
    """

    def __init__(
        self,
        repo_path: str,
        db_path: str | None = None,
        base_dir: str | None = None,
        memory_dir: str | None = None,
        max_index_lines: int = 200,
        indexer: Any | None = None,
    ) -> None:
        self._repo_path = repo_path
        self._backend = _auto_select_backend(
            repo_path=repo_path, db_path=db_path, base_dir=base_dir,
            memory_dir=memory_dir, max_index_lines=max_index_lines, indexer=indexer,
        )

    # ── Properties for backward compat ──

    @property
    def store_dir(self):
        if hasattr(self._backend, "_store_dir"):
            return self._backend._store_dir
        from memory._utils import project_hash as _project_hash
        return Path("~/.grace/projects").expanduser() / _project_hash(self._repo_path) / "memory"

    # ── CRUD — all delegate to backend ──

    def read_memory(self, name: str) -> Memory | None:
        return self._backend.read_memory(name)

    def write_memory(self, memory: Memory, source: str = "", source_session_id: str = "") -> bool:
        return self._backend.write_memory(memory, source=source, source_session_id=source_session_id)

    def delete_memory(self, name: str) -> bool:
        return self._backend.delete_memory(name)

    def list_memories(self) -> list[MemorySummary]:
        return self._backend.list_memories()

    def count_by_type(self) -> dict[str, int]:
        return self._backend.count_by_type()

    def list_by_scope(self, scope: str = "project", min_confidence: float = 0.0) -> list[Memory]:
        return self._backend.list_by_scope(scope, min_confidence)

    def record_access(self, name: str) -> bool:
        return self._backend.record_access(name)

    def get_index_content(self, max_lines: int | None = None) -> str:
        return self._backend.get_index_content(max_lines=max_lines)

    def get_stats(self) -> dict:
        """Compute aggregate memory statistics from the store.

        Always uses the store-level computation for semantic correctness.
        The backend may provide an optimized implementation via the same
        interface, but the semantics are owned by the store layer.
        """
        from datetime import datetime, timezone, timedelta

        # Collect full Memory objects from all supported scopes
        all_memories: list = []
        for scope in ("session", "project", "global"):
            try:
                all_memories.extend(self.list_by_scope(scope))
            except Exception:
                pass

        total = len(all_memories)
        by_type: dict[str, int] = {}
        by_scope: dict[str, int] = {}
        by_layer: dict[str, int] = {"project": 0, "global": 0, "archive": 0}
        active = 0
        deprecated = 0
        archived = 0
        expiring = 0
        now = datetime.now(timezone.utc)
        seven_days = timedelta(days=7)

        for m in all_memories:
            meta = m.metadata
            t = meta.type.value if hasattr(meta.type, "value") else str(meta.type)
            s = meta.scope.value if hasattr(meta.scope, "value") else str(meta.scope)
            by_type[t] = by_type.get(t, 0) + 1
            by_scope[s] = by_scope.get(s, 0) + 1

            status_str = meta.status.value if hasattr(meta.status, "value") else str(meta.status)
            if status_str == "active":
                active += 1
            elif status_str == "deprecated":
                deprecated += 1
                by_layer["archive"] = by_layer.get("archive", 0) + 1
                archived += 1

            if meta.expires_at:
                try:
                    expires = datetime.fromisoformat(meta.expires_at.replace("Z", "+00:00"))
                    if now < expires < now + seven_days:
                        expiring += 1
                except (ValueError, TypeError):
                    pass

            # Layer: derive from status (active→project, deprecated→archive)
            layer = "archive" if status_str == "deprecated" else "project"
            by_layer[layer] = by_layer.get(layer, 0) + 1

        return {
            "total": total, "active": active, "deprecated": deprecated,
            "archived": archived, "expiring": expiring,
            "by_type": by_type, "by_scope": by_scope, "by_layer": by_layer,
        }

    def export_to_files(self, target_dir: str | None = None) -> int:
        """Export all memories as .md files with YAML frontmatter.

        Args:
            target_dir: Output directory. Defaults to ~/.grace/projects/<hash>/memory/.

        Returns:
            Number of files written.
        """
        from memory.file_backend import FileMemoryBackend
        from memory._utils import project_hash as _project_hash

        if target_dir is None:
            store_dir = Path("~/.grace/projects").expanduser() / _project_hash(self._repo_path) / "memory"
        else:
            store_dir = Path(target_dir).expanduser().resolve()

        exporter = FileMemoryBackend(store_dir=store_dir)
        count = 0
        for s in self.list_memories():
            mem = self.read_memory(s.name)
            if mem is None:
                continue
            if exporter.write_memory(mem):
                count += 1
        # Write MEMORY.md index
        index_content = self.get_index_content()
        if index_content:
            (store_dir / "MEMORY.md").write_text(index_content, encoding="utf-8")
        return count

    def export_one(self, name: str, target_dir: str | None = None) -> bool:
        """Export a single memory as .md file."""
        mem = self.read_memory(name)
        if mem is None:
            return False
        from memory.file_backend import FileMemoryBackend
        from memory._utils import project_hash as _project_hash
        if target_dir is None:
            store_dir = Path("~/.grace/projects").expanduser() / _project_hash(self._repo_path) / "memory"
        else:
            store_dir = Path(target_dir).expanduser().resolve()
        exporter = FileMemoryBackend(store_dir=store_dir)
        return exporter.write_memory(mem)


    def prune_expired(self) -> int:
        """Prune expired and low-confidence memories.

        Delegates to the backend's decay + deprecation logic:
        - Low-access memories (>90 days): confidence *= 0.9
        - Ultra-low-confidence (< 0.2): auto-deprecated
        - Expired TTL: status → deprecated

        Returns number of affected rows.
        """
        changed = 0
        try:
            if hasattr(self._backend, "decay_confidences"):
                changed += self._backend.decay_confidences()
            if hasattr(self._backend, "prune_expired_ttl"):
                changed += self._backend.prune_expired_ttl()
        except Exception:
            logger.exception("prune_expired failed")
        return changed


# ── TwoTierMemoryStore ─────────────────────────────────────────────────────


class TwoTierMemoryStore(MemoryStore):
    """Two-tier memory: project + global scopes. Kept for backward compatibility.

    In SQLite mode, user/feedback types go to global scope, project/reference to project scope.
    """

    def __init__(
        self,
        repo_path: str,
        db_path: str | None = None,
        base_dir: str | None = None,
        memory_dir: str | None = None,
        global_dir: str | None = None,
        max_index_lines: int = 200,
        indexer: Any | None = None,
    ) -> None:
        super().__init__(repo_path=repo_path, db_path=db_path, base_dir=base_dir,
                         memory_dir=memory_dir, max_index_lines=max_index_lines, indexer=indexer)
        _ = global_dir  # kept for API compat

    def write_memory(self, memory: Memory, source: str = "") -> bool:
        from memory.models import MemoryType
        if memory.metadata.type in (MemoryType.USER, MemoryType.FEEDBACK):
            memory.metadata.scope = "global"
        else:
            memory.metadata.scope = "project"
        return super().write_memory(memory, source=source)
