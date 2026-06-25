"""Completion validation based on EventLog facts."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import TYPE_CHECKING

from agent.event_log import EventLog
from agent.policy import READ_TOOLS, WRITE_TOOLS, TaskPolicy, normalize_repo_path
from agent.task import EventType

if TYPE_CHECKING:
    from agent.task import Task
    from context.evidence import EvidenceLedger


@dataclass(frozen=True)
class CompletionVerdict:
    success: bool
    reason: str = ""
    reason_code: str = ""
    retryable: bool = False


class CompletionValidator:
    """Validate task completion from logged tool calls, not assistant prose."""

    def validate(
        self,
        log: EventLog,
        policy: TaskPolicy,
        repo_path: str,
        *,
        task: "Task | None" = None,
        evidence_ledger: "EvidenceLedger | None" = None,
        final_summary: str = "",
    ) -> CompletionVerdict:
        try:
            events = log.replay()
        except Exception as exc:
            return CompletionVerdict(False, f"Could not validate completion from event log: {exc}")

        read_paths: set[str] = set()
        write_paths: set[str] = set()
        saw_write = False

        observations_by_step: dict[int, dict[str, bool]] = {}
        for event in events:
            if event.event_type != EventType.OBSERVATION:
                continue
            observation = event.payload.get("observation", {})
            observations_by_step.setdefault(event.payload.get("step", 0), {})[observation.get("tool_name", "")] = observation.get("status") == "success"

        for event in events:
            if event.event_type != EventType.ACTION:
                continue
            action = event.payload.get("action", {})
            for tool_call in action.get("tool_calls") or []:
                name = tool_call.get("name", "")
                params = tool_call.get("params", {}) or {}
                path = normalize_repo_path(str(params.get("path", "")), repo_path)

                call_succeeded = observations_by_step.get(event.payload.get("step", 0), {}).get(name, True)

                if name in policy.completion.forbidden_tools and call_succeeded:
                    return CompletionVerdict(False, f"Forbidden tool '{name}' was used during execution.")

                if name in READ_TOOLS:
                    if call_succeeded and policy.execution.strict_file_scope and not self._path_allowed(path, policy.execution.allowed_read_paths):
                        return CompletionVerdict(False, f"Read outside allowed paths: {path}")
                    if call_succeeded:
                        read_paths.add(path)
                elif name in WRITE_TOOLS or name in {"file_edit", "edit_file", "edit"}:
                    if call_succeeded:
                        saw_write = True
                    if call_succeeded and policy.execution.strict_file_scope and not self._path_allowed(path, policy.execution.allowed_write_paths):
                        return CompletionVerdict(False, f"Write outside allowed paths: {path}")
                    if call_succeeded:
                        write_paths.add(path)

        if policy.completion.require_any_read and not read_paths:
            return CompletionVerdict(False, "Approved analysis plan finished without reading any file.")

        missing_reads = sorted(path for path in policy.completion.required_reads if path not in read_paths)
        if missing_reads:
            return CompletionVerdict(False, f"Approved analysis plan finished without reading required source file: {', '.join(missing_reads)}")

        missing_writes = sorted(path for path in policy.completion.required_writes if path not in write_paths)
        if missing_writes:
            return CompletionVerdict(False, f"Approved edit plan finished without writing required file: {', '.join(missing_writes)}")

        if policy.completion.require_any_write and not saw_write:
            return CompletionVerdict(False, "Approved edit plan finished without performing any file write.")

        if task is not None and task.intent == "analysis":
            grounding = self._validate_analysis_answer_grounding(
                final_summary=final_summary,
                evidence_ledger=evidence_ledger,
                task=task,
            )
            if not grounding.success:
                return grounding

        return CompletionVerdict(True)

    def _path_allowed(self, path: str, allowed_paths: frozenset[str] | None) -> bool:
        if allowed_paths is None:
            return True
        return path in allowed_paths

    def _validate_analysis_answer_grounding(
        self,
        *,
        final_summary: str,
        evidence_ledger: "EvidenceLedger | None",
        task: "Task",
    ) -> CompletionVerdict:
        shape = getattr(task, "shape", None)
        if shape is None or shape.kind != "broad_analysis":
            return CompletionVerdict(True)
        if evidence_ledger is None or evidence_ledger.evidence_count == 0:
            return CompletionVerdict(True)

        text = (final_summary or "").strip()
        if not text:
            return CompletionVerdict(
                False,
                "Broad analysis finished without a final grounded answer.",
                reason_code="analysis_answer_grounding_failed",
                retryable=True,
            )

        known_evidence_ids = evidence_ledger.known_evidence_ids()
        cited_ids = set(re.findall(r"\[(ev_[A-Za-z0-9]+)\]", text))
        unknown_ids = sorted(cited_ids - known_evidence_ids)
        if unknown_ids:
            return CompletionVerdict(
                False,
                f"Final analysis answer cited unknown evidence ids: {', '.join(unknown_ids)}",
                reason_code="analysis_answer_grounding_failed",
                retryable=True,
            )
        if not cited_ids:
            return CompletionVerdict(
                False,
                "Final broad-analysis answer must cite at least one recorded evidence id such as [ev_xxx].",
                reason_code="analysis_answer_grounding_failed",
                retryable=True,
            )

        confirmed_lines = self._collect_confirmed_lines(text)
        if confirmed_lines:
            ungrounded = [line for line in confirmed_lines if not re.search(r"\[ev_[A-Za-z0-9]+\]", line)]
            if ungrounded:
                return CompletionVerdict(
                    False,
                    "Confirmed analysis claims must cite recorded evidence ids like [ev_xxx].",
                    reason_code="analysis_answer_grounding_failed",
                    retryable=True,
                )

        return CompletionVerdict(True)

    def _collect_confirmed_lines(self, text: str) -> list[str]:
        lines = [line.rstrip() for line in text.splitlines()]
        confirmed: list[str] = []
        in_confirmed = False
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if in_confirmed:
                    break
                continue
            if stripped.startswith("#"):
                title = stripped.lstrip("#").strip().lower()
                in_confirmed = title.startswith("confirmed") or title.startswith("findings")
                continue
            if in_confirmed and (stripped.startswith("-") or re.match(r"^\d+\.\s", stripped)):
                confirmed.append(stripped)
            elif in_confirmed and not stripped.startswith("-"):
                break
        return confirmed
