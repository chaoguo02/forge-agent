"""Tests for replay validation and harness gates (Phase 15 Issue 05)."""

import pytest

from observability.models import REPLAY_CONTRACT_VERSION
from observability.replay_validator import (
    ReplayValidationResult,
    ValidationIssue,
    gate_boundary_preservation,
    gate_replay_completeness,
    validate_replay_run,
    validate_replay_snapshot,
    validate_replay_step,
)


def _minimal_run_record(**overrides):
    """Build a minimal valid run record dict."""
    record = {
        "version": REPLAY_CONTRACT_VERSION,
        "run_id": "run-001",
        "task_id": "task-001",
        "session_id": "sess-001",
        "generation": 0,
        "task": {},
        "provenance": {},
        "permission_snapshot": {},
        "runtime_snapshot": {},
        "visible_tools": [],
        "steps": [],
        "termination_reason": "none",
        "termination_status": "",
        "summary": "",
    }
    record.update(overrides)
    return record


def _minimal_step_record(step=1, **overrides):
    """Build a minimal valid step record dict."""
    record = {
        "step": step,
        "runtime_decision": {"action": "continue", "reason": ""},
        "visible_tools": [],
        "model_action": {"action_type": "tool_call", "thought": "", "message": "", "tool_calls": []},
        "tool_executions": [],
        "outcome": "continue",
        "termination_reason": "none",
        "termination_status": "",
    }
    record.update(overrides)
    return record


class TestReplaySnapshotValidation:
    """Reject incomplete or schema-incompatible replay records."""

    def test_valid_snapshot_passes(self):
        snapshot = {
            "version": REPLAY_CONTRACT_VERSION,
            "run": _minimal_run_record(),
        }
        result = validate_replay_snapshot(snapshot)
        assert result.valid
        assert result.boundary_preserved
        assert len(result.errors) == 0

    def test_missing_version_fails(self):
        snapshot = {"run": _minimal_run_record()}
        result = validate_replay_snapshot(snapshot)
        assert not result.valid
        assert any("version" in i.field for i in result.errors)

    def test_wrong_version_fails(self):
        snapshot = {
            "version": 999,
            "run": _minimal_run_record(),
        }
        result = validate_replay_snapshot(snapshot)
        assert not result.valid
        assert any("version" in i.message for i in result.errors)

    def test_missing_run_fails(self):
        snapshot = {"version": REPLAY_CONTRACT_VERSION}
        result = validate_replay_snapshot(snapshot)
        assert not result.valid
        assert any("run" in i.field for i in result.errors)


class TestRunRecordValidation:
    """Validate run record structure."""

    def test_valid_run_passes(self):
        run = _minimal_run_record()
        result = validate_replay_run(run)
        assert result.valid

    def test_missing_run_id_fails(self):
        run = _minimal_run_record(run_id="")
        result = validate_replay_run(run)
        assert not result.valid
        assert any("run_id" in i.field for i in result.errors)

    def test_missing_task_id_fails(self):
        run = _minimal_run_record(task_id="")
        result = validate_replay_run(run)
        assert not result.valid
        assert any("task_id" in i.field for i in result.errors)

    def test_steps_validated_count(self):
        steps = [_minimal_step_record(i) for i in range(1, 4)]
        run = _minimal_run_record(steps=steps)
        result = validate_replay_run(run)
        assert result.valid
        assert result.steps_validated == 3

    def test_malformed_step_reduces_validated_count(self):
        steps = [
            _minimal_step_record(1),
            {"step": None, "runtime_decision": None},  # malformed
            _minimal_step_record(3),
        ]
        run = _minimal_run_record(steps=steps)
        result = validate_replay_run(run)
        # May still be valid overall (step issues are warnings)
        assert result.steps_validated == 2


class TestStepRecordValidation:
    """Validate individual step records."""

    def test_valid_step_has_no_errors(self):
        step = _minimal_step_record(1)
        issues = validate_replay_step(step)
        errors = [i for i in issues if i.severity == "error"]
        assert len(errors) == 0

    def test_missing_step_number_is_error(self):
        step = _minimal_step_record(1)
        del step["step"]
        issues = validate_replay_step(step)
        errors = [i for i in issues if i.severity == "error"]
        assert any("step" in i.field for i in errors)

    def test_missing_runtime_decision_is_error(self):
        step = _minimal_step_record(1)
        del step["runtime_decision"]
        issues = validate_replay_step(step)
        errors = [i for i in issues if i.severity == "error"]
        assert any("runtime_decision" in i.field for i in errors)

    def test_unexpected_action_value_is_warning(self):
        step = _minimal_step_record(1)
        step["runtime_decision"]["action"] = "unknown_action"
        issues = validate_replay_step(step)
        warnings = [i for i in issues if i.severity == "warning"]
        assert any("action" in i.field for i in warnings)


class TestBoundaryPreservationGate:
    """Gate regressions in boundary preservation."""

    def test_gate_passes_correct_boundary(self):
        passed, msg = gate_boundary_preservation("budget_exhausted", "gave_up")
        assert passed

    def test_gate_fails_violated_boundary(self):
        passed, msg = gate_boundary_preservation("budget_exhausted", "success")
        assert not passed
        assert "boundary violation" in msg

    def test_gate_fails_unknown_reason(self):
        passed, msg = gate_boundary_preservation("unknown_xyz", "success")
        assert not passed
        assert "unknown" in msg

    def test_gate_fails_unknown_status(self):
        passed, msg = gate_boundary_preservation("budget_exhausted", "nonexistent_status")
        assert not passed
        assert "unknown" in msg

    def test_gate_max_steps_correct(self):
        passed, _ = gate_boundary_preservation("max_steps", "max_steps")
        assert passed

    def test_gate_model_error_correct(self):
        passed, _ = gate_boundary_preservation("model_error", "failed")
        assert passed

    def test_run_record_with_boundary_violation_detected(self):
        run = _minimal_run_record(
            termination_reason="budget_exhausted",
            termination_status="success",  # WRONG — should be gave_up
        )
        result = validate_replay_run(run)
        assert not result.boundary_preserved
        assert any("boundary" in i.field for i in result.issues)


class TestReplayCompletenessGate:
    """Gate incomplete replay records."""

    def test_complete_record_passes(self):
        run = _minimal_run_record()
        passed, msg = gate_replay_completeness(run)
        assert passed

    def test_wrong_version_fails(self):
        run = _minimal_run_record(version=999)
        passed, msg = gate_replay_completeness(run)
        assert not passed
        assert "version" in msg

    def test_missing_run_id_fails(self):
        run = _minimal_run_record(run_id="")
        passed, msg = gate_replay_completeness(run)
        assert not passed
        assert "run_id" in msg

    def test_missing_task_id_fails(self):
        run = _minimal_run_record(task_id="")
        passed, msg = gate_replay_completeness(run)
        assert not passed
        assert "task_id" in msg

    def test_min_steps_enforced(self):
        run = _minimal_run_record(steps=[_minimal_step_record(1)])
        passed, msg = gate_replay_completeness(run, min_steps=3)
        assert not passed
        assert "too few steps" in msg

    def test_min_steps_zero_always_passes(self):
        run = _minimal_run_record(steps=[])
        passed, msg = gate_replay_completeness(run, min_steps=0)
        assert passed

    def test_inconsistent_termination_fields_fail(self):
        run = _minimal_run_record(
            termination_reason="none",
            termination_status="gave_up",  # inconsistent
        )
        passed, msg = gate_replay_completeness(run)
        assert not passed
        assert "termination" in msg

    def test_non_dict_fails(self):
        passed, msg = gate_replay_completeness("not a dict")
        assert not passed
        assert "not a dict" in msg
