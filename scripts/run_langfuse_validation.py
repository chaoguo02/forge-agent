from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from observability.ci import (
    compare_validation_report_to_baseline,
    load_json_file,
    render_ci_markdown_summary,
    write_json_file,
    write_text_file,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Langfuse validation and prepare CI-friendly artifacts.")
    parser.add_argument("--repo", default=".", help="Repository path to validate")
    parser.add_argument("--scenario", default="both", help="Validation scenario selection")
    parser.add_argument("--baseline-name", default=None, help="Optional baseline snapshot name to generate")
    parser.add_argument("--baseline-out", default=None, help="Optional path for the generated baseline JSON")
    parser.add_argument("--report-out", default=None, help="Optional path for the validation report JSON")
    parser.add_argument("--summary-out", default=None, help="Optional path for the markdown summary")
    parser.add_argument("--comparison-out", default=None, help="Optional path for the baseline comparison JSON")
    parser.add_argument("--compare-baseline", default=None, help="Optional baseline JSON path used for regression comparison")
    parser.add_argument(
        "--max-token-regression-pct",
        type=float,
        default=0.2,
        help="Allowed token growth ratio when comparing to a baseline (0.2 = 20%%)",
    )
    parser.add_argument(
        "--require-baseline",
        action="store_true",
        help="Fail if --compare-baseline is missing or does not exist",
    )
    args = parser.parse_args()

    repo_path = Path(args.repo).resolve()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = repo_path / ".forge-agent" / "ci" / "langfuse" / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)

    report_out = Path(args.report_out) if args.report_out else output_dir / "validation-report.json"
    summary_out = Path(args.summary_out) if args.summary_out else output_dir / "summary.md"
    comparison_out = Path(args.comparison_out) if args.comparison_out else output_dir / "comparison.json"
    baseline_out = (
        Path(args.baseline_out)
        if args.baseline_out
        else (output_dir / "baseline.json" if args.baseline_name else None)
    )
    stdout_log = output_dir / "stdout.log"
    stderr_log = output_dir / "stderr.log"

    command = [
        sys.executable,
        "-m",
        "entry.cli",
        "langfuse-validate",
        "--repo",
        str(repo_path),
        "--scenario",
        args.scenario,
        "--json-out",
        str(report_out),
    ]
    if args.baseline_name:
        command.extend(["--baseline-name", args.baseline_name])
        if baseline_out:
            command.extend(["--baseline-out", str(baseline_out)])

    completed = subprocess.run(
        command,
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    write_text_file(stdout_log, completed.stdout)
    write_text_file(stderr_log, completed.stderr)

    report_payload = load_json_file(report_out) if report_out.exists() else None
    comparison = None
    comparison_baseline_path = args.compare_baseline
    comparison_error: str | None = None
    if args.compare_baseline:
        baseline_path = Path(args.compare_baseline)
        if not baseline_path.is_absolute():
            baseline_path = repo_path / baseline_path
        if baseline_path.exists():
            baseline_payload = load_json_file(baseline_path)
            if report_payload is not None:
                comparison = compare_validation_report_to_baseline(
                    report_payload,
                    baseline_payload,
                    max_token_regression_pct=args.max_token_regression_pct,
                    report_path=str(report_out),
                    baseline_path=str(baseline_path),
                )
                write_json_file(comparison_out, comparison.to_dict())
        else:
            comparison_error = f"Baseline file not found: {baseline_path}"
    elif args.require_baseline:
        comparison_error = "--require-baseline was set but --compare-baseline was not provided"

    if comparison_error is not None:
        comparison_payload = {
            "report_path": str(report_out),
            "baseline_path": comparison_baseline_path,
            "passed": False,
            "checks": [
                {
                    "name": "baseline_available",
                    "passed": False,
                    "details": comparison_error,
                }
            ],
            "metadata": {
                "error": comparison_error,
            },
        }
        write_json_file(comparison_out, comparison_payload)

    summary_text = render_ci_markdown_summary(
        report_payload,
        comparison=comparison,
        cli_exit_code=completed.returncode,
        compare_baseline_path=comparison_baseline_path,
    )
    if comparison_error is not None:
        summary_text += f"\n> Baseline comparison error: {comparison_error}\n"
    write_text_file(summary_out, summary_text)

    github_step_summary = os.getenv("GITHUB_STEP_SUMMARY")
    if github_step_summary:
        Path(github_step_summary).write_text(summary_text, encoding="utf-8")

    print(f"Validation report: {report_out}")
    if baseline_out:
        print(f"Generated baseline: {baseline_out}")
    print(f"Summary: {summary_out}")
    print(f"Stdout log: {stdout_log}")
    print(f"Stderr log: {stderr_log}")
    if comparison_out.exists():
        print(f"Comparison: {comparison_out}")

    if completed.returncode != 0:
        return completed.returncode
    if comparison_error is not None:
        return 1
    if comparison is not None and not comparison.passed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
