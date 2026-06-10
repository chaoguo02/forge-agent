"""
memory/context.py

MemoryContext — 管理记忆在 LLM 上下文中的注入。
"""

from __future__ import annotations

from memory.store import MemoryStore


class MemoryContext:
    """
    管理记忆在 agent 上下文中的注入。

    职责：
    - 构建要注入 system prompt 的 Memory Section
    - 控制注入时机（首次启动或 token 预算允许时）
    """

    def __init__(
        self,
        store: MemoryStore,
        max_lines: int = 50,
        enabled: bool = True,
    ) -> None:
        self._store = store
        self._max_lines = max_lines
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    def build_memory_section(self) -> str:
        """
        构建 Memory Section 文本，用于注入 system prompt。

        返回格式：
            ## Available Memories
            <MEMORY.md 的前 N 行>

            Use memory_read to read a specific memory, memory_write to save new information.

        没有记忆时返回空字符串。
        """
        if not self._enabled:
            return ""

        index_content = self._store.get_index_content(max_lines=self._max_lines)
        if not index_content.strip():
            return ""

        lines = [
            "## Available Memories",
            index_content,
            "",
            "Use memory_read to read a specific memory, memory_write to",
            "save new information you want to remember across sessions.",
        ]
        return "\n".join(lines)
