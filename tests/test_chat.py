"""
tests/test_chat.py

ChatSession 多轮对话测试。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent.task import Action, ActionType, Task, ToolCall
from config.schema import AppConfig
from context.history import ConversationHistory
from entry.chat import ChatSession
from llm.base import LLMMessage, MockBackend
from tools.base import NoopTool, ToolRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cfg(tmp_path) -> AppConfig:
    c = AppConfig()
    c.agent.max_steps = 5
    c.agent.budget_tokens = 40_000
    c.agent.log_dir = str(tmp_path / "logs")
    c.context.history_window = 20
    os.makedirs(c.agent.log_dir, exist_ok=True)
    return c


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry().register(NoopTool("shell"))


def make_session(backend, registry, cfg, tmp_path) -> ChatSession:
    return ChatSession(
        backend=backend,
        registry=registry,
        config=cfg,
        repo_path=str(tmp_path),
        log_dir=cfg.agent.log_dir,
    )


# ---------------------------------------------------------------------------
# 基本功能
# ---------------------------------------------------------------------------

class TestChatSessionBasic:
    def test_single_round_succeeds(self, tmp_path, cfg, registry):
        script = [Action(ActionType.FINISH, "done", message="ok")]
        session = make_session(MockBackend(script), registry, cfg, tmp_path)
        ok = session.run_round("fix the bug")
        assert ok
        assert session.round_count == 1
        assert session.total_steps == 1

    def test_stats_accumulate_across_rounds(self, tmp_path, cfg, registry):
        script = [
            Action(ActionType.FINISH, "done1", message="round1"),
            Action(ActionType.FINISH, "done2", message="round2"),
        ]
        session = make_session(MockBackend(script), registry, cfg, tmp_path)
        session.run_round("task 1")
        session.run_round("task 2")
        assert session.round_count == 2
        assert session.total_steps == 2
        assert session.total_tokens > 0

    def test_tool_call_in_round(self, tmp_path, cfg, registry):
        script = [
            Action(ActionType.TOOL_CALL, "explore", ToolCall("shell", {"cmd": "ls"})),
            Action(ActionType.FINISH, "done", message="explored"),
        ]
        session = make_session(MockBackend(script), registry, cfg, tmp_path)
        ok = session.run_round("look around")
        assert ok
        assert session.total_steps == 2


# ---------------------------------------------------------------------------
# History 跨轮传递
# ---------------------------------------------------------------------------

class TestHistoryPersistence:
    def test_round2_sees_more_messages_than_round1(self, tmp_path, cfg, registry):
        """Round 2 的 LLM 调用应收到比 Round 1 更多的 messages。"""
        received = []

        class RecordingBackend(MockBackend):
            def complete(self, messages, tools):
                received.append(len(messages))
                return super().complete(messages, tools)

        script = [
            Action(ActionType.FINISH, "done1", message="r1"),
            Action(ActionType.FINISH, "done2", message="r2"),
        ]
        session = make_session(RecordingBackend(script), registry, cfg, tmp_path)
        session.run_round("round 1 task")
        session.run_round("round 2 task")

        assert len(received) == 2
        # Round 2 应该看到更多 messages（包含了 round 1 的历史）
        assert received[1] > received[0]

    def test_round2_content_contains_round1_summary(self, tmp_path, cfg, registry):
        """Round 2 收到的 messages 里应包含 Round 1 的完成摘要。"""
        received_contents = []

        class ContentRecordingBackend(MockBackend):
            def complete(self, messages, tools):
                received_contents.append([m.content for m in messages])
                return super().complete(messages, tools)

        script = [
            Action(ActionType.FINISH, "done1", message="Created quicksort.py"),
            Action(ActionType.FINISH, "done2", message="Added tests"),
        ]
        session = make_session(ContentRecordingBackend(script), registry, cfg, tmp_path)
        session.run_round("write quicksort")
        session.run_round("add tests")

        # Round 2 的 messages 应包含 round 1 的内容
        round2_all = " ".join(received_contents[1])
        assert "quicksort" in round2_all.lower() or "round 1" in round2_all.lower()

    def test_history_grows_across_rounds(self, tmp_path, cfg, registry):
        """每轮结束后 shared_history 应该增长。"""
        script = [
            Action(ActionType.FINISH, "r1", message="done r1"),
            Action(ActionType.FINISH, "r2", message="done r2"),
            Action(ActionType.FINISH, "r3", message="done r3"),
        ]
        session = make_session(MockBackend(script), registry, cfg, tmp_path)

        session.run_round("task 1")
        count_after_1 = len(session._shared_history)

        session.run_round("task 2")
        count_after_2 = len(session._shared_history)

        session.run_round("task 3")
        count_after_3 = len(session._shared_history)

        assert count_after_2 > count_after_1
        assert count_after_3 > count_after_2

    def test_clear_history_resets(self, tmp_path, cfg, registry):
        """clear_except_first 后 history 应该只剩 1 条。"""
        script = [Action(ActionType.FINISH, "done", message="ok")]
        session = make_session(MockBackend(script), registry, cfg, tmp_path)
        session.run_round("task 1")

        # 清除前有多条
        assert len(session._shared_history) > 1

        session._shared_history.clear_except_first()
        assert len(session._shared_history) == 1


# ---------------------------------------------------------------------------
# 边界情况
# ---------------------------------------------------------------------------

class TestChatEdgeCases:
    def test_agent_give_up_still_returns_true(self, tmp_path, cfg, registry):
        """give_up 不是 success，但也不应让 chat 崩溃。"""
        script = [Action(ActionType.GIVE_UP, "stuck", message="cannot solve")]
        session = make_session(MockBackend(script), registry, cfg, tmp_path)
        ok = session.run_round("impossible task")
        # give_up 返回 True（session 继续），不退出
        assert ok

    def test_multiple_tool_calls_in_one_round(self, tmp_path, cfg, registry):
        script = [
            Action(ActionType.TOOL_CALL, "step1", ToolCall("shell", {"cmd": "ls"})),
            Action(ActionType.TOOL_CALL, "step2", ToolCall("shell", {"cmd": "pwd"})),
            Action(ActionType.TOOL_CALL, "step3", ToolCall("shell", {"cmd": "echo hi"})),
            Action(ActionType.FINISH, "done", message="all done"),
        ]
        session = make_session(MockBackend(script), registry, cfg, tmp_path)
        ok = session.run_round("do three things")
        assert ok
        assert session.total_steps == 4

    def test_repo_map_cache_persists_across_rounds(self, tmp_path, cfg, registry):
        """同一 repo 的 repo_map 应在多轮间共享缓存，只构建一次。"""
        (tmp_path / "mod.py").write_text("def foo(): pass\n")
        build_count = 0

        from context import repo_map as rm_module
        original_build = rm_module.RepoMap.build

        def counting_build(self, budget=8000):
            nonlocal build_count
            build_count += 1
            return original_build(self, budget)

        from unittest.mock import patch
        script = [
            Action(ActionType.FINISH, "r1", message="done1"),
            Action(ActionType.FINISH, "r2", message="done2"),
        ]
        with patch.object(rm_module.RepoMap, "build", counting_build):
            session = make_session(MockBackend(script), registry, cfg, tmp_path)
            session.run_round("round 1")
            session.run_round("round 2")

        # repo_map 只构建一次（第一轮），第二轮复用缓存
        assert build_count == 1


# ---------------------------------------------------------------------------
# CLI chat 命令注册
# ---------------------------------------------------------------------------

class TestChatCommand:
    def test_chat_command_registered(self):
        from click.testing import CliRunner
        from entry.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["chat", "--help"])
        assert result.exit_code == 0
        assert "--repo" in result.output
        assert "--model" in result.output

    def test_chat_listed_in_root_help(self):
        from click.testing import CliRunner
        from entry.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert "chat" in result.output