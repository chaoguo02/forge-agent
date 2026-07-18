from __future__ import annotations

import json
import tempfile
from pathlib import Path

from agent.task import RunStatus, Task
from agent.event_log import EventLog
from config.schema import load_config
from observability.datasets import append_failure_dataset_item
from observability.masking import sanitize_for_langfuse
from observability.models import build_analysis_run_metadata, build_run_output, build_task_metadata
from observability.scores import build_run_scores
from observability.tracing import _LangfuseObservationHandle
from observability.tracing import NoOpObserver, configure_observability


def test_load_config_parses_observability() -> None:
    with tempfile.TemporaryDirectory(dir=".") as tmp_dir:
        config_path = Path(tmp_dir) / "config.yaml"
        config_path.write_text(
            "\n".join(
                [
                    "llm:",
                    "  provider: openai",
                    "  model: gpt-4o-mini",
                    "observability:",
                    "  enabled: true",
                    "  provider: langfuse",
                    "  environment: staging",
                    "  sample_rate: 0.5",
                    "  langfuse:",
                    "    public_key: pk-lf-test",
                    "    secret_key: sk-lf-test",
                    "    base_url: https://cloud.langfuse.com",
                ]
            ),
            encoding="utf-8",
        )

        config = load_config(config_path)

        assert config.observability.enabled is True
        assert config.observability.environment == "staging"
        assert config.observability.sample_rate == 0.5
        assert config.observability.langfuse.public_key == "pk-lf-test"


def test_sanitize_for_langfuse_masks_nested_secrets() -> None:
    payload = {
        "api_key": "sk-secret-value",
        "nested": {
            "email": "dev@example.com",
            "password": "hello123",
        },
    }

    sanitized = sanitize_for_langfuse(payload)

    assert "secret-value" not in str(sanitized)
    assert "dev@example.com" not in str(sanitized)
    assert "[REDACTED" in str(sanitized)


def test_configure_observability_defaults_to_noop() -> None:
    config = load_config(None)
    observer = configure_observability(config)

    assert isinstance(observer, NoOpObserver)
    with observer.start_task(Task(description="demo", repo_path=".")) as handle:
        handle.update(output={"ok": True})


def test_task_metadata_and_run_output_include_langfuse_fields() -> None:
    task = Task(
        description="demo",
        repo_path=".",
        metadata={"entrypoint": "chat", "session_id": "session-1", "mode": "react"},
    )
    metadata = build_task_metadata(task)
    output = build_run_output(
        type(
            "Result",
            (),
            {
                "status": RunStatus.SUCCESS,
                "summary": "done",
                "steps_taken": 2,
                "total_tokens": 42,
                "patch": None,
            },
        )()
    )

    assert metadata["entrypoint"] == "chat"
    assert metadata["session_id"] == "session-1"
    assert output["status"] == "success"


def test_build_run_scores_for_edit_task() -> None:
    task = Task(description="edit", repo_path=".", intent="edit", metadata={"entrypoint": "cli_run"})
    result = type(
        "Result",
        (),
        {
            "status": RunStatus.SUCCESS,
            "summary": "done",
            "steps_taken": 3,
            "total_tokens": 99,
            "patch": "diff --git a/x b/x",
            "error": None,
        },
    )()

    scores = build_run_scores(task, result, stats={"observations_err": 2, "reflections": 1})
    score_map = {score.name: score.value for score in scores}

    assert score_map["grace.task_success"] == 1.0
    assert score_map["grace.task_error_free"] == 1.0
    assert score_map["grace.task_patch_generated"] == 1.0
    assert score_map["grace.task_max_steps_exhausted"] == 0.0
    assert score_map["grace.task_tool_error_count"] == 2.0
    assert score_map["grace.task_reflection_count"] == 1.0
    assert score_map["grace.task_tool_decision_count"] == 0.0
    assert score_map["grace.task_recovery_action_count"] == 0.0


def test_build_run_scores_for_analysis_task_include_claim_and_recovery_metrics() -> None:
    task = Task(description="audit", repo_path=".", intent="analysis", metadata={"entrypoint": "cli_run"})
    result = type(
        "Result",
        (),
        {
            "status": RunStatus.SUCCESS,
            "summary": "done",
            "steps_taken": 4,
            "total_tokens": 123,
            "patch": None,
            "error": None,
        },
    )()

    scores = build_run_scores(
        task,
        result,
        stats={"claims_created": 3, "tool_decisions": 2, "recovery_actions": 1, "analysis_deferred_reads": 2},
    )
    score_map = {score.name: score.value for score in scores}

    assert score_map["grace.analysis_claim_count"] == 3.0
    assert score_map["grace.analysis_deferred_read_count"] == 2.0
    assert score_map["grace.task_tool_decision_count"] == 2.0
    assert score_map["grace.task_recovery_action_count"] == 1.0


def test_build_analysis_run_metadata_includes_analysis_counters() -> None:
    context_stats = type(
        "Ctx",
        (),
        {
            "analysis_phase": "answer",
            "analysis_files_read": 5,
            "analysis_inspect_reads": 5,
            "analysis_verify_reads": 1,
            "analysis_evidence_records": 5,
            "analysis_phase_summaries": 1,
            "analysis_claims": 5,
            "analysis_tool_decisions": 2,
            "analysis_recovery_actions": 1,
            "analysis_deferred_reads": 2,
            "analysis_phase_token_costs": {"inspect": 750, "answer": 150},
        },
    )()

    metadata = build_analysis_run_metadata(
        run_stats={
            "tool_decisions": 2,
            "recovery_actions": 1,
            "claims_created": 5,
            "analysis_deferred_reads": 2,
            "analysis_phase_token_costs": {"inspect": 750, "answer": 150},
            "analysis_phase_llm_calls": {"inspect": 5, "answer": 1},
        },
        context_stats=context_stats,
    )

    assert metadata["tool_decisions"] == 2
    assert metadata["recovery_actions"] == 1
    assert metadata["claims_created"] == 5
    assert metadata["analysis_phase"] == "answer"
    assert metadata["analysis_claims"] == 5
    assert metadata["analysis_phase_token_costs"]["inspect"] == 750
    assert metadata["analysis_phase_llm_calls"]["answer"] == 1


def test_langfuse_observation_handle_writes_score_with_trace_id() -> None:
    calls: list[dict] = []

    class FakeClient:
        def create_score(self, **kwargs):
            calls.append(kwargs)

    class FakeObservation:
        trace_id = "trace-123"
        id = "obs-456"

    handle = _LangfuseObservationHandle(
        client=FakeClient(),
        observation=FakeObservation(),
        config=load_config(None).observability,
    )

    handle.score(name="grace.task_success", value=1.0, metadata={"status": "success"})

    assert calls == [
        {
            "trace_id": "trace-123",
            "observation_id": "obs-456",
            "name": "grace.task_success",
            "value": 1.0,
            "data_type": "NUMERIC",
            "metadata": {"status": "success"},
        }
    ]


def test_langfuse_observation_handle_writes_event_with_trace_id() -> None:
    calls: list[dict] = []

    class FakeClient:
        def create_event(self, **kwargs):
            calls.append(kwargs)

    class FakeObservation:
        trace_id = "trace-123"
        id = "obs-456"

    handle = _LangfuseObservationHandle(
        client=FakeClient(),
        observation=FakeObservation(),
        config=load_config(None).observability,
    )

    handle.event(
        name="tool_decision",
        metadata={"reason": "read_plan_required"},
        input_data={"path": "agent/core.py"},
        output_data={"synthetic_observation": "Deferred source read"},
        level="WARNING",
    )

    assert calls == [
        {
            "trace_id": "trace-123",
            "name": "tool_decision",
            "parent_observation_id": "obs-456",
            "metadata": {"reason": "read_plan_required"},
            "input": {"path": "agent/core.py"},
            "output": {"synthetic_observation": "Deferred source read"},
            "level": "WARNING",
        }
    ]


def test_append_failure_dataset_item_for_top_level_failure() -> None:
    with tempfile.TemporaryDirectory(dir=".") as tmp_dir:
        task = Task(
            description="fix failing build",
            repo_path=tmp_dir,
            intent="edit",
            metadata={"entrypoint": "cli_run", "mode": "react"},
        )
        dataset_path = Path(tmp_dir) / "failures.jsonl"

        with EventLog.create(task, log_dir=tmp_dir) as log:
            log.log_task_start(task)
            log.log_task_failed(steps=2, reason="build still failing")
            result = type(
                "Result",
                (),
                {
                    "status": RunStatus.FAILED,
                    "summary": "build still failing",
                    "steps_taken": 2,
                    "total_tokens": 12,
                    "patch": None,
                    "error": "build still failing",
                },
            )()
            written_path = append_failure_dataset_item(task, result, log_path=log.path, dataset_path=dataset_path)

        assert written_path == dataset_path
        lines = dataset_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        item = json.loads(lines[0])
        assert item["dataset_name"] == "forge-agent/failures"
        assert item["input"]["task"] == "fix failing build"
        assert item["metadata"]["final_status"] == "failed"
        assert item["metadata"]["tool_error_count"] == 0
        assert item["metadata"]["action_count"] == 0


def test_append_failure_dataset_item_skips_nested_or_successful_tasks() -> None:
    with tempfile.TemporaryDirectory(dir=".") as tmp_dir:
        dataset_path = Path(tmp_dir) / "failures.jsonl"

        success_task = Task(description="ok", repo_path=tmp_dir, intent="analysis")
        success_result = type(
            "Result",
            (),
            {
                "status": RunStatus.SUCCESS,
                "summary": "done",
                "steps_taken": 1,
                "total_tokens": 1,
                "patch": None,
                "error": None,
            },
        )()
        assert append_failure_dataset_item(success_task, success_result, dataset_path=dataset_path) is None

        nested_task = Task(
            description="nested fail",
            repo_path=tmp_dir,
            metadata={"parent_task_id": "parent-1"},
        )
        nested_result = type(
            "Result",
            (),
            {
                "status": RunStatus.GAVE_UP,
                "summary": "gave up",
                "steps_taken": 3,
                "total_tokens": 8,
                "patch": None,
                "error": None,
            },
        )()
        assert append_failure_dataset_item(nested_task, nested_result, dataset_path=dataset_path) is None
        assert not dataset_path.exists()
