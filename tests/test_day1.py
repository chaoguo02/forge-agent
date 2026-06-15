"""
tests/test_day1.py

覆盖 agent/task.py 和 agent/event_log.py 的关键路径：
- 数据类构造、序列化、反序列化
- EventLog 写入、flush、replay
- 循环检测辅助方法
- 上下文管理器
- summarize_run 统计
"""

import json
import tempfile
from pathlib import Path

import pytest

from agent.task import (
    Action, ActionType, Event, EventType, Observation, ObservationStatus,
    RunResult, RunStatus, Task, ToolCall,
)
from agent.event_log import EventLog, summarize_run


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_task() -> Task:
    return Task(
        task_id="abc12345",
        description="Fix the failing test in test_parser.py",
        repo_path="/tmp/repo",
        test_cmd="pytest tests/",
        max_steps=10,
    )


@pytest.fixture
def tool_call() -> ToolCall:
    return ToolCall(name="shell", params={"cmd": "pytest tests/", "timeout": 30})


@pytest.fixture
def shell_action(tool_call) -> Action:
    return Action(
        action_type=ActionType.TOOL_CALL,
        thought="I need to run the tests first to understand the failure.",
        tool_calls=[tool_call],
    )


@pytest.fixture
def success_observation() -> Observation:
    return Observation(
        status=ObservationStatus.SUCCESS,
        output="1 passed, 0 failed",
        tool_name="shell",
        tokens_used=12,
    )


@pytest.fixture
def error_observation() -> Observation:
    return Observation(
        status=ObservationStatus.ERROR,
        output="AssertionError: expected 1 got 2",
        tool_name="shell",
        tokens_used=18,
        error="pytest exit code 1",
    )


@pytest.fixture
def tmp_log_dir(tmp_path) -> Path:
    return tmp_path / "logs"


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------

class TestTask:
    def test_default_task_id_generated(self):
        t = Task(description="do something", repo_path="/tmp")
        assert len(t.task_id) == 8

    def test_custom_task_id(self, sample_task):
        assert sample_task.task_id == "abc12345"

    def test_to_dict_contains_required_fields(self, sample_task):
        d = sample_task.to_dict()
        assert d["description"] == "Fix the failing test in test_parser.py"
        assert d["repo_path"] == "/tmp/repo"
        assert d["task_id"] == "abc12345"
        assert d["max_steps"] == 10
        assert d["test_cmd"] == "pytest tests/"

    def test_repr(self, sample_task):
        r = repr(sample_task)
        assert "abc12345" in r
        assert "Fix the failing" in r


# ---------------------------------------------------------------------------
# ToolCall
# ---------------------------------------------------------------------------

class TestToolCall:
    def test_to_dict(self, tool_call):
        d = tool_call.to_dict()
        assert d["name"] == "shell"
        assert d["params"]["cmd"] == "pytest tests/"

    def test_serializable_to_json(self, tool_call):
        # 确保可以直接 json.dumps，没有不可序列化的类型
        json.dumps(tool_call.to_dict())


# ---------------------------------------------------------------------------
# Action
# ---------------------------------------------------------------------------

class TestAction:
    def test_tool_call_action(self, shell_action):
        assert shell_action.action_type == ActionType.TOOL_CALL
        assert len(shell_action.tool_calls) == 1
        assert shell_action.tool_calls[0].name == "shell"
        assert not shell_action.is_terminal()

    def test_finish_action_is_terminal(self):
        action = Action(
            action_type=ActionType.FINISH,
            thought="Task is complete.",
            message="Fixed the parser bug.",
        )
        assert action.is_terminal()
        assert not action.tool_calls

    def test_give_up_action_is_terminal(self):
        action = Action(
            action_type=ActionType.GIVE_UP,
            thought="Cannot find the root cause.",
            message="Insufficient context.",
        )
        assert action.is_terminal()

    def test_to_dict_roundtrip(self, shell_action):
        d = shell_action.to_dict()
        assert d["action_type"] == "tool_call"
        assert d["thought"].startswith("I need to run")
        assert len(d["tool_calls"]) == 1
        assert d["tool_calls"][0]["name"] == "shell"
        assert d["message"] is None

    def test_repr_with_tool_call(self, shell_action):
        assert "shell" in repr(shell_action)

    def test_repr_without_tool_call(self):
        action = Action(action_type=ActionType.FINISH, thought="done")
        assert "finish" in repr(action)

    def test_to_dict_json_serializable(self, shell_action):
        json.dumps(shell_action.to_dict())


# ---------------------------------------------------------------------------
# Observation
# ---------------------------------------------------------------------------

class TestObservation:
    def test_success_observation(self, success_observation):
        assert success_observation.is_success()
        assert success_observation.error is None

    def test_error_observation(self, error_observation):
        assert not error_observation.is_success()
        assert error_observation.error == "pytest exit code 1"

    def test_to_dict(self, success_observation):
        d = success_observation.to_dict()
        assert d["status"] == "success"
        assert d["tool_name"] == "shell"
        assert d["tokens_used"] == 12

    def test_repr(self, success_observation):
        r = repr(success_observation)
        assert "shell" in r
        assert "success" in r


# ---------------------------------------------------------------------------
# RunResult
# ---------------------------------------------------------------------------

class TestRunResult:
    def test_success_result(self):
        r = RunResult(
            task_id="abc12345",
            status=RunStatus.SUCCESS,
            summary="Fixed the bug.",
            steps_taken=5,
            total_tokens=3200,
            patch="diff --git a/foo.py ...",
        )
        assert r.is_success()
        assert r.patch is not None

    def test_failed_result(self):
        r = RunResult(
            task_id="abc12345",
            status=RunStatus.FAILED,
            summary="Could not fix.",
            steps_taken=40,
            error="max steps reached",
        )
        assert not r.is_success()

    def test_to_dict(self):
        r = RunResult(
            task_id="abc12345",
            status=RunStatus.MAX_STEPS,
            summary="Hit limit.",
            steps_taken=40,
        )
        d = r.to_dict()
        assert d["status"] == "max_steps"
        assert d["steps_taken"] == 40


# ---------------------------------------------------------------------------
# EventLog — 写入与 replay
# ---------------------------------------------------------------------------

class TestEventLogWriteAndReplay:
    def test_create_makes_directory(self, sample_task, tmp_log_dir):
        log = EventLog.create(sample_task, log_dir=str(tmp_log_dir))
        assert tmp_log_dir.exists()
        log.close()

    def test_log_file_named_with_task_id(self, sample_task, tmp_log_dir):
        log = EventLog.create(sample_task, log_dir=str(tmp_log_dir))
        assert sample_task.task_id in log.path.name
        log.close()

    def test_task_start_event_written(self, sample_task, tmp_log_dir):
        log = EventLog.create(sample_task, log_dir=str(tmp_log_dir))
        log.log_task_start(sample_task)
        log.close()

        lines = log.path.read_text().strip().splitlines()
        assert len(lines) == 1
        raw = json.loads(lines[0])
        assert raw["event_type"] == "task_start"
        assert raw["payload"]["task"]["task_id"] == "abc12345"

    def test_action_and_observation_written(
        self, sample_task, shell_action, success_observation, tmp_log_dir
    ):
        log = EventLog.create(sample_task, log_dir=str(tmp_log_dir))
        log.log_task_start(sample_task)
        log.log_action(step=1, action=shell_action)
        log.log_observation(step=1, observation=success_observation)
        log.close()

        lines = log.path.read_text().strip().splitlines()
        assert len(lines) == 3

        types = [json.loads(l)["event_type"] for l in lines]
        assert types == ["task_start", "action", "observation"]

    def test_replay_restores_all_events(
        self, sample_task, shell_action, success_observation, tmp_log_dir
    ):
        log = EventLog.create(sample_task, log_dir=str(tmp_log_dir))
        log.log_task_start(sample_task)
        log.log_action(step=1, action=shell_action)
        log.log_observation(step=1, observation=success_observation)
        log.log_task_complete(steps=1, summary="All tests passing.")
        log.close()

        events = log.replay()
        assert len(events) == 4
        assert events[0].event_type == EventType.TASK_START
        assert events[1].event_type == EventType.ACTION
        assert events[2].event_type == EventType.OBSERVATION
        assert events[3].event_type == EventType.TASK_COMPLETE

    def test_replay_preserves_payload(
        self, sample_task, shell_action, tmp_log_dir
    ):
        log = EventLog.create(sample_task, log_dir=str(tmp_log_dir))
        log.log_task_start(sample_task)
        log.log_action(step=1, action=shell_action)
        log.close()

        events = log.replay()
        action_event = events[1]
        assert action_event.payload["step"] == 1
        assert action_event.payload["action"]["thought"].startswith("I need to run")
        assert action_event.payload["action"]["tool_calls"][0]["name"] == "shell"

    def test_reflection_logged(self, sample_task, tmp_log_dir):
        log = EventLog.create(sample_task, log_dir=str(tmp_log_dir))
        log.log_task_start(sample_task)
        log.log_reflection(
            step=3,
            reason="test_failed",
            prompt="Tests are failing. Reconsider your approach.",
        )
        log.close()

        events = log.replay()
        assert events[1].event_type == EventType.REFLECTION
        assert events[1].payload["reason"] == "test_failed"

    def test_task_failed_logged(self, sample_task, tmp_log_dir):
        log = EventLog.create(sample_task, log_dir=str(tmp_log_dir))
        log.log_task_start(sample_task)
        log.log_task_failed(steps=40, reason="max_steps")
        log.close()

        events = log.replay()
        assert events[-1].event_type == EventType.TASK_FAILED
        assert events[-1].payload["reason"] == "max_steps"


# ---------------------------------------------------------------------------
# EventLog — 上下文管理器
# ---------------------------------------------------------------------------

class TestEventLogContextManager:
    def test_context_manager_closes_file(self, sample_task, tmp_log_dir):
        with EventLog.create(sample_task, log_dir=str(tmp_log_dir)) as log:
            log.log_task_start(sample_task)
            path = log.path

        # 退出后文件句柄已关闭，文件内容已落盘
        assert path.exists()
        lines = path.read_text().strip().splitlines()
        assert len(lines) == 1


# ---------------------------------------------------------------------------
# EventLog — get_actions（循环检测辅助）
# ---------------------------------------------------------------------------

class TestGetActions:
    def test_get_actions_returns_only_actions(
        self, sample_task, shell_action, success_observation, tmp_log_dir
    ):
        with EventLog.create(sample_task, log_dir=str(tmp_log_dir)) as log:
            log.log_task_start(sample_task)
            log.log_action(step=1, action=shell_action)
            log.log_observation(step=1, observation=success_observation)
            log.log_action(step=2, action=shell_action)

        actions = log.get_actions()
        assert len(actions) == 2
        assert all(a.action_type == ActionType.TOOL_CALL for a in actions)
        assert all(a.tool_calls[0].name == "shell" for a in actions)

    def test_get_actions_empty_log(self, sample_task, tmp_log_dir):
        with EventLog.create(sample_task, log_dir=str(tmp_log_dir)) as log:
            log.log_task_start(sample_task)

        assert log.get_actions() == []


# ---------------------------------------------------------------------------
# EventLog — iter_events 惰性迭代
# ---------------------------------------------------------------------------

class TestIterEvents:
    def test_iter_events(self, sample_task, shell_action, tmp_log_dir):
        with EventLog.create(sample_task, log_dir=str(tmp_log_dir)) as log:
            log.log_task_start(sample_task)
            log.log_action(step=1, action=shell_action)

        collected = list(log.iter_events())
        assert len(collected) == 2
        assert isinstance(collected[0], Event)


# ---------------------------------------------------------------------------
# summarize_run
# ---------------------------------------------------------------------------

class TestSummarizeRun:
    def test_summarize_complete_run(
        self,
        sample_task,
        shell_action,
        success_observation,
        error_observation,
        tmp_log_dir,
    ):
        with EventLog.create(sample_task, log_dir=str(tmp_log_dir)) as log:
            log.log_task_start(sample_task)
            log.log_action(step=1, action=shell_action)
            log.log_observation(step=1, observation=success_observation)
            log.log_action(step=2, action=shell_action)
            log.log_observation(step=2, observation=error_observation)
            log.log_reflection(step=2, reason="test_failed", prompt="retry")
            log.log_action(step=3, action=shell_action)
            log.log_observation(step=3, observation=success_observation)
            log.log_task_complete(steps=3, summary="Done")

        stats = summarize_run(log)
        assert stats["actions"] == 3
        assert stats["reflections"] == 1
        assert stats["observations_ok"] == 2
        assert stats["observations_err"] == 1
        assert stats["tool_calls"]["shell"] == 3
        assert stats["final_status"] == "task_complete"
