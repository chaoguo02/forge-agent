"""
memory/models.py

记忆数据模型。

记忆是带 YAML frontmatter 的 Markdown 文件，格式参照 Claude Code 的 auto memory：
- 每个文件一条记忆
- MEMORY.md 作为索引，启动时注入上下文
- 主题文件按需读取
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

MemoryType = Literal["episodic", "semantic", "procedural"]

_LEGACY_TYPE_MAP: dict[str, MemoryType] = {
    "user": "episodic",
    "feedback": "procedural",
    "project": "semantic",
    "reference": "semantic",
}
_VALID_MEMORY_TYPES = frozenset({"episodic", "semantic", "procedural"})


@dataclass
class Anchor:
    """记忆锚点：将记忆关联到文件、符号或任务类型。"""
    kind: str
    path: str | None = None
    name: str | None = None
    value: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key in ("kind", "path", "name", "value")
            if (value := getattr(self, key)) is not None
        }


@dataclass
class MemoryMetadata:
    """记忆元数据。"""
    type: str = "semantic"  # "episodic" | "semantic" | "procedural"
    stale: bool = False
    access_count: int = 0
    validated_at: str = ""


@dataclass
class Memory:
    """
    单条记忆。

    name 是 slug（短横线命名），同时也是文件名（{name}.md）。
    description 是一行摘要，LLM 用它判断是否相关。
    content 是 markdown 正文。
    anchors 将记忆绑定到文件、符号或任务类型，用于精确检索。
    """
    name: str
    description: str
    content: str
    metadata: MemoryMetadata = field(default_factory=MemoryMetadata)
    updated_at: str = field(default_factory=lambda: _now())
    anchors: list[Anchor] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "type": self.metadata.type,
            "updated_at": self.updated_at,
            "content": self.content,
            "anchors": [anchor.to_dict() for anchor in self.anchors],
        }


@dataclass
class MemorySummary:
    """
    记忆摘要（不含正文），用于列表和索引。
    MEMORY.md 中的每一行对应一个 MemorySummary。
    """
    name: str
    description: str
    type: str
    updated_at: str = ""


def normalize_memory_type(raw_type: str | None) -> str:
    """将旧类型名映射为新三分法类型。"""
    if not raw_type:
        return "semantic"
    mapped = _LEGACY_TYPE_MAP.get(raw_type, raw_type)
    if mapped in _VALID_MEMORY_TYPES:
        return mapped
    return "semantic"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
