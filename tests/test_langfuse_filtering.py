from __future__ import annotations

import json
import tempfile
from pathlib import Path

from click.testing import CliRunner

from agent.event_log import EventLog
from agent.task import Task
from entry.cli import cli
from observability.filtering import (
    collect_log_filter_records,
    extract_log_filter_record,
    summarize_filter_groups,
)
from observability.models import build_task_metadata


def _write_log(
    repo_path: str,
    log_dir: str,
    *,
    description: str,
    metadata: dict,
    success: bool = True,
) -> Path:
    task = Task(
        description=description,
        repo_path=repo_path,
        metadata=metadata,
    )
    with EventLog.create(task, log_dir=log_dir) as log:
        log.log_task_start(task)
        if success:
            log.log_task_complete(steps=1, summary="done")
        else:
            log.log_task_failed(steps=1, reason="failed")
        return log.path


def test_build_task_metadata_includes_subtask_filter_fields() -> None:
    task = Task(
        description="subtask",
        repo_path=".",
        metadata={
            "session_id": "session-1",
            "parent_task_id": "parent-1",
            "subtask_id": "subtask-1",
            "subtask_type": "research",
            "role": "planner",
            "agent_id": "agent-1",
            "coordinator_task_id": "coord-1",
            "isolation": "worktree",
            "depends_on": ["subtask-0"],
            "spawn_index": 2,
        },
    )

    metadata = build_task_metadata(task)

    assert metadata["subtask_type"] == "research"
    assert metadata["agent_id"] == "agent-1"
    assert metadata["coordinator_task_id"] == "coord-1"
    assert metadata["isolation"] == "worktree"
    assert metadata["depends_on"] == ["subtask-0"]
    assert metadata["spawn_index"] == 2


def test_extract_log_filter_record_reads_session_and_subtask_metadata() -> None:
    with tempfile.TemporaryDirectory(dir=".") as tmp_dir:
        log_path = _write_log(
            tmp_dir,
            tmp_dir,
            description="worker task",
            metadata={
                "entrypoint": "chat",
                "mode": "multi-agent",
                "session_id": "session-42",
                "round": 3,
                "phase": "execution",
                "parent_task_id": "parent-7",
                "subtask_id": "subtask-9",
                "subtask_type": "code",
                "role": "worker",
                "agent_id": "agent-2",
                "coordinator_task_id": "coord-8",
                "isolation": "worktree",
                "depends_on": ["subtask-3", "subtask-4"],
                "spawn_index": 1,
                "provider": "deepseek",
                "model": "deepseek-chat",
            },
            success=False,
        )

        record = extract_log_filter_record(log_path)

        assert record.entrypoint == "chat"
        assert record.mode == "multi-agent"
        assert record.session_id == "session-42"
        assert record.round == 3
        assert record.phase == "execution"
        assert record.parent_task_id == "parent-7"
        assert record.subtask_id == "subtask-9"
        assert record.subtask_type == "code"
        assert record.role == "worker"
        assert record.agent_id == "agent-2"
        assert record.coordinator_task_id == "coord-8"
        assert record.isolation == "worktree"
        assert record.depends_on == ["subtask-3", "subtask-4"]
        assert record.spawn_index == 1
        assert record.provider == "deepseek"
        assert record.model == "deepseek-chat"
        assert record.final_event == "task_failed"


def test_collect_log_filter_records_and_group_summary() -> None:
    with tempfile.TemporaryDirectory(dir=".") as tmp_dir:
        log_a = _write_log(
            tmp_dir,
            tmp_dir,
            description="planner",
            metadata={
                "mode": "dag",
                "session_id": "session-a",
                "parent_task_id": "parent-1",
                "subtask_id": "subtask-a",
                "role": "planner",
                "agent_id": "agent-1",
            },
        )
        log_b = _write_log(
            tmp_dir,
            tmp_dir,
            description="worker",
            metadata={
                "mode": "dag",
                "session_id": "session-a",
                "parent_task_id": "parent-1",
                "subtask_id": "subtask-b",
                "role": "worker",
                "agent_id": "agent-2",
            },
        )
        log_c = _write_log(
            tmp_dir,
            tmp_dir,
            description="reviewer",
            metadata={
                "mode": "multi-agent",
                "session_id": "session-b",
                "parent_task_id": "parent-2",
                "subtask_id": "subtask-c",
                "role": "reviewer",
                "agent_id": "agent-3",
            },
        )

        records = collect_log_filter_records([log_a, log_b, log_c])
        groups = summarize_filter_groups(records)

        assert len(records) == 3
        assert groups["session_id"] == {"session-a": 2, "session-b": 1}
        assert groups["parent_task_id"] == {"parent-1": 2, "parent-2": 1}
        assert groups["subtask_id"] == {"subtask-a": 1, "subtask-b": 1, "subtask-c": 1}
        assert groups["role"] == {"planner": 1, "worker": 1, "reviewer": 1}
        assert groups["agent_id"] == {"agent-1": 1, "agent-2": 1, "agent-3": 1}


def test_log_filters_cli_emits_json_summary() -> None:
    with tempfile.TemporaryDirectory(dir=".") as tmp_dir:
        log_a = _write_log(
            tmp_dir,
            tmp_dir,
            description="planner",
            metadata={
                "mode": "dag",
                "session_id": "session-a",
                "parent_task_id": "parent-1",
                "subtask_id": "subtask-a",
                "role": "planner",
                "agent_id": "agent-1",
            },
        )
        log_b = _write_log(
            tmp_dir,
            tmp_dir,
            description="worker",
            metadata={
                "mode": "dag",
                "session_id": "session-a",
                "parent_task_id": "parent-1",
                "subtask_id": "subtask-b",
                "role": "worker",
                "agent_id": "agent-2",
            },
        )

        result = CliRunner().invoke(cli, ["log", "filters", "--json", str(log_a), str(log_b)])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert len(payload["records"]) == 2
        assert payload["groups"]["session_id"] == {"session-a": 2}
        assert payload["groups"]["parent_task_id"] == {"parent-1": 2}
        assert payload["groups"]["role"] == {"planner": 1, "worker": 1}
