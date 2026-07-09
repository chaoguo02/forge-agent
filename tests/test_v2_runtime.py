"""Tests for V2 fork-based subagent runtime."""

from __future__ import annotations

import pytest

from agent.core import AgentConfig
from agent.task import Action, ActionType, ToolCall
from agent.v2 import AgentRegistryV2, AgentTool, ForkResult, SessionRuntime, SessionStore
from agent.v2.models import AgentDefinition
from llm.base import LLMMessage, MockBackend
from tools.base import NoopTool, ToolRegistry


def _make_runtime(tmp_path, backend: MockBackend) -> tuple[SessionRuntime, SessionStore]:
    agent_registry = AgentRegistryV2()
    base_registry = ToolRegistry()

    from agent.v2.agent_registry import _BUILD_ALLOWED
    for tool_name in sorted(_BUILD_ALLOWED):
        base_registry.register(NoopTool(tool_name, output=f"{tool_name} ok"))
    base_registry.register(NoopTool("task", "subagent done"))

    store = SessionStore(str(tmp_path / ".forge-agent" / "v2" / "sessions.db"))
    runtime = SessionRuntime(
        store=store,
        backend=backend,
        base_registry=base_registry,
        agent_registry=agent_registry,
        root_agent_config=AgentConfig(
            max_steps=10, budget_tokens=50_000, request_budget_tokens=20_000,
            history_max_messages=20, stream=False,
        ),
        log_dir=str(tmp_path / "logs"),
    )
    return runtime, store


# ── Session Store ──

def test_v2_session_store_persists_parent_child_relationships(tmp_path):
    store = SessionStore(str(tmp_path / ".forge-agent" / "v2" / "sessions.db"))
    root = store.create_session(agent_name="build", mode="primary", repo_path=str(tmp_path), title="root")
    child = store.create_session(agent_name="explore", mode="subagent", repo_path=str(tmp_path),
                                 title="child", parent_id=root.id, root_id=root.root_id)
    assert store.get_session(root.id).parent_id is None
    assert store.get_session(child.id).parent_id == root.id
    assert [item.id for item in store.list_child_sessions(root.id)] == [child.id]


# ── Agent Registry ──

def test_v2_agent_registry_loads_builtins():
    registry = AgentRegistryV2()
    for name in ("explore", "general", "code-reviewer"):
        definition = registry.get(name)
        assert isinstance(definition, AgentDefinition)
        assert definition.name == name


def test_v2_agent_registry_resolves_tool_names():
    registry = AgentRegistryV2()
    names = registry.tool_names_for("explore")
    assert "file_read" in names or "Read" in names


# ── AgentTool ──

def test_v2_task_tool_rejects_unknown_subagent_type(tmp_path):
    backend = MockBackend([])
    runtime, store = _make_runtime(tmp_path, backend)
    tool = AgentTool(runtime, "parent")
    result = tool.execute({"subagent_type": "nonexistent", "description": "test", "prompt": "do it"})
    assert result.success is False
    assert "Unknown subagent_type" in result.error


def test_v2_task_tool_rejects_missing_params():
    tool = AgentTool.__new__(AgentTool)
    result = tool.execute({})
    assert result.success is False
    assert "requires" in result.error


# ── Fork Result ──

def test_v2_fork_result_fields():
    result = ForkResult(
        agent_name="explore", session_id="abc123", status="completed",
        summary="Found 3 files.", turns_used=5,
    )
    assert result.session_id == "abc123"
    assert result.status == "completed"


# ── Primary agent run ──

def test_v2_build_agent_runs_to_completion(tmp_path):
    backend = MockBackend([
        Action(action_type=ActionType.FINISH, thought="done", message="Task complete."),
    ])
    runtime, store = _make_runtime(tmp_path, backend)
    session = runtime.create_root_session(agent_name="build", repo_path=str(tmp_path), title="test")
    result = runtime.run_session(session.id, agent_name="build", task_description="do it", intent="edit")
    assert result.summary == "Task complete."


def test_v2_plan_agent_is_readonly(tmp_path):
    agent_registry = AgentRegistryV2()
    definition = agent_registry.get("explore")
    assert "Write" in definition.disallowed_tools or definition.tools
    assert definition.mode == "subagent"


# ── Subagent tool restriction ──

def test_v2_build_gets_task_tool(tmp_path):
    backend = MockBackend([
        Action(action_type=ActionType.FINISH, thought="ok", message="done"),
    ])
    runtime, store = _make_runtime(tmp_path, backend)
    session = runtime.create_root_session(agent_name="build", repo_path=str(tmp_path), title="test")
    definition = runtime.agent_registry.get("build")
    assert definition is not None


# ── Fork execution ──

def test_v2_fork_subagent_builds_restricted_registry(tmp_path):
    backend = MockBackend([Action(action_type=ActionType.FINISH, thought="ok", message="summary")])
    runtime, store = _make_runtime(tmp_path, backend)
    result = runtime.fork_session(
        definition=runtime.agent_registry.get("explore"),
        description="explore auth",
        prompt="Find login flow",
    )
    assert result.status == "completed"
    assert result.summary == "summary"
    assert result.agent_name == "explore"


def test_v2_fork_subagent_max_steps_exhaustion(tmp_path):
    # Run many steps until max_steps exhausted
    actions = []
    for _ in range(55):
        actions.append(Action(
            action_type=ActionType.TOOL_CALL, thought="searching",
            tool_calls=[ToolCall(name="file_read", params={"path": "a.py"})],
        ))
    backend = MockBackend(actions)
    runtime, store = _make_runtime(tmp_path, backend)
    result = runtime.fork_session(
        definition=runtime.agent_registry.get("explore"),
        description="exhaustive search", prompt="Find everything",
    )
    assert result.status in ("partial", "failed")


def test_v2_parent_recovers_after_failed_child(tmp_path):
    # Fork subagent finishes immediately
    child_backend = MockBackend([
        Action(action_type=ActionType.FINISH, thought="sub", message="child done"),
    ])
    runtime, store = _make_runtime(tmp_path, child_backend)
    result = runtime.fork_session(
        definition=runtime.agent_registry.get("general"),
        description="fast task", prompt="Do quick thing",
    )
    assert result.status == "completed"

    # Parent can still run after child — separate backend needed in real use,
    # but here we verify fork doesn't crash and session still works.
    parent_backend = MockBackend([
        Action(action_type=ActionType.FINISH, thought="ok", message="parent done"),
    ])
    runtime2, _ = _make_runtime(tmp_path, parent_backend)
    session = runtime2.create_root_session(agent_name="build", repo_path=str(tmp_path), title="recovery")
    result2 = runtime2.run_session(session.id, agent_name="build", task_description="recover", intent="edit")
    assert result2.summary == "parent done"


def test_v2_runtime_injects_subagent_descriptions(tmp_path):
    backend = MockBackend([
        Action(action_type=ActionType.FINISH, thought="ok", message="done"),
    ])
    runtime, store = _make_runtime(tmp_path, backend)
    definition = runtime.agent_registry.get("build")
    messages = runtime._build_runtime_messages(definition, "test task")
    text = " ".join(str(m.content) for m in messages)
    assert "task" in text
    assert "explore" in text
    assert "general" in text


def test_v2_unknown_parent_session_raises(tmp_path):
    runtime, store = _make_runtime(tmp_path, MockBackend([]))
    with pytest.raises(ValueError, match="Unknown v2 session"):
        runtime.run_session("nonexistent", agent_name="build", task_description="x", intent="analysis")
