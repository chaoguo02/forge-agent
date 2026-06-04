"""
tests/test_factory.py

测试 agent/factory.py 的 create_agent() 工厂函数：
- 模式分发（react / plan / auto）
- auto 启发式判断
- 未知模式拒绝
"""

from __future__ import annotations

import pytest

from agent.core import AgentConfig, ReActAgent, PlanExecuteAgent
from agent.factory import create_agent, _is_complex_task, _resolve_mode
from llm.base import MockBackend
from tools.base import NoopTool, ToolRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def backend() -> MockBackend:
    return MockBackend([])


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry().register(NoopTool("shell"))


# ===========================================================================
# create_agent
# ===========================================================================

class TestCreateAgent:

    def test_react_creates_react_agent(self, backend, registry):
        agent = create_agent("react", backend, registry)
        assert isinstance(agent, ReActAgent)

    def test_plan_creates_plan_execute_agent(self, backend, registry):
        agent = create_agent("plan", backend, registry)
        assert isinstance(agent, PlanExecuteAgent)

    def test_unknown_mode_raises(self, backend, registry):
        with pytest.raises(ValueError, match="Unknown mode"):
            create_agent("invalid", backend, registry)

    def test_both_have_run_method(self, backend, registry):
        """ReActAgent 和 PlanExecuteAgent 都有 run(task, log) 接口。"""
        react = create_agent("react", backend, registry)
        plan = create_agent("plan", backend, registry)
        assert hasattr(react, "run")
        assert hasattr(plan, "run")

    def test_plan_accepts_plan_config(self, backend, registry):
        from agent.plan import PlanExecuteConfig
        cfg = PlanExecuteConfig(plan_max_subtasks=5)
        agent = create_agent("plan", backend, registry, plan_config=cfg)
        assert isinstance(agent, PlanExecuteAgent)

    def test_agent_config_passed_through(self, backend, registry):
        cfg = AgentConfig(max_steps=99, budget_tokens=12345)
        react = create_agent("react", backend, registry, cfg)
        assert isinstance(react, ReActAgent)
        plan = create_agent("plan", backend, registry, cfg)
        assert isinstance(plan, PlanExecuteAgent)


# ===========================================================================
# auto mode 启发式判断
# ===========================================================================

class TestIsComplexTask:

    def test_short_task_is_simple(self):
        assert not _is_complex_task("Fix the typo in README.md")

    def test_long_description_is_complex(self):
        desc = "x " * 200  # > 300 chars
        assert _is_complex_task(desc)

    def test_numbered_steps_is_complex(self):
        desc = (
            "1. First fix the parser bug in src/parser.py\n"
            "2. Then add a unit test for the edge case\n"
            "3. Finally run pytest and verify all pass"
        )
        assert _is_complex_task(desc)

    def test_sequential_keywords_is_complex(self):
        desc = "First refactor the tokenizer, then rewrite the AST visitor"
        assert _is_complex_task(desc)

    def test_multiple_files_is_complex(self):
        desc = (
            "First find all imports in utils.py, then move them to helpers.py, "
            "and finally update the references in main.py"
        )
        assert _is_complex_task(desc)

    def test_refactor_keyword_is_complex(self):
        desc = "Refactor the database layer to use async/await"
        assert _is_complex_task(desc)

    def test_multi_line_task_is_complex(self):
        desc = "\n".join(f"line {i}" for i in range(6))
        assert _is_complex_task(desc)

    def test_single_short_line_is_simple(self):
        assert not _is_complex_task("Rename variable x to y")


class TestResolveMode:

    def test_explicit_react(self):
        assert _resolve_mode("react", None) == "react"

    def test_explicit_plan(self):
        assert _resolve_mode("plan", None) == "plan"

    def test_auto_simple_task_returns_react(self):
        assert _resolve_mode("auto", "Fix typo") == "react"

    def test_auto_complex_task_returns_plan(self):
        desc = "1. Refactor parser 2. Add tests 3. Update docs"
        assert _resolve_mode("auto", desc) == "plan"

    def test_auto_no_description_returns_react(self):
        assert _resolve_mode("auto", None) == "react"


# ===========================================================================
# auto mode 端到端 (create_agent)
# ===========================================================================

class TestAutoMode:

    def test_auto_react_for_simple_task(self, backend, registry):
        agent = create_agent("auto", backend, registry, task_description="Fix typo")
        assert isinstance(agent, ReActAgent)

    def test_auto_plan_for_complex_task(self, backend, registry):
        desc = (
            "1. Find all hardcoded URLs in the codebase\n"
            "2. Replace them with config references\n"
            "3. Update tests to use the new config\n"
            "4. Run pytest and verify everything passes"
        )
        agent = create_agent("auto", backend, registry, task_description=desc)
        assert isinstance(agent, PlanExecuteAgent)
