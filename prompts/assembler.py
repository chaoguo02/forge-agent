"""
prompts/assembler.py

Prompt 分层架构核心：PromptAssembler。

职责：
- 从 prompts/ 目录加载 .md 文件
- 三层覆盖：内置 → ~/.forge-agent/prompts/ → .forge-agent/prompts/
- 模板变量替换 ({repo_path}, {tool_descriptions}, ...)
- 返回渲染后字符串

设计原则：
- 内容与组装逻辑分离：.md 文件存内容，assembler 负责加载和渲染
- 三层覆盖：项目级最高优先级 → 用户级 → 内置兜底
- cache 友好：稳定内容（base.md）不因动态变量改变文件选择
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class _SafeDict(dict):
    """format_map 用的安全字典，未知 key 保留原样 {key}。"""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


class PromptAssembler:
    """
    三层覆盖的 Prompt 文件加载与渲染。

    查找顺序（高优先级 → 低优先级）：
    1. 项目级: {project_dir}/.forge-agent/prompts/
    2. 用户级: ~/.forge-agent/prompts/
    3. 内置:   {package}/prompts/

    Usage:
        assembler = PromptAssembler(project_dir="/path/to/repo")
        core = assembler.render_system_core(repo_path, tools, repo_summary)
        plan_prompt = assembler.render("modes/plan.md")
    """

    BUILTIN_DIR = Path(__file__).parent
    USER_DIR = Path.home() / ".forge-agent" / "prompts"

    def __init__(self, project_dir: str | Path | None = None):
        self._project_dir: Path | None = None
        if project_dir:
            self._project_dir = Path(project_dir) / ".forge-agent" / "prompts"
        self._cache: dict[str, str] = {}

    def resolve(self, relative_path: str) -> str:
        """
        三层查找，返回文件原始内容。

        Args:
            relative_path: 相对于 prompts/ 的路径，如 "base.md", "modes/plan.md"

        Returns:
            文件内容字符串

        Raises:
            FileNotFoundError: 三层都找不到时抛出
        """
        if relative_path in self._cache:
            return self._cache[relative_path]

        content = self._load_from_layers(relative_path)
        self._cache[relative_path] = content
        return content

    def render(self, relative_path: str, **variables: Any) -> str:
        """
        加载并渲染模板。

        变量使用 {name} 格式。未提供的变量保留原样（不崩溃）。

        Args:
            relative_path: 模板文件相对路径
            **variables: 模板变量

        Returns:
            渲染后的字符串
        """
        raw = self.resolve(relative_path)
        if not variables:
            return raw
        return raw.format_map(_SafeDict(variables))

    def render_system_core(
        self,
        repo_path: str,
        tools: list,
        repo_summary: str | None = None,
    ) -> str:
        """
        渲染 system prompt 核心部分（等价于旧 build_system_prompt_core）。

        组装: base.md 模板 + 工具描述 + repo 信息
        """
        tool_descriptions = self._format_tool_descriptions(tools)
        summary = repo_summary or "(Repository summary not yet available — use find_files and file_read to explore)"
        return self.render(
            "base.md",
            repo_path=repo_path,
            repo_summary=summary,
            tool_descriptions=tool_descriptions,
        )

    def render_mode_prompt(self, mode: str, **variables: Any) -> str:
        """
        渲染模式 prompt（modes/{mode}.md）。

        不存在时返回空字符串（非所有模式都有独立 prompt）。
        """
        path = f"modes/{mode}.md"
        try:
            return self.render(path, **variables)
        except FileNotFoundError:
            return ""

    def render_reflection(self, kind: str, **variables: Any) -> str:
        """渲染反思 prompt（reflection/{kind}.md）。"""
        return self.render(f"reflection/{kind}.md", **variables)

    def render_agent_prompt(self, template: str, **variables: Any) -> str:
        """渲染 agent 模板（agents/{template}.md）。"""
        return self.render(f"agents/{template}.md", **variables)

    def clear_cache(self) -> None:
        """清除文件缓存，下次 resolve 时重新从磁盘读取。"""
        self._cache.clear()

    def _load_from_layers(self, relative_path: str) -> str:
        """按优先级从三层目录中查找文件。"""
        # Layer 1: 项目级（最高优先级）
        if self._project_dir:
            p = self._project_dir / relative_path
            if p.is_file():
                logger.debug("Prompt override (project): %s", p)
                return p.read_text(encoding="utf-8")

        # Layer 2: 用户级
        p = self.USER_DIR / relative_path
        if p.is_file():
            logger.debug("Prompt override (user): %s", p)
            return p.read_text(encoding="utf-8")

        # Layer 3: 内置（兜底）
        p = self.BUILTIN_DIR / relative_path
        if p.is_file():
            return p.read_text(encoding="utf-8")

        raise FileNotFoundError(
            f"Prompt file not found in any layer: {relative_path}\n"
            f"  Searched: project={self._project_dir}, user={self.USER_DIR}, builtin={self.BUILTIN_DIR}"
        )

    @staticmethod
    def _format_tool_descriptions(tools: list) -> str:
        """把工具列表格式化为易读的描述块（按 name 排序，确保 cache 稳定）。"""
        if not tools:
            return "(no tools available)"
        sorted_tools = sorted(tools, key=lambda t: t.name)
        lines = []
        for tool in sorted_tools:
            lines.append(f"- **{tool.name}**: {tool.description}")
        return "\n".join(lines)
