from __future__ import annotations

from agent.core import _coerce_finish_tool_call
from agent.policy import build_task_policy, extract_explicit_read_paths
from agent.task import Action, ActionType, Task, ToolCall
from agent.task_classifier import classify_task_shape


def test_extract_explicit_read_paths_from_direct_file_mentions() -> None:
    paths = extract_explicit_read_paths(
        "只梳理 agent/core.py 里 broad analysis controller 的主要阶段切换逻辑，不要改代码。",
        repo_path=".",
    )

    assert paths == frozenset({"agent/core.py"})


def test_single_file_analysis_is_not_upgraded_to_broad_analysis() -> None:
    task = Task(
        description="只梳理 agent/core.py 里 broad analysis controller 的主要阶段切换逻辑，不要改代码。",
        repo_path=".",
        intent="analysis",
    )

    shape = classify_task_shape(task)

    assert shape.kind == "scoped_analysis"
    assert shape.explicit_paths == frozenset({"agent/core.py"})


def test_single_file_analysis_policy_scopes_allowed_reads() -> None:
    task = Task(
        description="只梳理 agent/core.py 里 broad analysis controller 的主要阶段切换逻辑，不要改代码。",
        repo_path=".",
        intent="analysis",
    )

    policy = build_task_policy(task)

    assert policy.execution.allowed_read_paths == frozenset({"agent/core.py"})
    assert policy.execution.strict_file_scope is True


def test_finish_tool_call_is_coerced_into_terminal_finish_action() -> None:
    action = Action(
        action_type=ActionType.TOOL_CALL,
        thought="submit final result",
        tool_calls=[ToolCall(name="finish", params={"summary": "done"})],
    )

    normalized = _coerce_finish_tool_call(action)

    assert normalized.action_type == ActionType.FINISH
    assert normalized.message == "done"
    assert normalized.tool_calls == []
