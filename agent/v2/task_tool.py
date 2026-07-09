"""AgentTool — spawn a fork subagent to handle a delegated subtask."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from agent.v2.runtime import SessionRuntime

logger = logging.getLogger(__name__)


class AgentTool(BaseTool):
    """Dispatch a fork subagent. Claude Code `task` tool equivalent.

    The subagent runs in a fresh context (Fork model):
    - No parent conversation history.
    - Tools restricted to the agent definition's allowlist.
    - Its final message is the return value.

    Usage:
        AgentTool(runtime, parent_session_id)
    """

    def __init__(self, runtime: "SessionRuntime", parent_session_id: str) -> None:
        self._runtime = runtime
        self._parent_session_id = parent_session_id

    # ── BaseTool interface ──

    @property
    def name(self) -> str:
        return "task"

    @property
    def description(self) -> str:
        registry = self._runtime.agent_registry
        subagents = [
            f"- {spec.name}: {spec.description}"
            for spec in registry.list_subagents()
        ]
        lines = [
            "Launch a subagent to handle a complex, multi-step task autonomously.",
            "The subagent runs in an isolated context and returns one final message.",
            "",
            "Available subagent types:",
            *subagents,
            "",
            "Guidelines:",
            "- Put ALL necessary context in the prompt — the subagent has no access to this conversation.",
            "- The subagent's final summary is the only thing returned to you.",
            "- Use for independent, clearly-scoped work. Do simple tasks directly.",
            "- Never hand off understanding — you can delegate execution, not comprehension.",
        ]
        return "\n".join(lines)

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "subagent_type": {
                    "type": "string",
                    "description": "The type of subagent to spawn (e.g. 'explore', 'general', 'code-reviewer')",
                },
                "description": {
                    "type": "string",
                    "description": "A short (3-5 word) description of the task",
                },
                "prompt": {
                    "type": "string",
                    "description": "The full task for the subagent. Include ALL context, constraints, and expected output format.",
                },
            },
            "required": ["subagent_type", "description", "prompt"],
        }

    # ── Execution ──

    def execute(self, params: dict[str, Any]) -> ToolResult:
        subagent_type = str(params.get("subagent_type", "")).strip()
        description = str(params.get("description", "")).strip()
        prompt = str(params.get("prompt", "")).strip()

        # Validate
        if not subagent_type or not prompt:
            return ToolResult(
                success=False, output="",
                error="task requires subagent_type, description, and prompt",
            )
        if not self._runtime.agent_registry.has(subagent_type):
            return ToolResult(
                success=False, output="",
                error=f"Unknown subagent_type: {subagent_type!r}. "
                      f"Available: {[s.name for s in self._runtime.agent_registry.list_subagents()]}",
            )

        definition = self._runtime.agent_registry.get(subagent_type)

        logger.info(
            "Dispatching subagent '%s' for task: %s",
            subagent_type, description,
        )

        try:
            fork_result = self._runtime.fork_session(
                definition=definition,
                description=description,
                prompt=prompt,
            )
        except Exception as exc:
            logger.exception("Fork subagent '%s' crashed", subagent_type)
            return ToolResult(
                success=False, output="",
                error=f"Subagent '{subagent_type}' failed: {exc}",
            )

        # Build XML-format result (Claude Code <task-notification> style)
        output = _format_fork_result(subagent_type, fork_result)

        is_failure = fork_result.status == "failed" and bool(fork_result.error)
        return ToolResult(
            success=not is_failure,
            output=output,
            error=fork_result.error if is_failure else "",
            duration_ms=0.0,
        )


def _format_fork_result(agent_type: str, result: Any) -> str:
    """Format ForkResult as an XML <task-notification> block."""
    lines = [
        "<task-notification>",
        f"  <agent-type>{agent_type}</agent-type>",
        f"  <session-id>{result.session_id}</session-id>",
        f"  <status>{result.status}</status>",
        f"  <turns-used>{result.turns_used}</turns-used>",
    ]
    if result.error:
        lines.append(f"  <error>{_xml_escape(result.error)}</error>")
    lines.extend([
        "  <summary>",
        result.summary.strip(),
        "  </summary>",
        "</task-notification>",
    ])
    return "\n".join(lines)


def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
