"""
tests/test_sandbox.py

沙箱 Runtime 测试。
DockerRuntime 的真实 docker exec 路径需要 Docker 可用，
用 pytest.mark.skipif 跳过（CI / 没有 Docker 的环境）。
LocalRuntime 的测试不依赖 Docker，始终运行。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.runtime import (
    DockerRuntime, LocalRuntime, RunResult, create_runtime,
    CONTAINER_WORKDIR, SANDBOX_IMAGE,
)
from tools.shell_tool import ShellTool
from tools.test_tool import PytestTool
from tools.git_tool import GitStatusTool


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

DOCKER_AVAILABLE = shutil.which("docker") is not None and (
    subprocess.run(["docker", "info"], capture_output=True, timeout=5).returncode == 0
)


# ===========================================================================
# RunResult
# ===========================================================================

class TestRunResult:
    def test_success(self):
        r = RunResult(returncode=0, stdout="hello\n", stderr="")
        assert r.success
        assert r.output == "hello\n"

    def test_failure(self):
        r = RunResult(returncode=1, stdout="", stderr="error")
        assert not r.success

    def test_output_combines_stdout_stderr(self):
        r = RunResult(returncode=0, stdout="out", stderr="err")
        assert r.output == "outerr"


# ===========================================================================
# LocalRuntime
# ===========================================================================

class TestLocalRuntime:
    def test_exec_simple_command(self):
        rt = LocalRuntime()
        result = rt.exec("echo hello")
        assert result.success
        assert "hello" in result.output

    def test_exec_with_cwd(self, tmp_path):
        (tmp_path / "test.txt").write_text("content")
        rt = LocalRuntime()
        result = rt.exec("dir", cwd=str(tmp_path))
        assert result.success
        assert "test.txt" in result.output

    def test_exec_failure(self):
        rt = LocalRuntime()
        result = rt.exec("false")
        assert not result.success
        assert result.returncode != 0

    def test_exec_timeout(self):
        rt = LocalRuntime()
        result = rt.exec("ping -n 10 127.0.0.1", timeout=1)
        assert not result.success
        assert "timed out" in result.stderr.lower()

    def test_name(self):
        assert LocalRuntime().name == "local"

    def test_context_manager(self):
        with LocalRuntime() as rt:
            result = rt.exec("echo ctx")
        assert "ctx" in result.output

    def test_cleanup_is_noop(self):
        rt = LocalRuntime()
        rt.cleanup()  # 不应抛异常


# ===========================================================================
# ShellTool with LocalRuntime (默认)
# ===========================================================================

class TestShellToolWithRuntime:
    def test_default_uses_local_runtime(self):
        tool = ShellTool()
        assert isinstance(tool._runtime, LocalRuntime)

    def test_custom_runtime_injected(self):
        mock_rt = MagicMock()
        mock_rt.exec.return_value = RunResult(returncode=0, stdout="mocked\n", stderr="")
        tool = ShellTool(runtime=mock_rt)
        result = tool.execute({"cmd": "echo test"})
        # echo 是只读命令，直接走 runtime
        assert result.success
        mock_rt.exec.assert_called_once()

    def test_runtime_receives_correct_cmd(self):
        calls = []
        class RecordingRuntime(LocalRuntime):
            def exec(self, cmd, cwd=None, timeout=30):
                calls.append(cmd)
                return super().exec(cmd, cwd=cwd, timeout=timeout)

        tool = ShellTool(runtime=RecordingRuntime())
        tool.execute({"cmd": "echo hello"})
        assert len(calls) == 1
        assert calls[0] == "echo hello"

    def test_blocked_command_never_reaches_runtime(self):
        mock_rt = MagicMock()
        tool = ShellTool(runtime=mock_rt)
        result = tool.execute({"cmd": "rm -rf /"})
        assert not result.success
        assert "blocked" in result.error.lower()
        mock_rt.exec.assert_not_called()

    def test_denied_command_never_reaches_runtime(self):
        from tools.shell_tool import always_deny
        mock_rt = MagicMock()
        tool = ShellTool(confirm_callback=always_deny, runtime=mock_rt)
        result = tool.execute({"cmd": "pip install requests"})
        assert not result.success
        mock_rt.exec.assert_not_called()


# ===========================================================================
# PytestTool with runtime
# ===========================================================================

class TestTestToolWithRuntime:
    def test_default_uses_local_runtime(self):
        tool = PytestTool()
        assert isinstance(tool._runtime, LocalRuntime)

    def test_custom_runtime_used(self, tmp_path):
        # 用真实的 LocalRuntime，但通过 tmp_path 验证 cwd 传递
        calls = []
        class RecordingRuntime(LocalRuntime):
            def exec(self, cmd, cwd=None, timeout=30):
                calls.append({"cmd": cmd, "cwd": cwd})
                return super().exec(cmd, cwd=cwd, timeout=timeout)

        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_x.py").write_text("def test_ok(): assert True\n")

        tool = PytestTool(runtime=RecordingRuntime())
        tool.execute({"path": str(tests_dir), "cwd": str(tmp_path)})
        assert len(calls) == 1
        assert "pytest" in calls[0]["cmd"]


# ===========================================================================
# GitTool with runtime
# ===========================================================================

class TestGitToolWithRuntime:
    def test_default_uses_local_runtime(self):
        tool = GitStatusTool()
        assert isinstance(tool._runtime, LocalRuntime)

    def test_custom_runtime_called(self):
        calls = []
        class RecordingRuntime(LocalRuntime):
            def exec(self, cmd, cwd=None, timeout=30):
                calls.append(cmd)
                return super().exec(cmd, cwd=cwd, timeout=timeout)

        tool = GitStatusTool(runtime=RecordingRuntime())
        tool.execute({})
        assert any("git" in c for c in calls)


# ===========================================================================
# create_runtime 工厂函数
# ===========================================================================

class TestCreateRuntime:
    def test_no_sandbox_returns_local(self):
        rt = create_runtime(sandbox=False)
        assert isinstance(rt, LocalRuntime)

    def test_sandbox_without_repo_raises(self):
        with pytest.raises(ValueError, match="repo_path"):
            create_runtime(sandbox=True, repo_path=None)

    def test_sandbox_returns_docker_runtime(self, tmp_path):
        rt = create_runtime(sandbox=True, repo_path=str(tmp_path))
        assert isinstance(rt, DockerRuntime)
        # 不 start，不清理

    def test_local_runtime_context_manager(self):
        with create_runtime(sandbox=False) as rt:
            result = rt.exec("echo hi")
        assert "hi" in result.output


# ===========================================================================
# DockerRuntime — 单元测试（mock docker 调用）
# ===========================================================================

class TestDockerRuntimeUnit:
    """不需要真实 Docker 的单元测试。"""

    def _make_runtime(self, tmp_path) -> DockerRuntime:
        return DockerRuntime(repo_path=str(tmp_path))

    def test_name_includes_image(self, tmp_path):
        rt = self._make_runtime(tmp_path)
        assert "docker" in rt.name
        assert SANDBOX_IMAGE in rt.name

    def test_not_running_initially(self, tmp_path):
        rt = self._make_runtime(tmp_path)
        assert not rt.is_running
        assert rt.container_id is None

    def test_cleanup_when_not_running_is_safe(self, tmp_path):
        rt = self._make_runtime(tmp_path)
        rt.cleanup()   # 不应抛异常

    def test_docker_unavailable_returns_error(self, tmp_path):
        """Docker 不可用时 exec() 返回 error，不崩溃。"""
        rt = self._make_runtime(tmp_path)

        with patch("subprocess.run") as mock_run:
            # docker info 返回失败
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Cannot connect")
            result = rt.exec("echo hello")

        assert not result.success
        assert "docker" in result.stderr.lower() or "not available" in result.stderr.lower()

    def test_container_start_failure_returns_error(self, tmp_path):
        """容器启动失败时返回 error。"""
        rt = self._make_runtime(tmp_path)

        def mock_run(args, **kwargs):
            m = MagicMock()
            if "info" in args:
                m.returncode = 0   # docker info 成功
            else:
                m.returncode = 1   # docker run 失败
                m.stdout = ""
                m.stderr = "image not found"
            return m

        with patch("subprocess.run", side_effect=mock_run):
            result = rt.exec("echo hello")

        assert not result.success
        assert not rt.is_running

    def test_cwd_translation_inside_repo(self, tmp_path):
        """容器内 cwd：repo 子目录应被正确翻译为容器内路径。"""
        rt = DockerRuntime(repo_path=str(tmp_path))
        rt._container_id = "fake-container-id"

        sub = tmp_path / "src" / "module"
        sub.mkdir(parents=True)

        exec_calls = []

        def mock_popen(args=None, **kwargs):
            if args:
                exec_calls.append(args)
            m = MagicMock()
            m.returncode = 0
            m.stdout = "ok"
            m.stderr = ""
            m.communicate = MagicMock(return_value=("ok", ""))
            return m

        with patch("subprocess.Popen", side_effect=mock_popen):
            rt.exec("ls", cwd=str(sub))

        # 找到 docker exec 调用
        docker_exec_call = next(a for a in exec_calls if "exec" in a)
        workdir_idx = docker_exec_call.index("--workdir")
        container_cwd = docker_exec_call[workdir_idx + 1]
        assert container_cwd == f"{CONTAINER_WORKDIR}/src/module"

    def test_cleanup_removes_container(self, tmp_path):
        """cleanup() 应调用 docker rm -f。"""
        rt = self._make_runtime(tmp_path)
        rt._container_id = "abc123"

        rm_calls = []
        def mock_run(args, **kwargs):
            rm_calls.append(args)
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=mock_run):
            rt.cleanup()

        assert rt._container_id is None
        rm_call = next((a for a in rm_calls if "rm" in a), None)
        assert rm_call is not None
        assert "abc123" in rm_call


# ===========================================================================
# DockerRuntime — 集成测试（需要真实 Docker）
# ===========================================================================

@pytest.mark.skipif(not DOCKER_AVAILABLE, reason="Docker not available")
class TestDockerRuntimeIntegration:

    def test_exec_simple_command(self, tmp_path):
        with DockerRuntime(repo_path=str(tmp_path)) as rt:
            result = rt.exec("echo hello_from_docker")
        assert result.success
        assert "hello_from_docker" in result.output

    def test_exec_python(self, tmp_path):
        with DockerRuntime(repo_path=str(tmp_path)) as rt:
            result = rt.exec("python3 -c \"print('python ok')\"")
        assert result.success
        assert "python ok" in result.output

    def test_file_visible_in_container(self, tmp_path):
        """宿主机写入的文件在容器里可见。"""
        (tmp_path / "hello.txt").write_text("from host")
        with DockerRuntime(repo_path=str(tmp_path)) as rt:
            result = rt.exec("cat hello.txt")
        assert result.success
        assert "from host" in result.output

    def test_file_written_in_container_visible_on_host(self, tmp_path):
        """容器写入的文件在宿主机可见（bind mount 双向）。"""
        with DockerRuntime(repo_path=str(tmp_path)) as rt:
            rt.exec("echo from_container > container_output.txt")
        content = (tmp_path / "container_output.txt").read_text()
        assert "from_container" in content

    def test_no_network_by_default(self, tmp_path):
        """默认断网，curl 应失败。"""
        with DockerRuntime(repo_path=str(tmp_path)) as rt:
            result = rt.exec("curl -s --max-time 3 https://example.com", timeout=10)
        assert not result.success

    def test_cleanup_stops_container(self, tmp_path):
        rt = DockerRuntime(repo_path=str(tmp_path))
        rt.exec("echo start")   # 触发容器启动
        container_id = rt.container_id
        assert container_id is not None
        rt.cleanup()
        assert rt.container_id is None
        # 确认容器已被删除
        check = subprocess.run(
            ["docker", "inspect", container_id],
            capture_output=True, timeout=5,
        )
        assert check.returncode != 0  # 容器不存在

    def test_shell_tool_with_docker_runtime(self, tmp_path):
        """ShellTool + DockerRuntime 端到端。"""
        with DockerRuntime(repo_path=str(tmp_path)) as rt:
            tool = ShellTool(runtime=rt)
            result = tool.execute({"cmd": "python3 --version"})
        assert result.success
        assert "Python" in result.output


# ===========================================================================
# CLI --sandbox 选项
# ===========================================================================

class TestCliSandboxOption:
    def test_sandbox_in_run_help(self):
        from click.testing import CliRunner
        from entry.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--help"])
        assert "--sandbox" in result.output

    def test_sandbox_in_chat_help(self):
        from click.testing import CliRunner
        from entry.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["chat", "--help"])
        assert "--sandbox" in result.output