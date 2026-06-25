from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from agent.task import RunResult, Task
from llm.base import LLMMessage, LLMResponse, LLMToolSchema
from tools.base import ToolResult

from observability.masking import truncate_text


def build_task_input(task: Task) -> dict[str, Any]:
    return {
        "description": task.description,
        "repo_path": task.repo_path,
        "intent": task.intent,
        "issue_url": task.issue_url,
    }


def build_task_metadata(task: Task) -> dict[str, Any]:
    metadata = {
        "task_id": task.task_id,
        "intent": task.intent,
        "repo_path": task.repo_path,
        "max_steps": task.max_steps,
        "budget_tokens": task.budget_tokens,
        "has_issue_url": bool(task.issue_url),
        "entrypoint": task.metadata.get("entrypoint"),
        "mode": task.metadata.get("mode"),
        "phase": task.metadata.get("phase"),
        "session_id": task.metadata.get("session_id"),
        "parent_task_id": task.metadata.get("parent_task_id"),
        "subtask_id": task.metadata.get("subtask_id"),
        "subtask_type": task.metadata.get("subtask_type"),
        "role": task.metadata.get("role"),
        "agent_id": task.metadata.get("agent_id"),
        "coordinator_task_id": task.metadata.get("coordinator_task_id"),
        "isolation": task.metadata.get("isolation"),
        "depends_on": task.metadata.get("depends_on"),
        "spawn_index": task.metadata.get("spawn_index"),
        "round": task.metadata.get("round"),
        "provider": task.metadata.get("provider"),
        "model": task.metadata.get("model"),
    }
    metadata.update(task.metadata)
    return {k: v for k, v in metadata.items() if v is not None}


def build_run_output(result: RunResult) -> dict[str, Any]:
    return {
        "status": result.status.value,
        "summary": truncate_text(result.summary or "", max_length=2_000),
        "steps_taken": result.steps_taken,
        "total_tokens": result.total_tokens,
        "has_patch": bool(result.patch),
    }


def build_run_metadata(result: RunResult) -> dict[str, Any]:
    metadata = {
        "status": result.status.value,
        "steps_taken": result.steps_taken,
        "total_tokens": result.total_tokens,
        "has_patch": bool(result.patch),
        "patch_length": len(result.patch or ""),
        "error": result.error,
    }
    if result.cache_stats is not None:
        metadata["cache_stats"] = dataclass_to_dict(result.cache_stats)
    return {k: v for k, v in metadata.items() if v is not None}


def build_analysis_run_metadata(
    *,
    run_stats: dict[str, Any] | None = None,
    context_stats: Any = None,
) -> dict[str, Any]:
    run_stats = run_stats or {}
    metadata: dict[str, Any] = {
        "tool_decisions": run_stats.get("tool_decisions"),
        "recovery_actions": run_stats.get("recovery_actions"),
        "claims_created": run_stats.get("claims_created"),
        "analysis_deferred_reads": run_stats.get("analysis_deferred_reads"),
        "phase_starts": run_stats.get("phase_starts"),
        "phase_ends": run_stats.get("phase_ends"),
        "analysis_phase_token_costs": run_stats.get("analysis_phase_token_costs"),
        "analysis_phase_llm_calls": run_stats.get("analysis_phase_llm_calls"),
    }
    if context_stats is not None:
        metadata.update({
            "analysis_phase": getattr(context_stats, "analysis_phase", ""),
            "analysis_files_read": getattr(context_stats, "analysis_files_read", 0),
            "analysis_inspect_reads": getattr(context_stats, "analysis_inspect_reads", 0),
            "analysis_verify_reads": getattr(context_stats, "analysis_verify_reads", 0),
            "analysis_evidence_records": getattr(context_stats, "analysis_evidence_records", 0),
            "analysis_phase_summaries": getattr(context_stats, "analysis_phase_summaries", 0),
            "analysis_claims": getattr(context_stats, "analysis_claims", 0),
            "analysis_tool_decisions": getattr(context_stats, "analysis_tool_decisions", 0),
            "analysis_recovery_actions": getattr(context_stats, "analysis_recovery_actions", 0),
            "analysis_deferred_reads_context": getattr(context_stats, "analysis_deferred_reads", 0),
            "analysis_phase_token_costs_context": getattr(context_stats, "analysis_phase_token_costs", {}),
        })
    return {k: v for k, v in metadata.items() if v not in (None, "", [])}


def summarize_messages(
    messages: list[LLMMessage],
    *,
    capture_prompts: bool,
) -> list[dict[str, Any]]:
    summarized: list[dict[str, Any]] = []
    for message in messages[-12:]:
        item: dict[str, Any] = {"role": message.role}
        if capture_prompts:
            item["content"] = summarize_content(message.content)
        if message.tool_call_id:
            item["tool_call_id"] = message.tool_call_id
        if message.tool_calls:
            item["tool_calls"] = [tool_call.to_dict() for tool_call in message.tool_calls]
        summarized.append(item)
    return summarized


def summarize_tools(tools: list[LLMToolSchema]) -> list[dict[str, Any]]:
    return [
        {
            "name": tool.name,
            "description": truncate_text(tool.description, max_length=300),
        }
        for tool in tools[:30]
    ]


def build_generation_input(
    messages: list[LLMMessage],
    tools: list[LLMToolSchema],
    *,
    capture_prompts: bool,
) -> dict[str, Any]:
    return {
        "message_count": len(messages),
        "messages": summarize_messages(messages, capture_prompts=capture_prompts),
        "tools": summarize_tools(tools),
    }


def build_generation_output(
    response: LLMResponse,
    *,
    capture_llm_outputs: bool,
) -> dict[str, Any]:
    output = {
        "action_type": response.action.action_type.value,
        "message": response.action.message,
        "tool_calls": [tool_call.to_dict() for tool_call in response.action.tool_calls],
    }
    if capture_llm_outputs:
        output["raw_content"] = response.raw_content
        output["thought"] = response.action.thought
    return output


def build_generation_metadata(
    response: LLMResponse,
    *,
    attempt: int,
    provider: str | None,
    model: str,
) -> dict[str, Any]:
    return {
        "attempt": attempt,
        "provider": provider,
        "model": model,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "total_tokens": response.total_tokens,
        "cache_stats": dataclass_to_dict(response.cache_stats),
    }


def build_tool_input(name: str, params: dict[str, Any], thought: str, step: int) -> dict[str, Any]:
    return {
        "tool_name": name,
        "params": params,
        "thought": thought,
        "step": step,
    }


def build_tool_output(
    result: ToolResult,
    *,
    capture_tool_outputs: bool,
) -> dict[str, Any]:
    output = {
        "success": result.success,
        "duration_ms": result.duration_ms,
        "error": result.error,
    }
    if capture_tool_outputs:
        output["output"] = result.output
    return output


def merge_metadata(*parts: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for part in parts:
        if not part:
            continue
        merged.update({k: v for k, v in part.items() if v is not None})
    return merged


def dataclass_to_dict(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    return value


def summarize_content(content: str | list[dict[str, Any]]) -> Any:
    if isinstance(content, str):
        return truncate_text(content, max_length=1_500)
    return content[:10]
