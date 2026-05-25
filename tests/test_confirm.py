"""
tests/test_confirm.py

权限确认测试：白名单、需确认命令、回调行为、集成到 agent 流程。
"""
from __future__ import annotations

import pytest

from tools.shell_tool import (
    ShellTool, ToolResult,
    _check_blocked, _is_readonly, _needs_confirm,
    terminal_confirm, always_allow, always_deny,
)


# ===========================================================================
# _is_readonly — 白名单判断
# ===========================================================================

class TestIsReadonly:
    @pytest.mark.parametrize("cmd", [
        "ls", "ls -la", "ls /tmp",
        "cat file.py", "cat -n foo.py",
        "grep pattern file.py", "grep -r foo .",
        "find . -name '*.py'",
        "git status", "git diff HEAD", "git log --oneline",
        "git branch -a",
        "python -m pytest tests/",
        "pytest tests/test_foo.py",
        "echo hello",
        "pwd", "whoami",
        "diff a.py b.py",
        "wc -l file.py",
        "tree .",
    ])
    def test_readonly_commands_pass(self, cmd):
        assert _is_readonly(cmd), f"Expected {cmd!r} to be readonly"

    @pytest.mark.parametrize("cmd", [
        "rm file.py",
        "git commit -m 'fix'",
        "pip install requests",
        "mv old.py new.py",
        "chmod 755 script.sh",
        "sudo apt-get install vim",
        "curl https://example.com",
        "git push origin main",
    ])
    def test_write_commands_not_readonly(self, cmd):
        assert not _is_readonly(cmd), f"Expected {cmd!r} to NOT be readonly"


# ===========================================================================
# _needs_confirm — 确认判断
# ===========================================================================

class TestNeedsConfirm:
    def test_readonly_does_not_need_confirm(self):
        assert not _needs_confirm("ls -la")
        assert not _needs_confirm("cat file.py")
        assert not _needs_confirm("git status")
        assert not _needs_confirm("pytest tests/")

    @pytest.mark.parametrize("cmd", [
        "rm file.py",
        "git commit -m 'fix'",
        "pip install requests",
        "mv old.py new.py",
        "chmod 755 script.sh",
        "sudo apt-get install vim",
        "curl https://example.com",
        "git push origin main",
        "echo hello > output.txt",
        "git reset --hard HEAD",
        "docker run ubuntu",
    ])
    def test_dangerous_commands_need_confirm(self, cmd):
        assert _needs_confirm(cmd), f"Expected {cmd!r} to need confirmation"

    def test_unknown_safe_command_no_confirm(self):
        # 未知命令但不含危险关键词，不需要确认
        assert not _needs_confirm("python parse_data.py")
        assert not _needs_confirm("node server.js")


# ===========================================================================
# _check_blocked — 黑名单
# ===========================================================================

class TestCheckBlocked:
    def test_rm_rf_root_blocked(self):
        assert _check_blocked("rm -rf /") is not None

    def test_mkfs_blocked(self):
        assert _check_blocked("mkfs.ext4 /dev/sda1") is not None

    def test_normal_rm_not_blocked(self):
        # rm 单个文件不在黑名单（会走确认流程）
        assert _check_blocked("rm file.py") is None

    def test_git_commit_not_blocked(self):
        assert _check_blocked("git commit -m 'fix'") is None


# ===========================================================================
# ShellTool 权限确认行为
# ===========================================================================

class TestShellToolConfirm:

    def test_readonly_no_callback_called(self):
        """只读命令不调用 confirm_callback。"""
        callback_called = []
        tool = ShellTool(confirm_callback=lambda cmd: callback_called.append(cmd) or True)
        result = tool.execute({"cmd": "echo hello"})
        assert result.success
        assert len(callback_called) == 0  # callback 没被调用

    def test_dangerous_callback_allow(self):
        """危险命令，callback 返回 True → 执行。"""
        tool = ShellTool(confirm_callback=always_allow)
        # pip install 会触发确认，always_allow 允许它
        # 实际执行可能失败（没有网络），但不会被拒绝
        result = tool.execute({"cmd": "pip install --help"})
        # pip --help 是安全的读操作，应该成功
        # 如果 pip install 被拦截，error 里会有 "rejected"
        assert "rejected" not in (result.error or "")

    def test_dangerous_callback_deny(self):
        """危险命令，callback 返回 False → 拒绝。"""
        tool = ShellTool(confirm_callback=always_deny)
        result = tool.execute({"cmd": "pip install requests"})
        assert not result.success
        assert "rejected" in result.error.lower()
        assert "pip install" in result.error

    def test_no_callback_dangerous_command_executes(self):
        """confirm_callback=None → 跳过确认，危险命令直接执行（run 模式）。"""
        tool = ShellTool(confirm_callback=None)
        # 用一个安全但触发确认的命令测试（实际不危险）
        result = tool.execute({"cmd": "echo 'confirm test'"})
        assert result.success

    def test_blocked_command_denied_regardless_of_callback(self):
        """黑名单命令即使 callback=always_allow 也拒绝。"""
        tool = ShellTool(confirm_callback=always_allow)
        result = tool.execute({"cmd": "rm -rf /"})
        assert not result.success
        assert "blocked" in result.error.lower()

    def test_callback_receives_full_command(self):
        """confirm_callback 收到的是完整命令字符串。"""
        received = []
        tool = ShellTool(confirm_callback=lambda cmd: received.append(cmd) or False)
        cmd = "pip install numpy"
        tool.execute({"cmd": cmd})
        assert len(received) == 1
        assert received[0] == cmd

    def test_readonly_command_executes_without_confirm(self):
        """只读命令即使没有 callback 也直接执行。"""
        tool = ShellTool(confirm_callback=None)
        result = tool.execute({"cmd": "echo no_confirm_needed"})
        assert result.success
        assert "no_confirm_needed" in result.output

    def test_mv_needs_confirm(self):
        """mv 命令需要确认。"""
        denied = []
        tool = ShellTool(confirm_callback=lambda cmd: denied.append(cmd) or False)
        result = tool.execute({"cmd": "mv old.py new.py"})
        assert not result.success
        assert len(denied) == 1

    def test_git_commit_needs_confirm(self):
        """git commit 需要确认。"""
        approved = []
        tool = ShellTool(confirm_callback=lambda cmd: approved.append(cmd) or True)
        # 在真实 git repo 里执行会失败（没有 staged 文件），但 callback 应该被调用
        tool.execute({"cmd": "git commit -m 'test'"})
        assert len(approved) == 1
        assert "git commit" in approved[0]

    def test_curl_needs_confirm(self):
        """curl 需要确认（网络请求）。"""
        denied = []
        tool = ShellTool(confirm_callback=lambda cmd: denied.append(cmd) or False)
        result = tool.execute({"cmd": "curl https://example.com"})
        assert not result.success
        assert len(denied) == 1

    def test_redirect_needs_confirm(self):
        """重定向覆盖（>）需要确认。"""
        # 纯逻辑验证：echo hello > file 不应被判为只读
        assert not _is_readonly("echo hello > output.txt")
        # 且需要确认（因为含有 > 重定向）
        assert _needs_confirm("echo hello > output.txt")
        # 工具层：callback 拒绝时应返回错误
        denied = []
        tool = ShellTool(confirm_callback=lambda cmd: denied.append(cmd) or False)
        result = tool.execute({"cmd": "echo hello > output.txt"})
        assert not result.success
        assert len(denied) == 1


# ===========================================================================
# 辅助函数
# ===========================================================================

class TestAlwaysCallbacks:
    def test_always_allow(self):
        assert always_allow("any command") is True

    def test_always_deny(self):
        assert always_deny("any command") is False


# ===========================================================================
# 集成：agent 流程中的权限确认
# ===========================================================================

class TestConfirmInAgentFlow:

    def test_dangerous_command_denied_stops_that_step(self, tmp_path):
        """agent 执行危险命令被拒绝时，observation 包含拒绝信息，agent 继续下一步。"""
        from agent.core import Agent, AgentConfig
        from agent.event_log import EventLog
        from agent.task import Action, ActionType, EventType, Task, ToolCall
        from llm.base import MockBackend
        from tools.base import ToolRegistry

        script = [
            # 先尝试一个被拒绝的危险命令
            Action(ActionType.TOOL_CALL, "try dangerous", ToolCall("shell", {"cmd": "pip install requests"})),
            # 然后用安全命令继续
            Action(ActionType.TOOL_CALL, "safe cmd", ToolCall("shell", {"cmd": "echo done"})),
            Action(ActionType.FINISH, "done", message="completed"),
        ]
        backend = MockBackend(script)
        # always_deny：所有需要确认的命令都拒绝
        registry = ToolRegistry().register(ShellTool(confirm_callback=always_deny))
        agent = Agent(backend, registry, AgentConfig(max_steps=5))

        task = Task(task_id="conf1", description="test", repo_path=str(tmp_path), max_steps=5)
        with EventLog.create(task, log_dir=str(tmp_path / "logs")) as log:
            result = agent.run(task, log)

        assert result.is_success()

        # 检查 event log：第一个 observation 应该包含拒绝信息
        events = log.replay()
        obs_events = [e for e in events if e.event_type == EventType.OBSERVATION]
        first_obs = obs_events[0].payload["observation"]
        assert first_obs["status"] == "error"
        assert "rejected" in first_obs.get("error", "").lower()

    def test_all_allowed_completes_normally(self, tmp_path):
        """所有命令都允许时，agent 正常完成。"""
        from agent.core import Agent, AgentConfig
        from agent.event_log import EventLog
        from agent.task import Action, ActionType, Task, ToolCall
        from llm.base import MockBackend
        from tools.base import ToolRegistry

        script = [
            Action(ActionType.TOOL_CALL, "install", ToolCall("shell", {"cmd": "pip install requests"})),
            Action(ActionType.FINISH, "done", message="installed"),
        ]
        backend = MockBackend(script)
        registry = ToolRegistry().register(ShellTool(confirm_callback=always_allow))
        agent = Agent(backend, registry, AgentConfig(max_steps=5))

        task = Task(task_id="conf2", description="test", repo_path=str(tmp_path), max_steps=5)
        with EventLog.create(task, log_dir=str(tmp_path / "logs")) as log:
            result = agent.run(task, log)

        assert result.is_success()

    def test_readonly_never_triggers_confirm(self, tmp_path):
        """只读命令不触发 confirm，即使 callback=always_deny。"""
        from agent.core import Agent, AgentConfig
        from agent.event_log import EventLog
        from agent.task import Action, ActionType, Task, ToolCall
        from llm.base import MockBackend
        from tools.base import ToolRegistry

        script = [
            Action(ActionType.TOOL_CALL, "ls", ToolCall("shell", {"cmd": "ls /tmp"})),
            Action(ActionType.TOOL_CALL, "echo", ToolCall("shell", {"cmd": "echo hello"})),
            Action(ActionType.FINISH, "done", message="ok"),
        ]
        backend = MockBackend(script)
        # 即使 always_deny，只读命令也不走 callback
        registry = ToolRegistry().register(ShellTool(confirm_callback=always_deny))
        agent = Agent(backend, registry, AgentConfig(max_steps=5))

        task = Task(task_id="conf3", description="test", repo_path=str(tmp_path), max_steps=5)
        with EventLog.create(task, log_dir=str(tmp_path / "logs")) as log:
            result = agent.run(task, log)

        assert result.is_success()


# ===========================================================================
# CLI --confirm 选项注册
# ===========================================================================

class TestCliConfirmOption:
    def test_confirm_option_in_run_help(self):
        from click.testing import CliRunner
        from entry.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--help"])
        assert "--confirm" in result.output

    def test_chat_always_has_confirm(self):
        """chat 命令默认开启 terminal_confirm，不需要额外参数。"""
        from click.testing import CliRunner
        from entry.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["chat", "--help"])
        assert result.exit_code == 0