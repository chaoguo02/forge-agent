"""
tests/test_renderer.py

测试 entry/renderer.py 的 Renderer 类。
"""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from entry.renderer import Renderer, _highlight_diff


# ===========================================================================
# Renderer — 基本功能
# ===========================================================================

class TestRenderer:
    def setup_method(self):
        self.r = Renderer(model="gpt-4o", mode="plan")

    def test_all_methods_no_crash(self, capsys):
        r = self.r
        r.stream_text("Hello")
        r.stream_thought("thinking...")
        r.on_tool_call(1, "shell", {"cmd": "ls"})
        r.on_observation(1, "shell", "success", "file1\nfile2\n", None)
        r.on_observation(2, "shell", "error", "", "command not found")
        r.on_reflection("test_failed")
        r.on_finish(3, "All tests pass")
        r.on_give_up(4, "Cannot solve")
        r.on_round_end(1, 5, 1000, 2.5)
        r.on_error("something broke")
        r.on_stats(3, 15, 5000)
        captured = capsys.readouterr()
        assert len(captured.out) > 0

    def test_stream_text_flushes(self, capsys):
        self.r.stream_text("hello")
        captured = capsys.readouterr()
        assert "hello" in captured.out

    def test_stream_thought_dim(self, capsys):
        # 在 TTY 环境（mock）下 stream_thought 应该带有 ANSI 暗色转义
        with patch("sys.stdout.isatty", return_value=True):
            self.r.stream_thought("thinking")
        captured = capsys.readouterr()
        assert "thinking" in captured.out

    def test_silent_tools_short_output(self, capsys):
        self.r.on_observation(1, "file_read", "success", "huge file content here...", None)
        captured = capsys.readouterr()
        assert "huge file content" not in captured.out

    def test_non_silent_tools_print_output(self, capsys):
        self.r.on_observation(1, "shell", "success", "output line", None)
        captured = capsys.readouterr()
        assert "output line" in captured.out

    def test_stats_shows_model_and_mode(self, capsys):
        self.r.on_stats(2, 10, 2000)
        captured = capsys.readouterr()
        assert "gpt-4o" in captured.out
        assert "plan" in captured.out

    def test_default_values(self):
        r = Renderer()
        assert r.model == "?"
        assert r.mode == "react"

    def test_on_finish_does_not_repeat_message(self, capsys):
        """stream_text 已输出 token，on_finish 不应重复打印 message。"""
        self.r.stream_text("The")
        self.r.stream_text(" fix")
        self.r.on_finish(3, "The complete fix message")
        captured = capsys.readouterr()
        # 应该没有打印完整的 message
        assert "The complete fix message" not in captured.out

    def test_on_give_up_prints_message(self, capsys):
        """give_up 不走流式，message 需要打印。"""
        self.r.on_give_up(4, "Cannot solve this")
        captured = capsys.readouterr()
        assert "Cannot solve this" in captured.out

    def test_round_end_prints_stats(self, capsys):
        self.r.on_round_end(1, 5, 999, 3.2)
        captured = capsys.readouterr()
        assert "Round 1" in captured.out
        assert "999" in captured.out
        assert "3.2" in captured.out

    def test_round_end_accumulates_totals(self):
        self.r.on_round_end(1, 2, 100, 0.5)
        self.r.on_round_end(2, 3, 200, 1.0)
        assert self.r._total_steps == 5
        assert self.r._total_tokens == 300


# ===========================================================================
# diff 高亮
# ===========================================================================

class TestHighlightDiff:
    def test_no_crash(self):
        diff = "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new"
        result = _highlight_diff(diff)
        assert len(result) > 0

    def test_non_diff_text_passes_through(self):
        result = _highlight_diff("not a diff")
        assert "not a diff" in result


# ===========================================================================
# ChatSession 集成
# ===========================================================================

class TestChatSessionWithRenderer:
    def test_chat_session_accepts_renderer(self, tmp_path):
        from agent.task import Action, ActionType
        from config.schema import AppConfig
        from llm.base import MockBackend
        from tools.base import NoopTool, ToolRegistry
        from entry.chat import ChatSession

        cfg = AppConfig()
        cfg.agent.max_steps = 5
        cfg.agent.budget_tokens = 40_000
        cfg.agent.log_dir = str(tmp_path / "logs")

        registry = ToolRegistry().register(NoopTool("shell"))
        backend = MockBackend([
            Action(ActionType.FINISH, "done", message="ok"),
        ])

        import os
        os.makedirs(cfg.agent.log_dir, exist_ok=True)

        session = ChatSession(
            backend=backend, registry=registry, config=cfg,
            repo_path=str(tmp_path), log_dir=cfg.agent.log_dir,
        )
        assert isinstance(session._renderer, Renderer)
        ok = session.run_round("do something")
        assert ok

    def test_chat_session_with_custom_renderer(self, tmp_path):
        from agent.task import Action, ActionType
        from config.schema import AppConfig
        from llm.base import MockBackend
        from tools.base import NoopTool, ToolRegistry
        from entry.chat import ChatSession

        cfg = AppConfig()
        cfg.agent.max_steps = 5
        cfg.agent.budget_tokens = 40_000
        cfg.agent.log_dir = str(tmp_path / "logs")

        registry = ToolRegistry().register(NoopTool("shell"))
        backend = MockBackend([
            Action(ActionType.FINISH, "done", message="ok"),
        ])

        import os
        os.makedirs(cfg.agent.log_dir, exist_ok=True)

        r = Renderer(model="deepseek-chat", mode="react")
        session = ChatSession(
            backend=backend, registry=registry, config=cfg,
            repo_path=str(tmp_path), log_dir=cfg.agent.log_dir,
            renderer=r,
        )
        assert session._renderer is r
        ok = session.run_round("hello")
        assert ok
