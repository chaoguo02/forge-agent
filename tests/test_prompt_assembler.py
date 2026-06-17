"""
tests/test_prompt_assembler.py

PromptAssembler 单元测试。

覆盖：
- 三层文件覆盖（内置 → 用户级 → 项目级）
- 模板变量替换
- 缺失变量安全处理
- 缓存与清除
- 兼容层函数输出正确性
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from prompts.assembler import PromptAssembler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def assembler():
    """无项目目录的 assembler（仅使用内置）。"""
    return PromptAssembler()


@pytest.fixture
def temp_dirs():
    """创建临时的项目级和用户级 prompt 目录。"""
    with tempfile.TemporaryDirectory() as project_root:
        with tempfile.TemporaryDirectory() as user_home:
            project_prompts = Path(project_root) / ".forge-agent" / "prompts"
            user_prompts = Path(user_home) / ".forge-agent" / "prompts"
            project_prompts.mkdir(parents=True)
            user_prompts.mkdir(parents=True)
            yield {
                "project_root": project_root,
                "project_prompts": project_prompts,
                "user_prompts": user_prompts,
                "user_home": user_home,
            }


# ---------------------------------------------------------------------------
# 基本加载测试
# ---------------------------------------------------------------------------

class TestResolve:
    def test_loads_builtin_base_md(self, assembler):
        content = assembler.resolve("base.md")
        assert "autonomous coding agent" in content
        assert "{repo_path}" in content
        assert "{tool_descriptions}" in content

    def test_loads_builtin_reflection(self, assembler):
        content = assembler.resolve("reflection/test-failed.md")
        assert "[REFLECTION]" in content
        assert "root cause" in content

    def test_loads_builtin_modes(self, assembler):
        content = assembler.resolve("modes/plan.md")
        assert "PLAN MODE" in content

    def test_file_not_found_raises(self, assembler):
        with pytest.raises(FileNotFoundError, match="nonexistent.md"):
            assembler.resolve("nonexistent.md")

    def test_project_level_override(self, temp_dirs):
        project_prompts = temp_dirs["project_prompts"]
        (project_prompts / "base.md").write_text("CUSTOM PROJECT PROMPT", encoding="utf-8")

        asm = PromptAssembler(project_dir=temp_dirs["project_root"])
        content = asm.resolve("base.md")
        assert content == "CUSTOM PROJECT PROMPT"

    def test_user_level_override(self, temp_dirs):
        user_prompts = temp_dirs["user_prompts"]
        (user_prompts / "base.md").write_text("CUSTOM USER PROMPT", encoding="utf-8")

        with patch.object(PromptAssembler, "USER_DIR", user_prompts):
            asm = PromptAssembler()
            content = asm.resolve("base.md")
            assert content == "CUSTOM USER PROMPT"

    def test_project_overrides_user(self, temp_dirs):
        project_prompts = temp_dirs["project_prompts"]
        user_prompts = temp_dirs["user_prompts"]

        (user_prompts / "base.md").write_text("USER LEVEL", encoding="utf-8")
        (project_prompts / "base.md").write_text("PROJECT LEVEL", encoding="utf-8")

        with patch.object(PromptAssembler, "USER_DIR", user_prompts):
            asm = PromptAssembler(project_dir=temp_dirs["project_root"])
            content = asm.resolve("base.md")
            assert content == "PROJECT LEVEL"

    def test_falls_through_to_builtin(self, temp_dirs):
        """项目级无文件时应使用内置。"""
        asm = PromptAssembler(project_dir=temp_dirs["project_root"])
        content = asm.resolve("base.md")
        assert "autonomous coding agent" in content

    def test_subdirectory_override(self, temp_dirs):
        project_prompts = temp_dirs["project_prompts"]
        modes_dir = project_prompts / "modes"
        modes_dir.mkdir(parents=True)
        (modes_dir / "plan.md").write_text("MY CUSTOM PLAN MODE", encoding="utf-8")

        asm = PromptAssembler(project_dir=temp_dirs["project_root"])
        content = asm.resolve("modes/plan.md")
        assert content == "MY CUSTOM PLAN MODE"


# ---------------------------------------------------------------------------
# 模板渲染测试
# ---------------------------------------------------------------------------

class TestRender:
    def test_variable_substitution(self, assembler):
        content = assembler.render("reflection/no-edit.md", n=5)
        assert "5 steps" in content
        assert "{n}" not in content

    def test_unknown_variable_preserved(self, assembler):
        """未提供的变量应保留 {name} 原样，不崩溃。"""
        content = assembler.render("base.md")
        assert "{repo_path}" in content

    def test_partial_variables(self, assembler):
        content = assembler.render("base.md", repo_path="/my/repo")
        assert "/my/repo" in content
        assert "{tool_descriptions}" in content

    def test_all_variables(self, assembler):
        content = assembler.render(
            "base.md",
            repo_path="/test",
            repo_summary="A test repo",
            tool_descriptions="- tool1\n- tool2",
        )
        assert "/test" in content
        assert "A test repo" in content
        assert "- tool1" in content
        assert "{" not in content or "{{" in content  # no unresolved vars


# ---------------------------------------------------------------------------
# 高级渲染方法测试
# ---------------------------------------------------------------------------

class TestRenderMethods:
    def test_render_system_core(self, assembler):
        from unittest.mock import MagicMock
        tool1 = MagicMock()
        tool1.name = "file_read"
        tool1.description = "Read a file"
        tool2 = MagicMock()
        tool2.name = "shell"
        tool2.description = "Execute shell command"

        result = assembler.render_system_core("/repo", [tool1, tool2], "My repo summary")
        assert "/repo" in result
        assert "My repo summary" in result
        assert "file_read" in result
        assert "shell" in result
        # tools should be sorted
        assert result.index("file_read") < result.index("shell")

    def test_render_system_core_no_summary(self, assembler):
        result = assembler.render_system_core("/repo", [], None)
        assert "not yet available" in result

    def test_render_mode_prompt_existing(self, assembler):
        result = assembler.render_mode_prompt("plan")
        assert "PLAN MODE" in result

    def test_render_mode_prompt_nonexistent(self, assembler):
        result = assembler.render_mode_prompt("nonexistent-mode-xyz")
        assert result == ""

    def test_render_reflection(self, assembler):
        result = assembler.render_reflection("loop-detected", n=3)
        assert "3 times" in result
        assert "[REFLECTION]" in result

    def test_render_agent_prompt(self, assembler):
        result = assembler.render_agent_prompt(
            "sub-agent",
            role="Reader",
            task_prompt="Find the auth module",
            upstream_section="",
        )
        assert "Reader" in result
        assert "Find the auth module" in result


# ---------------------------------------------------------------------------
# 缓存测试
# ---------------------------------------------------------------------------

class TestCache:
    def test_caches_file_content(self, assembler):
        content1 = assembler.resolve("base.md")
        content2 = assembler.resolve("base.md")
        assert content1 is content2  # same object = cached

    def test_clear_cache(self, temp_dirs):
        project_prompts = temp_dirs["project_prompts"]
        (project_prompts / "base.md").write_text("V1", encoding="utf-8")

        asm = PromptAssembler(project_dir=temp_dirs["project_root"])
        assert asm.resolve("base.md") == "V1"

        (project_prompts / "base.md").write_text("V2", encoding="utf-8")
        assert asm.resolve("base.md") == "V1"  # still cached

        asm.clear_cache()
        assert asm.resolve("base.md") == "V2"  # fresh load


# ---------------------------------------------------------------------------
# 兼容层测试
# ---------------------------------------------------------------------------

class TestCompatibilityLayer:
    """验证 agent/prompt.py 的旧函数通过新 assembler 输出正确内容。"""

    def test_build_system_prompt_core(self):
        from agent.prompt import build_system_prompt_core
        from unittest.mock import MagicMock

        tool = MagicMock()
        tool.name = "test_tool"
        tool.description = "A test tool"

        result = build_system_prompt_core("/repo", [tool], "summary")
        assert "autonomous coding agent" in result
        assert "/repo" in result
        assert "summary" in result
        assert "test_tool" in result

    def test_build_system_prompt_variable_with_memory(self):
        from agent.prompt import build_system_prompt_variable

        result = build_system_prompt_variable(memory_section="my memories", auto_memory_enabled=True)
        assert "my memories" in result
        assert "Auto Memory Guidelines" in result

    def test_build_system_prompt_variable_empty(self):
        from agent.prompt import build_system_prompt_variable

        result = build_system_prompt_variable()
        assert result == ""

    def test_get_plan_mode_injection(self):
        from agent.prompt import get_plan_mode_injection

        result = get_plan_mode_injection()
        assert "PLAN MODE" in result
        assert "read-only" in result

    def test_get_plan_execution_injection(self):
        from agent.prompt import get_plan_execution_injection

        result = get_plan_execution_injection()
        assert "EXECUTION MODE" in result

    def test_get_dag_plan_prompt(self):
        from agent.prompt import get_dag_plan_prompt

        result = get_dag_plan_prompt()
        assert "DAG PLAN MODE" in result
        assert "depends_on" in result

    def test_reflection_test_failed(self):
        from agent.prompt import reflection_test_failed

        result = reflection_test_failed()
        assert "[REFLECTION]" in result
        assert "root cause" in result

    def test_reflection_no_edit(self):
        from agent.prompt import reflection_no_edit

        result = reflection_no_edit(7)
        assert "7 steps" in result

    def test_reflection_loop_detected(self):
        from agent.prompt import reflection_loop_detected

        result = reflection_loop_detected(4)
        assert "4 times" in result

    def test_build_task_prompt(self):
        from agent.prompt import build_task_prompt

        result = build_task_prompt("Fix the bug", "/repo", "https://github.com/issue/1")
        assert "Fix the bug" in result
        assert "/repo" in result
        assert "https://github.com/issue/1" in result

    def test_build_coordinator_system_prompt(self):
        from agent.prompt import build_coordinator_system_prompt

        result = build_coordinator_system_prompt(
            task_description="Do something",
            repo_path="/repo",
            total_budget=100000,
            sub_agent_budget=70000,
            max_retries=2,
        )
        assert "COORDINATOR" in result
        assert "Do something" in result
        assert "/repo" in result
        assert "70000" in result

    def test_build_sub_agent_prompt(self):
        from agent.prompt import build_sub_agent_prompt

        result = build_sub_agent_prompt(
            role="reader",
            task_prompt="Find the auth module",
            upstream_context="Previous findings...",
        )
        assert "Reader" in result
        assert "Find the auth module" in result
        assert "Previous findings..." in result

    def test_build_dag_subtask_prompt(self):
        from agent.prompt import build_dag_subtask_prompt

        result = build_dag_subtask_prompt(
            subtask_id="2",
            description="Edit config.py",
            expected_outcome="Config updated",
            upstream_context="Task 1 done",
        )
        assert "[2]" in result
        assert "Edit config.py" in result
        assert "Config updated" in result
        assert "Task 1 done" in result

    def test_build_system_prompt_structured_plain(self):
        from agent.prompt import build_system_prompt_structured
        from unittest.mock import MagicMock

        tool = MagicMock()
        tool.name = "t"
        tool.description = "d"

        result = build_system_prompt_structured("/r", [tool], enable_caching=False)
        assert isinstance(result, str)
        assert "autonomous coding agent" in result

    def test_build_system_prompt_structured_cached(self):
        from agent.prompt import build_system_prompt_structured
        from unittest.mock import MagicMock

        tool = MagicMock()
        tool.name = "t"
        tool.description = "d"

        result = build_system_prompt_structured(
            "/r", [tool], auto_memory_enabled=True, enable_caching=True
        )
        assert isinstance(result, list)
        assert result[0]["cache_control"] == {"type": "ephemeral"}


# ---------------------------------------------------------------------------
# 工具描述格式化测试
# ---------------------------------------------------------------------------

class TestFormatToolDescriptions:
    def test_empty_tools(self):
        result = PromptAssembler._format_tool_descriptions([])
        assert "no tools available" in result

    def test_sorted_by_name(self):
        from unittest.mock import MagicMock

        tools = []
        for name in ["zebra", "alpha", "middle"]:
            t = MagicMock()
            t.name = name
            t.description = f"{name} desc"
            tools.append(t)

        result = PromptAssembler._format_tool_descriptions(tools)
        assert result.index("alpha") < result.index("middle") < result.index("zebra")
