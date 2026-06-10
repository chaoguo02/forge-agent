"""
memory/store.py

MemoryStore — 文件型长期记忆存储。

目录结构：
    ~/.forge-agent/projects/<project-hash>/memory/
    ├── MEMORY.md          # 索引文件（启动时注入前 N 行）
    ├── build-commands.md  # 主题文件
    ├── debugging.md
    └── ...

MEMORY.md 格式：
    # Memory Index

    - [build-commands](build-commands.md) — Build, test, and lint commands
    - [debugging](debugging.md) — Common debugging patterns

主题文件格式（YAML frontmatter + Markdown）：
    ---
    name: build-commands
    description: Build, test, and lint commands
    metadata:
      type: project
    ---

    ## Build
    ...
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any

import yaml

from memory.models import Memory, MemoryMetadata, MemorySummary

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_DEFAULT_BASE_DIR = "~/.forge-agent/projects"
_INDEX_FILENAME = "MEMORY.md"
_FRONTMATTER_SEP = "---"
_MAX_INDEX_LINES = 200  # MEMORY.md 默认最大行数

# ---------------------------------------------------------------------------
# YAML frontmatter 解析
# ---------------------------------------------------------------------------

_FM_RE = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n(.*)",
    re.DOTALL,
)


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """
    解析 YAML frontmatter + Markdown 正文。

    Returns:
        (frontmatter_dict, body_text)
        没有 frontmatter 时 frontmatter_dict 为空字典。
    """
    m = _FM_RE.match(text)
    if not m:
        return {}, text.strip()
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        fm = {}
    body = m.group(2).strip()
    return fm, body


def _build_frontmatter(memory: Memory) -> str:
    """从 Memory 对象生成 YAML frontmatter 字符串。"""
    fm = {
        "name": memory.name,
        "description": memory.description,
        "metadata": {
            "type": memory.metadata.type,
        },
    }
    return yaml.dump(fm, default_flow_style=False, allow_unicode=True).strip()


def _build_memory_file(memory: Memory) -> str:
    """组装完整的记忆文件内容（frontmatter + body）。"""
    fm = _build_frontmatter(memory)
    return f"---\n{fm}\n---\n\n{memory.content.strip()}\n"


def _project_hash(repo_path: str) -> str:
    """从项目路径生成短哈希，用于隔离不同项目的记忆目录。"""
    return hashlib.sha256(repo_path.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# MemoryStore
# ---------------------------------------------------------------------------

class MemoryStore:
    """
    文件型记忆存储。

    Args:
        repo_path:    项目根目录路径（用于生成项目标识）
        base_dir:     记忆根目录，默认 ~/.forge-agent/projects
        memory_dir:   可选，直接指定记忆目录（覆盖自动计算）
        max_index_lines: MEMORY.md 每次注入的最大行数
    """

    def __init__(
        self,
        repo_path: str,
        base_dir: str | None = None,
        memory_dir: str | None = None,
        max_index_lines: int = _MAX_INDEX_LINES,
    ) -> None:
        if memory_dir:
            self._store_dir = Path(memory_dir).expanduser().resolve()
        else:
            base = Path(base_dir or _DEFAULT_BASE_DIR).expanduser()
            self._store_dir = base / _project_hash(repo_path) / "memory"
        self._max_index_lines = max_index_lines
        self._ensure_dir()

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def store_dir(self) -> Path:
        """记忆文件存放目录。"""
        return self._store_dir

    @property
    def index_path(self) -> Path:
        """MEMORY.md 索引文件路径。"""
        return self._store_dir / _INDEX_FILENAME

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def read_memory(self, name: str) -> Memory | None:
        """
        读取一条记忆。

        Args:
            name: 记忆名称（slug），对应 {name}.md

        Returns:
            Memory 对象，不存在时返回 None
        """
        path = self._file_path(name)
        if not path.exists():
            return None
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to read memory %s: %s", name, exc)
            return None

        fm, body = _parse_frontmatter(text)
        meta = fm.get("metadata", {})
        return Memory(
            name=fm.get("name", name),
            description=fm.get("description", ""),
            content=body,
            metadata=MemoryMetadata(
                type=meta.get("type", "reference"),
            ),
            updated_at=fm.get("updated_at", ""),
        )

    def write_memory(self, memory: Memory) -> bool:
        """
        写入一条记忆（创建或覆盖）。

        自动更新 MEMORY.md 索引。

        Args:
            memory: Memory 对象

        Returns:
            True 表示成功
        """
        content = _build_memory_file(memory)
        path = self._file_path(memory.name)
        try:
            path.write_text(content, encoding="utf-8")
        except OSError as exc:
            logger.error("Failed to write memory %s: %s", memory.name, exc)
            return False
        self._rebuild_index()
        return True

    def list_memories(self) -> list[MemorySummary]:
        """
        列出所有记忆摘要。

        从 MEMORY.md 索引文件读取；索引不存在时扫描目录重建。

        Returns:
            MemorySummary 列表
        """
        if self.index_path.exists():
            summaries = self._parse_index(self.index_path.read_text(encoding="utf-8"))
            if summaries:
                return summaries
        # 降级：扫描目录
        return self._scan_dir()

    def delete_memory(self, name: str) -> bool:
        """
        删除一条记忆。

        Args:
            name: 记忆名称（slug）

        Returns:
            True 表示成功（文件不存在也返回 True）
        """
        path = self._file_path(name)
        if not path.exists():
            return True
        try:
            path.unlink()
        except OSError as exc:
            logger.error("Failed to delete memory %s: %s", name, exc)
            return False
        self._rebuild_index()
        return True

    # ------------------------------------------------------------------
    # 上下文注入
    # ------------------------------------------------------------------

    def get_index_content(self, max_lines: int | None = None) -> str:
        """
        获取 MEMORY.md 的内容（前 max_lines 行），用于注入 LLM 上下文。

        Args:
            max_lines: 最大行数，默认使用 self._max_index_lines

        Returns:
            MEMORY.md 的纯文本内容，空 store 返回空字符串
        """
        if not self.index_path.exists():
            # 索引不存在但可能有记忆文件
            self._rebuild_index()
        if not self.index_path.exists():
            return ""

        text = self.index_path.read_text(encoding="utf-8").strip()
        # 索引只有标题行（没有记忆条目）时返回空
        if text.count("\n") == 0 and ("# Memory Index" in text or not text):
            return ""

        limit = max_lines if max_lines is not None else self._max_index_lines
        lines = text.splitlines()
        if len(lines) > limit:
            lines = lines[:limit]
            lines.append(f"... [{len(lines) - limit} lines omitted]")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _file_path(self, name: str) -> Path:
        """返回 {name}.md 的完整路径。"""
        return self._store_dir / f"{name}.md"

    def _ensure_dir(self) -> None:
        """确保记忆目录存在。"""
        self._store_dir.mkdir(parents=True, exist_ok=True)

    def _rebuild_index(self) -> None:
        """
        从目录中的 .md 文件重建 MEMORY.md 索引。
        排除 MEMORY.md 自身。
        """
        summaries = self._scan_dir()
        lines = ["# Memory Index\n"]
        for s in summaries:
            lines.append(
                f"- [{s.name}]({s.name}.md) — {s.description} ({s.type})"
            )
        self.index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _scan_dir(self) -> list[MemorySummary]:
        """扫描目录，从 .md 文件中提取摘要（不含 MEMORY.md）。"""
        summaries: list[MemorySummary] = []
        if not self._store_dir.exists():
            return summaries
        for fpath in sorted(self._store_dir.glob("*.md")):
            if fpath.name == _INDEX_FILENAME:
                continue
            try:
                text = fpath.read_text(encoding="utf-8")
            except OSError:
                continue
            fm, _body = _parse_frontmatter(text)
            meta = fm.get("metadata", {})
            summaries.append(MemorySummary(
                name=fm.get("name", fpath.stem),
                description=fm.get("description", ""),
                type=meta.get("type", "reference"),
                updated_at=fm.get("updated_at", ""),
            ))
        return summaries

    @staticmethod
    def _parse_index(text: str) -> list[MemorySummary]:
        """
        从 MEMORY.md 文本解析 MemorySummary 列表。

        格式：- [name](name.md) — description (type)
        """
        summaries: list[MemorySummary] = []
        pattern = re.compile(r"-\s*\[(.+?)\]\((.+?\.md)\)\s*—\s*(.+?)(?:\s*\((\w+)\))?\s*$")
        for line in text.splitlines():
            m = pattern.match(line.strip())
            if m:
                summaries.append(MemorySummary(
                    name=m.group(1),
                    description=m.group(3).strip(),
                    type=m.group(4) or "reference",
                ))
        return summaries
