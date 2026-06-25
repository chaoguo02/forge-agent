from __future__ import annotations

import json
import tempfile
from pathlib import Path

from observability.ci import (
    compare_validation_report_to_baseline,
    load_json_file,
    render_ci_markdown_summary,
    write_json_file,
    write_text_file,
)


def _report_payload(*, tokens: int = 120, passed: bool = True) -> dict:
    return {
        "all_passed": passed,
        "results": [
            {
                "scenario": "success-readonly",
                "expected_status": "success",
                "actual_status": "success" if passed else "failed",
                "passed": passed,
                "repo_path": ".",
                "summary": "ok",
                "steps": 2,
                "tokens": tokens,
                "log_path": "logs/demo.jsonl",
                "trace_id": "trace-1",
                "trace_url": "https://example.com/trace-1",
            }
        ],
    }


def _baseline_payload(*, tokens: int = 100) -> dict:
    return {
        "baseline_name": "nightly-main",
        "created_at": "2026-06-25T00:00:00+00:00",
        "repo_path": ".",
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "prompt_source": "local",
        "prompt_label": "production",
        "prompt_version": None,
        "scenarios": ["success-readonly"],
        "all_passed": True,
        "pass_rate": 1.0,
        "average_tokens": float(tokens),
        "results": [
            {
                "scenario": "success-readonly",
                "expected_status": "success",
                "actual_status": "success",
                "passed": True,
                "repo_path": ".",
                "summary": "ok",
                "steps": 2,
                "tokens": tokens,
                "log_path": "logs/demo.jsonl",
                "trace_id": "trace-1",
                "trace_url": "https://example.com/trace-1",
            }
        ],
        "metadata": {},
    }


def test_compare_validation_report_to_baseline_passes_within_threshold() -> None:
    comparison = compare_validation_report_to_baseline(
        _report_payload(tokens=110),
        _baseline_payload(tokens=100),
        max_token_regression_pct=0.2,
        report_path="report.json",
        baseline_path="baseline.json",
    )

    assert comparison.passed is True
    assert comparison.report_path == "report.json"
    assert comparison.baseline_path == "baseline.json"
    assert all(check.passed for check in comparison.checks)


def test_compare_validation_report_to_baseline_fails_on_token_regression() -> None:
    comparison = compare_validation_report_to_baseline(
        _report_payload(tokens=160),
        _baseline_payload(tokens=100),
        max_token_regression_pct=0.2,
    )

    assert comparison.passed is False
    failed_checks = {check.name for check in comparison.checks if not check.passed}
    assert "average_tokens_within_threshold" in failed_checks
    assert "scenario:success-readonly:tokens_within_threshold" in failed_checks


def test_render_ci_markdown_summary_includes_scenarios_and_comparison() -> None:
    comparison = compare_validation_report_to_baseline(
        _report_payload(tokens=110),
        _baseline_payload(tokens=100),
        max_token_regression_pct=0.2,
        report_path="report.json",
        baseline_path="baseline.json",
    )

    summary = render_ci_markdown_summary(
        _report_payload(tokens=110),
        comparison=comparison,
        cli_exit_code=0,
        compare_baseline_path="baseline.json",
    )

    assert "# Langfuse Validation Summary" in summary
    assert "| success-readonly | success | success | yes | 110 | 2 | [trace](https://example.com/trace-1) |" in summary
    assert "`scenario:success-readonly:status_matches`" in summary
    assert "`baseline.json`" in summary


def test_json_and_text_file_helpers_round_trip() -> None:
    with tempfile.TemporaryDirectory(dir=".") as tmp_dir:
        base = Path(tmp_dir)
        payload = {"hello": "world"}
        json_path = write_json_file(base / "out" / "payload.json", payload)
        text_path = write_text_file(base / "out" / "summary.md", "# Demo\n")

        assert load_json_file(json_path) == payload
        assert text_path.read_text(encoding="utf-8") == "# Demo\n"
        assert json.loads(json_path.read_text(encoding="utf-8")) == payload
