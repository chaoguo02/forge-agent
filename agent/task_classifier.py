from __future__ import annotations

import re

from agent.policy import extract_explicit_read_paths
from agent.task import Task, TaskShape

_BROAD_ANALYSIS_RE = re.compile(
    r"(architecture|audit|roadmap|optimization|optimi[sz]e|review architecture|"
    r"main problems|trade-?offs|subsystem|design|梳理|架构|审计|路线图|优化|主要问题|治理)",
    re.IGNORECASE,
)
_VERIFICATION_RE = re.compile(
    r"(verify|check whether|confirm whether|prove|validate|核实|验证|检查是否|确认是否)",
    re.IGNORECASE,
)
_LOOKUP_RE = re.compile(
    r"(what is|where is|find|locate|show|which file|哪个文件|哪里|查找|定位|说明一下)",
    re.IGNORECASE,
)
_IMPLEMENTATION_RE = re.compile(
    r"(fix|modify|change|edit|write|add|remove|delete|refactor|implement|create|"
    r"修复|修改|新增|添加|删除|实现|重构|编写)",
    re.IGNORECASE,
)


def classify_task_shape(task: Task) -> TaskShape:
    explicit_paths = frozenset(set(task.explicit_read_paths or ()) | set(task.explicit_write_paths or ()))
    text = task.description.strip()
    inferred_paths = extract_explicit_read_paths(text, task.repo_path)
    scoped_paths = explicit_paths or inferred_paths

    if task.intent == "edit" or _IMPLEMENTATION_RE.search(text):
        return TaskShape(
            kind="implementation",
            explicit_paths=explicit_paths,
            requires_plan=bool(len(text) > 200 or len(text.splitlines()) >= 4),
            confidence=0.9,
            reason="edit intent or implementation wording",
        )

    if scoped_paths:
        return TaskShape(
            kind="scoped_analysis",
            explicit_paths=scoped_paths,
            requires_read_plan=False,
            confidence=0.95,
            reason="specific file scope provided or inferred from the user request",
        )

    if _VERIFICATION_RE.search(text):
        return TaskShape(
            kind="verification",
            explicit_paths=scoped_paths,
            requires_read_plan=False,
            confidence=0.8,
            reason="verification wording detected",
        )

    if _BROAD_ANALYSIS_RE.search(text):
        return TaskShape(
            kind="broad_analysis",
            explicit_paths=scoped_paths,
            requires_plan=True,
            requires_read_plan=True,
            confidence=0.9,
            reason="broad architecture or audit wording detected",
        )

    if _LOOKUP_RE.search(text):
        return TaskShape(
            kind="targeted_lookup",
            explicit_paths=scoped_paths,
            requires_read_plan=False,
            confidence=0.7,
            reason="lookup wording detected",
        )

    return TaskShape(
        kind="simple_answer",
        explicit_paths=scoped_paths,
        requires_read_plan=False,
        confidence=0.5,
        reason="default analysis fallback",
    )
