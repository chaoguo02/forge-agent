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


@dataclass
class MemoryMetadata:
    """记忆元数据。"""
    type: str = "reference"  # "user" | "feedback" | "project" | "reference"


@dataclass
class Memory:
    """
    单条记忆。

    name 是 slug（短横线命名），同时也是文件名（{name}.md）。
    description 是一行摘要，LLM 用它判断是否相关。
    content 是 markdown 正文。
    """
    name: str
    description: str
    content: str
    metadata: MemoryMetadata = field(default_factory=MemoryMetadata)
    updated_at: str = field(default_factory=lambda: _now())

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "type": self.metadata.type,
            "updated_at": self.updated_at,
            "content": self.content,
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


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
