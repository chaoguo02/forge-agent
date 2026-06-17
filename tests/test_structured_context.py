"""
tests/test_structured_context.py

结构化上下文 + Prompt Caching 单元测试。
"""

import pytest
from llm.base import CacheStats, LLMResponse, LLMToolSchema
from agent.task import Action, ActionType
from context.structured import (
    ContextLayer,
    ContextPriority,
    StructuredContext,
    build_structured_context,
)


# ---------------------------------------------------------------------------
# CacheStats Tests
# ---------------------------------------------------------------------------

class TestCacheStats:
    def test_default_empty(self):
        stats = CacheStats()
        assert stats.cache_read_tokens == 0
        assert stats.cache_creation_tokens == 0
        assert stats.cache_hit_rate == 0.0
        assert not stats.has_cache_activity

    def test_hit_rate_calculation(self):
        stats = CacheStats(cache_read_tokens=8000, cache_creation_tokens=2000)
        assert stats.cache_hit_rate == 0.8
        assert stats.has_cache_activity

    def test_all_cache_read(self):
        stats = CacheStats(cache_read_tokens=10000, cache_creation_tokens=0)
        assert stats.cache_hit_rate == 1.0

    def test_all_cache_creation(self):
        stats = CacheStats(cache_read_tokens=0, cache_creation_tokens=5000)
        assert stats.cache_hit_rate == 0.0
        assert stats.has_cache_activity

    def test_no_activity(self):
        stats = CacheStats()
        assert not stats.has_cache_activity
        assert stats.cache_hit_rate == 0.0


class TestLLMResponseWithCache:
    def test_default_cache_stats(self):
        action = Action(ActionType.FINISH, "done", message="ok")
        resp = LLMResponse(action=action, raw_content="test")
        assert resp.cache_stats is not None
        assert not resp.cache_stats.has_cache_activity

    def test_with_cache_stats(self):
        action = Action(ActionType.FINISH, "done", message="ok")
        stats = CacheStats(cache_read_tokens=5000, cache_creation_tokens=1000)
        resp = LLMResponse(
            action=action, raw_content="test",
            input_tokens=10000, output_tokens=500,
            cache_stats=stats,
        )
        assert resp.cache_stats.cache_hit_rate == pytest.approx(5/6)
        assert resp.total_tokens == 10500


# ---------------------------------------------------------------------------
# ContextLayer Tests
# ---------------------------------------------------------------------------

class TestContextLayer:
    def test_basic_creation(self):
        layer = ContextLayer(
            name="system",
            priority=ContextPriority.SYSTEM,
            content="You are a coding agent.",
            cacheable=True,
        )
        assert layer.name == "system"
        assert not layer.is_empty
        assert layer.cacheable

    def test_empty_detection(self):
        layer = ContextLayer(name="empty", priority=ContextPriority.EPHEMERAL, content="")
        assert layer.is_empty

        layer2 = ContextLayer(name="whitespace", priority=ContextPriority.EPHEMERAL, content="  \n  ")
        assert layer2.is_empty

    def test_repr(self):
        layer = ContextLayer(name="test", priority=ContextPriority.TASK, content="hello")
        r = repr(layer)
        assert "test" in r
        assert "TASK" in r


# ---------------------------------------------------------------------------
# StructuredContext Tests
# ---------------------------------------------------------------------------

class TestStructuredContext:
    def test_add_and_retrieve_layers(self):
        ctx = StructuredContext()
        ctx.add_layer(ContextLayer("sys", ContextPriority.SYSTEM, "System rules", cacheable=True))
        ctx.add_layer(ContextLayer("task", ContextPriority.TASK, "Current task", cacheable=False))
        assert len(ctx.layers) == 2

    def test_stable_prefix(self):
        ctx = StructuredContext()
        ctx.add_layer(ContextLayer("sys", ContextPriority.SYSTEM, "System rules", cacheable=True))
        ctx.add_layer(ContextLayer("proj", ContextPriority.PROJECT, "Project info", cacheable=True))
        ctx.add_layer(ContextLayer("task", ContextPriority.TASK, "Task data", cacheable=False))

        prefix = ctx.get_stable_prefix()
        assert "System rules" in prefix
        assert "Project info" in prefix
        assert "Task data" not in prefix

    def test_dynamic_suffix(self):
        ctx = StructuredContext()
        ctx.add_layer(ContextLayer("sys", ContextPriority.SYSTEM, "System rules", cacheable=True))
        ctx.add_layer(ContextLayer("task", ContextPriority.TASK, "Task data", cacheable=False))
        ctx.add_layer(ContextLayer("tool_result", ContextPriority.EPHEMERAL, "Output: ok", cacheable=False))

        suffix = ctx.get_dynamic_suffix()
        assert "Task data" in suffix
        assert "Output: ok" in suffix
        assert "System rules" not in suffix

    def test_build_system_content_plain(self):
        ctx = StructuredContext()
        ctx.add_layer(ContextLayer("sys", ContextPriority.SYSTEM, "Rules", cacheable=True))
        ctx.add_layer(ContextLayer("task", ContextPriority.TASK, "Do this", cacheable=False))

        result = ctx.build_system_content(enable_caching=False)
        assert isinstance(result, str)
        assert "Rules" in result
        assert "Do this" in result

    def test_build_system_content_with_caching(self):
        ctx = StructuredContext()
        ctx.add_layer(ContextLayer("sys", ContextPriority.SYSTEM, "Rules", cacheable=True))
        ctx.add_layer(ContextLayer("task", ContextPriority.TASK, "Do this", cacheable=False))

        result = ctx.build_system_content(enable_caching=True)
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["cache_control"] == {"type": "ephemeral"}
        assert "Rules" in result[0]["text"]
        assert "Do this" in result[1]["text"]
        assert "cache_control" not in result[1]

    def test_build_system_content_only_stable(self):
        ctx = StructuredContext()
        ctx.add_layer(ContextLayer("sys", ContextPriority.SYSTEM, "Rules", cacheable=True))

        result = ctx.build_system_content(enable_caching=True)
        assert isinstance(result, list)
        assert len(result) == 1
        assert "cache_control" in result[0]

    def test_build_system_content_only_dynamic(self):
        ctx = StructuredContext()
        ctx.add_layer(ContextLayer("task", ContextPriority.TASK, "Task", cacheable=False))

        result = ctx.build_system_content(enable_caching=True)
        assert isinstance(result, list)
        assert len(result) == 1
        assert "cache_control" not in result[0]

    def test_empty_layers_excluded(self):
        ctx = StructuredContext()
        ctx.add_layer(ContextLayer("sys", ContextPriority.SYSTEM, "Rules", cacheable=True))
        ctx.add_layer(ContextLayer("empty", ContextPriority.PROJECT, "", cacheable=True))

        prefix = ctx.get_stable_prefix()
        assert prefix == "Rules"

    def test_trim_to_budget(self):
        ctx = StructuredContext()
        ctx.add_layer(ContextLayer("sys", ContextPriority.SYSTEM, "A" * 100, cacheable=True))
        ctx.add_layer(ContextLayer("proj", ContextPriority.PROJECT, "B" * 100, cacheable=True))
        ctx.add_layer(ContextLayer("task", ContextPriority.TASK, "C" * 100, cacheable=False))
        ctx.add_layer(ContextLayer("ephemeral", ContextPriority.EPHEMERAL, "D" * 100, cacheable=False))

        # Budget allows ~75 tokens (300 chars / 4)
        ctx.trim_to_budget(75)

        # Ephemeral should be trimmed first, then Task
        assert ctx.layers[0].content == "A" * 100  # SYSTEM preserved
        assert ctx.layers[1].content == "B" * 100  # PROJECT preserved
        assert ctx.layers[3].content == ""          # EPHEMERAL trimmed

    def test_trim_preserves_system_and_project(self):
        ctx = StructuredContext()
        ctx.add_layer(ContextLayer("sys", ContextPriority.SYSTEM, "A" * 400, cacheable=True))
        ctx.add_layer(ContextLayer("proj", ContextPriority.PROJECT, "B" * 400, cacheable=True))
        ctx.add_layer(ContextLayer("task", ContextPriority.TASK, "C" * 400, cacheable=False))

        # Very tight budget — can't fit everything
        ctx.trim_to_budget(50)

        # SYSTEM and PROJECT preserved (priority <= PROJECT), TASK trimmed
        assert ctx.layers[0].content == "A" * 400
        assert ctx.layers[1].content == "B" * 400
        assert ctx.layers[2].content == ""

    def test_layer_summary(self):
        ctx = StructuredContext()
        ctx.add_layer(ContextLayer("sys", ContextPriority.SYSTEM, "Rules", cacheable=True))
        ctx.add_layer(ContextLayer("task", ContextPriority.TASK, "Do", cacheable=False))

        summary = ctx.layer_summary()
        assert len(summary) == 2
        assert summary[0]["name"] == "sys"
        assert summary[0]["priority"] == "SYSTEM"
        assert summary[0]["cacheable"] is True

    def test_total_content_length(self):
        ctx = StructuredContext()
        ctx.add_layer(ContextLayer("a", ContextPriority.SYSTEM, "hello", cacheable=True))
        ctx.add_layer(ContextLayer("b", ContextPriority.TASK, "world", cacheable=False))
        assert ctx.total_content_length() == 10

    def test_sorted_layers_order(self):
        ctx = StructuredContext()
        ctx.add_layer(ContextLayer("task", ContextPriority.TASK, "T"))
        ctx.add_layer(ContextLayer("sys", ContextPriority.SYSTEM, "S"))
        ctx.add_layer(ContextLayer("proj", ContextPriority.PROJECT, "P"))

        sorted_layers = ctx._sorted_layers()
        assert sorted_layers[0].priority == ContextPriority.SYSTEM
        assert sorted_layers[1].priority == ContextPriority.PROJECT
        assert sorted_layers[2].priority == ContextPriority.TASK


# ---------------------------------------------------------------------------
# build_structured_context Factory Tests
# ---------------------------------------------------------------------------

class TestBuildStructuredContext:
    def test_minimal(self):
        ctx = build_structured_context(system_core="You are helpful.")
        assert len(ctx.layers) == 1
        assert ctx.layers[0].cacheable
        assert "You are helpful." in ctx.layers[0].content

    def test_with_tools(self):
        ctx = build_structured_context(
            system_core="Agent rules.",
            tool_descriptions="- file_read: Read a file",
        )
        content = ctx.get_stable_prefix()
        assert "Agent rules." in content
        assert "file_read" in content

    def test_with_project_context(self):
        ctx = build_structured_context(
            system_core="Rules",
            project_context="src/main.py: entry point",
            memory_section="User prefers Python",
            skills_prompt="## Available Skills\n- code-review",
        )
        assert len(ctx.layers) == 2
        prefix = ctx.get_stable_prefix()
        assert "User prefers Python" in prefix
        assert "src/main.py" in prefix
        assert "code-review" in prefix

    def test_with_task_context(self):
        ctx = build_structured_context(
            system_core="Rules",
            task_context="Fix the bug in auth.py",
        )
        assert len(ctx.layers) == 2
        prefix = ctx.get_stable_prefix()
        suffix = ctx.get_dynamic_suffix()
        assert "Rules" in prefix
        assert "Fix the bug" in suffix
        assert "Fix the bug" not in prefix

    def test_full_context(self):
        ctx = build_structured_context(
            system_core="You are a coding agent.",
            tool_descriptions="- shell: Run commands\n- file_read: Read files",
            project_context="RepoMap: 5 files",
            memory_section="Memory: user is expert",
            skills_prompt="Skills: code-review",
            task_context="Implement dark mode",
        )
        # Should have 3 layers: system, project, task
        assert len(ctx.layers) == 3

        # Caching: system + project = stable, task = dynamic
        result = ctx.build_system_content(enable_caching=True)
        assert isinstance(result, list)
        assert len(result) == 2  # stable block + dynamic block
        assert "cache_control" in result[0]


# ---------------------------------------------------------------------------
# Tool Sorting Tests
# ---------------------------------------------------------------------------

class TestToolSorting:
    def test_get_schemas_sorted(self):
        from tools.base import ToolRegistry, BaseTool, ToolResult

        class FakeTool(BaseTool):
            def __init__(self, name, desc):
                self._name = name
                self._desc = desc
            @property
            def name(self): return self._name
            @property
            def description(self): return self._desc
            @property
            def parameters_schema(self): return {"type": "object", "properties": {}}
            def execute(self, params): return ToolResult(output="ok")

        registry = ToolRegistry()
        registry.register(FakeTool("zebra", "Z tool"))
        registry.register(FakeTool("alpha", "A tool"))
        registry.register(FakeTool("middle", "M tool"))

        schemas = registry.get_schemas()
        names = [s.name for s in schemas]
        assert names == ["alpha", "middle", "zebra"]

    def test_format_tool_descriptions_sorted(self):
        from agent.prompt import _format_tool_descriptions

        tools = [
            LLMToolSchema(name="zebra", description="Z", parameters={}),
            LLMToolSchema(name="alpha", description="A", parameters={}),
            LLMToolSchema(name="middle", description="M", parameters={}),
        ]
        result = _format_tool_descriptions(tools)
        lines = result.strip().split("\n")
        assert "alpha" in lines[0]
        assert "middle" in lines[1]
        assert "zebra" in lines[2]


# ---------------------------------------------------------------------------
# Integration: CacheStats in RunResult
# ---------------------------------------------------------------------------

class TestRunResultCacheStats:
    def test_run_result_has_cache_stats(self):
        from agent.task import RunResult, RunStatus

        stats = CacheStats(cache_read_tokens=5000, cache_creation_tokens=1000)
        result = RunResult(
            task_id="test",
            status=RunStatus.SUCCESS,
            summary="done",
            steps_taken=3,
            total_tokens=15000,
            cache_stats=stats,
        )
        assert result.cache_stats.cache_hit_rate == pytest.approx(5/6)

    def test_run_result_default_no_cache(self):
        from agent.task import RunResult, RunStatus

        result = RunResult(
            task_id="test",
            status=RunStatus.SUCCESS,
            summary="done",
            steps_taken=1,
        )
        assert result.cache_stats is None
