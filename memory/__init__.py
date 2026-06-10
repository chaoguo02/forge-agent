"""
memory/__init__.py

长期记忆模块，提供跨会话持久化存储。

用法：
    store = MemoryStore(repo_path)
    store.write_memory(Memory(name="build-cmd", description="...", content="..."))
    mem = store.read_memory("build-cmd")
    summaries = store.list_memories()
    store.delete_memory("build-cmd")
"""

from memory.models import Memory, MemoryMetadata, MemorySummary
from memory.store import MemoryStore

__all__ = [
    "Memory",
    "MemoryMetadata",
    "MemorySummary",
    "MemoryStore",
]
