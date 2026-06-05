"""
tests/test_renderer.py

测试 entry/renderer.py 的 Renderer 接口和实现。
"""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from entry.renderer import (
    Renderer, PlainRenderer, InlineRenderer, get_renderer,
)


# ===========================================================================
# Factory
# ===========================================================================

class TestGetRenderer:
    def test_plain_returns_plainrenderer(self):
        r = get_renderer("plain")
        assert isinstance(r, PlainRenderer)

    @patch("sys.stdout.isatty", return_value=True)
    def test_inline_tty_returns_inlinerenderer(self, _mock):
        r = get_renderer("inline")
        assert isinstance(r, InlineRenderer)

    @patch("sys.stdout.isatty", return_value=False)
    def test_inline_no_tty_falls_back_to_plain(self, _mock):
        r = get_renderer("inline")
        assert isinstance(r, PlainRenderer)

    def test_unknown_renderer_raises(self):
        with pytest.raises(ValueError, match="Unknown renderer"):
            get_renderer("garbage")

    def test_inline_accepts_kwargs(self):
        with patch("sys.stdout.isatty", return_value=True):
            r = get_renderer("inline", model="gpt-4o", mode="plan")
            assert isinstance(r, InlineRenderer)
            assert r._model == "gpt-4o"
            assert r._mode == "plan"


# ===========================================================================
# PlainRenderer — methods don't crash
# ===========================================================================

class TestPlainRenderer:
    def setup_method(self):
        self.r = PlainRenderer()

    def test_all_methods_no_crash(self, capsys):
        """所有方法至少不抛异常。"""
        r = self.r
        r.on_round_start("fix the bug")
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
        # 至少有些输出
        assert len(captured.out) > 0

    def test_silent_tools_short_output(self, capsys):
        """只读工具不打印输出内容。"""
        r = self.r
        r.on_observation(1, "file_read", "success", "huge file content here...", None)
        captured = capsys.readouterr()
        assert "huge file content" not in captured.out

    def test_non_silent_tools_print_output(self, capsys):
        """非只读工具打印输出。"""
        r = self.r
        r.on_observation(1, "shell", "success", "output line", None)
        captured = capsys.readouterr()
        assert "output line" in captured.out


# ===========================================================================
# InlineRenderer — methods don't crash
# ===========================================================================

class TestInlineRenderer:
    def setup_method(self):
        with patch("sys.stdout.isatty", return_value=True):
            self.r = InlineRenderer(model="test-model", mode="react")

    def test_all_methods_no_crash(self, capsys):
        r = self.r
        r.on_round_start("fix the bug")
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

    def test_stats_contains_model(self, capsys):
        r = self.r
        r.on_stats(2, 10, 2000)
        captured = capsys.readouterr()
        assert "test-model" in captured.out
        assert "react" in captured.out

    def test_rich_fallback_when_not_installed(self, monkeypatch):
        """InlineRenderer 在 rich 未安装时创建失败 → 工厂应降级为 PlainRenderer。"""
        import entry.renderer as mod
        monkeypatch.setattr(mod.InlineRenderer, "_rich_ok", False, raising=False)

        r = InlineRenderer()
        # 不应该崩溃（rich_ok=False 时跳过 rich 特性）
        r.on_round_start("test")
        r.stream_text("ok")
        r.on_round_end(1, 1, 100, 0.5)

    def test_diff_highlight_doesnt_crash(self):
        diff = "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new"
        result = self.r._highlight_diff(diff)
        assert len(result) > 0

    def test_output_lines_collected(self):
        r = self.r
        r.on_round_start("test task")
        r.on_tool_call(1, "file_read", {"path": "main.py"})
        r.on_observation(1, "file_read", "success", "", None)
        r.on_round_end(1, 2, 300, 0.5)
        assert len(r._output_lines) >= 4  # on_round_start + tool + obs + round_end


# ===========================================================================
# ChatSession + Renderer 集成（最小冒烟测试，重用现有 test_chat 环境）
# ===========================================================================

class TestChatSessionWithRenderer:
    def test_chat_session_accepts_renderer(self, tmp_path):
        """ChatSession 构造时不传 renderer 应自动创建 PlainRenderer。"""
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

        # 不传 renderer → 默认 PlainRenderer
        session = ChatSession(
            backend=backend, registry=registry, config=cfg,
            repo_path=str(tmp_path), log_dir=cfg.agent.log_dir,
        )
        assert isinstance(session._renderer, PlainRenderer)
        ok = session.run_round("do something")
        assert ok

    def test_chat_session_with_inline_renderer(self, tmp_path):
        """ChatSession 接受 InlineRenderer。"""
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

        with patch("sys.stdout.isatty", return_value=True):
            renderer = InlineRenderer(model="gpt-4o", mode="react")
        session = ChatSession(
            backend=backend, registry=registry, config=cfg,
            repo_path=str(tmp_path), log_dir=cfg.agent.log_dir,
            renderer=renderer,
        )
        assert session._renderer is renderer
        ok = session.run_round("hello")
        assert ok


# ===========================================================================
# CLI --renderer option
# ===========================================================================

class TestCliRendererOption:
    def test_chat_help_shows_renderer(self):
        from click.testing import CliRunner
        from entry.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["chat", "--help"])
        assert result.exit_code == 0
        assert "--renderer" in result.output
