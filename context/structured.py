"""
context/structured.py

结构化上下文分层系统。

借鉴 Claude Code 的四层上下文架构：
- Layer 0 (System Identity): 极稳定，可缓存
- Layer 1 (Project Context): session 级稳定
- Layer 2 (Task Context): 轮次级变化
- Layer 3 (Ephemeral): 单步级，最短生命周期

设计原则：
- Layer 0 + Layer 1 = Prompt Cache 稳定前缀（最大化 cache hit rate）
- Layer 2 + Layer 3 = 动态后缀（每轮重建）
- 工具定义排序确定化（按 name 字典序）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class ContextPriority(IntEnum):
    """上下文层优先级。数值越小优先级越高（越不容易被裁剪）。"""
    SYSTEM = 0       # 角色定义、安全约束、工具规则
    PROJECT = 1      # RepoMap、Skills、Memory
    TASK = 2         # 当前任务、对话历史
    EPHEMERAL = 3    # 工具结果、诊断、临时 skill body


@dataclass
class ContextLayer:
    """上下文的一个分层片段。"""
    name: str
    priority: ContextPriority
    content: str
    cacheable: bool = False
    max_tokens: int = 0         # 0 = 无限制，由外部 budget 控制

    @property
    def is_empty(self) -> bool:
        return not self.content.strip()

    def __repr__(self) -> str:
        length = len(self.content)
        return f"ContextLayer({self.name!r}, priority={self.priority.name}, len={length}, cacheable={self.cacheable})"


@dataclass
class StructuredContext:
    """
    组装和管理结构化上下文。

    职责：
    1. 维护分层的 context layers
    2. 按优先级排序确保稳定前缀在前
    3. 标记 cache boundary（稳定/动态分界）
    4. 在 token 预算内裁剪低优先级内容
    """
    layers: list[ContextLayer] = field(default_factory=list)

    def add_layer(self, layer: ContextLayer) -> None:
        self.layers.append(layer)

    def get_stable_prefix(self) -> str:
        """返回可缓存的稳定前缀（Layer 0 + Layer 1）。"""
        parts = []
        for layer in self._sorted_layers():
            if layer.cacheable and not layer.is_empty:
                parts.append(layer.content)
        return "\n\n".join(parts)

    def get_dynamic_suffix(self) -> str:
        """返回动态后缀（Layer 2 + Layer 3）。"""
        parts = []
        for layer in self._sorted_layers():
            if not layer.cacheable and not layer.is_empty:
                parts.append(layer.content)
        return "\n\n".join(parts)

    def build_system_content(self, enable_caching: bool = False) -> "str | list[dict[str, Any]]":
        """
        组装最终的 system prompt content。

        如果 enable_caching=True（Anthropic 模式），返回结构化 content blocks：
        [
            {"type": "text", "text": <stable_prefix>, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": <dynamic_suffix>}
        ]

        否则返回纯文本拼接。
        """
        stable = self.get_stable_prefix()
        dynamic = self.get_dynamic_suffix()

        if not enable_caching:
            parts = [p for p in (stable, dynamic) if p]
            return "\n\n".join(parts)

        blocks = []
        if stable:
            blocks.append({
                "type": "text",
                "text": stable,
                "cache_control": {"type": "ephemeral"},
            })
        if dynamic:
            blocks.append({"type": "text", "text": dynamic})
        return blocks if blocks else ""

    def total_content_length(self) -> int:
        return sum(len(layer.content) for layer in self.layers if not layer.is_empty)

    def trim_to_budget(self, budget_tokens: int, estimate_fn=None) -> None:
        """
        裁剪低优先级层以适应 token 预算。
        从 EPHEMERAL 层开始裁剪，然后 TASK，保留 SYSTEM 和 PROJECT。
        """
        if estimate_fn is None:
            estimate_fn = lambda text: len(text) // 4

        total = sum(estimate_fn(l.content) for l in self.layers if not l.is_empty)
        if total <= budget_tokens:
            return

        for priority in reversed(ContextPriority):
            if priority <= ContextPriority.PROJECT:
                break
            for layer in self.layers:
                if layer.priority == priority and not layer.is_empty:
                    layer.content = ""
                    total = sum(estimate_fn(l.content) for l in self.layers if not l.is_empty)
                    if total <= budget_tokens:
                        return

    def layer_summary(self) -> list[dict[str, Any]]:
        """返回各层摘要信息（用于调试/统计）。"""
        return [
            {
                "name": layer.name,
                "priority": layer.priority.name,
                "cacheable": layer.cacheable,
                "chars": len(layer.content),
                "empty": layer.is_empty,
            }
            for layer in self._sorted_layers()
        ]

    def _sorted_layers(self) -> list[ContextLayer]:
        """按优先级排序（稳定的在前）。"""
        return sorted(self.layers, key=lambda l: (l.priority, l.name))


# ---------------------------------------------------------------------------
# 工厂函数：构建标准的 4 层上下文
# ---------------------------------------------------------------------------

def build_structured_context(
    system_core: str,
    tool_descriptions: str = "",
    project_context: str = "",
    memory_section: str = "",
    skills_prompt: str = "",
    task_context: str = "",
) -> StructuredContext:
    """
    构建标准的结构化上下文。

    Args:
        system_core: 角色定义 + 工作流规则 + 安全约束
        tool_descriptions: 工具列表描述
        project_context: RepoMap + 项目规则
        memory_section: 记忆上下文
        skills_prompt: Skills 列表
        task_context: 当前轮次的任务相关上下文

    Returns:
        StructuredContext，已按层分好
    """
    ctx = StructuredContext()

    # Layer 0: System Identity (cacheable)
    core_parts = [system_core]
    if tool_descriptions:
        core_parts.append(f"## Available Tools\n\n{tool_descriptions}")
    ctx.add_layer(ContextLayer(
        name="system_core",
        priority=ContextPriority.SYSTEM,
        content="\n\n".join(core_parts),
        cacheable=True,
    ))

    # Layer 1: Project Context (cacheable within session)
    if project_context or memory_section or skills_prompt:
        project_parts = []
        if memory_section:
            project_parts.append(memory_section)
        if project_context:
            project_parts.append(project_context)
        if skills_prompt:
            project_parts.append(skills_prompt)
        ctx.add_layer(ContextLayer(
            name="project_context",
            priority=ContextPriority.PROJECT,
            content="\n\n".join(project_parts),
            cacheable=True,
        ))

    # Layer 2: Task Context (dynamic, per-round)
    if task_context:
        ctx.add_layer(ContextLayer(
            name="task_context",
            priority=ContextPriority.TASK,
            content=task_context,
            cacheable=False,
        ))

    return ctx
