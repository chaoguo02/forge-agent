"""
memory/store.py

MemoryStore - Long-term memory storage. Supports SQLite (primary) and file (export) backends.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from memory.models import Anchor, Memory, MemoryMetadata, MemoryScope, MemoryStatus, MemorySummary, MemoryType, normalize_memory_type, parse_memory_type

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_BASE_DIR = "~/.grace/projects"
_GLOBAL_MEMORY_DIR = "~/.grace/global/memory"
_INDEX_FILENAME = "MEMORY.md"
_FRONTMATTER_SEP = "---"
_MAX_INDEX_LINES = 200
_MAX_INDEX_BYTES = 25_600
_ARCHIVE_DIR_NAME = "archive"

_GLOBAL_MEMORY_TYPES: frozenset[MemoryType] = frozenset({MemoryType.USER, MemoryType.FEEDBACK})
_ENABLE_LLM_JUDGE = False

# Lazily imported utilities
from memory._utils import (
    atomic_write_text as _atomic_write_text,
    build_memory_file as _build_memory_file,
    needs_type_migration as _needs_type_migration,
    truncate_index as _truncate_index,
    project_hash as _project_hash,
)
from utils.frontmatter import parse_frontmatter as _parse_frontmatter

