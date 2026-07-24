"""
Memory backend protocol and implementations.

Defines the abstraction boundary between MemoryStore (facade) and its
storage backends (SQLite, file system).
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from memory.models import Memory, MemorySummary

logger = logging.getLogger(__name__)


class MemoryBackend(Protocol):
    """Protocol that all memory backends must implement."""

    def read_memory(self, name: str) -> Memory | None:
        """Read a single memory by name. Returns None if not found."""
        ...

    def write_memory(self, memory: Memory, source: str = "", source_session_id: str = "", source_run_id: str = "") -> bool:
        """Create or overwrite a memory. Returns True on success."""
        ...

    def delete_memory(self, name: str) -> bool:
        """Delete a memory by name. Returns True if deleted or not found."""
        ...

    def list_memories(self) -> list[MemorySummary]:
        """List all memory summaries."""
        ...

    def list_by_scope(self, scope: str, min_confidence: float = 0.0) -> list[Memory]:
        """List memories by scope with minimum confidence filter."""
        ...

    def count_by_type(self) -> dict[str, int]:
        """Return counts of memories grouped by type."""
        ...

    def record_access(self, name: str) -> bool:
        """Increment access_count for a memory."""
        ...

    def get_index_content(self, max_lines: int | None = None) -> str:
        """Return index content (MEMORY.md equivalent) for context injection."""
        ...
