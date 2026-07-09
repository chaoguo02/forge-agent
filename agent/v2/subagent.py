"""Fork subagent — Claude Code style child agent with fresh context."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from agent.core import AgentConfig, ReActAgent
from agent.event_log import EventLog
from agent.policy import PhasePolicy
from agent.policy_registry import PolicyAwareToolRegistry
from agent.task import RunResult, RunStatus, Task
from agent.v2.models import AgentDefinition, ForkResult
from context.history import ConversationHistory
from llm.base import LLMBackend, LLMMessage
from tools.base import ToolRegistry

logger = logging.getLogger(__name__)

_SUBAGENT_SUMMARY_RULE = (
    "Your final answer is returned to the parent as a tool result. "
    "The parent only sees your final message — not your full reasoning or tool history. "
    "Make your final summary standalone and directly useful."
)


@dataclass
class _ForkContext:
    """Internal context for a fork subagent run."""
    agent_id: str
    definition: AgentDefinition
    prompt: str
    repo_path: str
    log_dir: str
    tool_registry: ToolRegistry
    backend: LLMBackend
    hook_dispatcher: Any = None


def fork_subagent(
    *,
    definition: AgentDefinition,
    prompt: str,
    repo_path: str,
    base_registry: ToolRegistry,
    backend: LLMBackend,
    log_dir: str,
    root_agent_config: AgentConfig | None = None,
    hook_dispatcher: Any = None,
) -> ForkResult:
    """Run a subagent in a forked context.

    The subagent gets:
    - A fresh conversation context (no parent history)
    - Tools restricted to its definition's allowlist
    - Its own system prompt (from the agent definition's body)
    - The prompt as the first user message

    Returns a ForkResult with the subagent's final summary.
    """
    agent_id = uuid.uuid4().hex[:12]
    logger.info("Fork subagent '%s' (%s) starting: %s", definition.name, agent_id, prompt[:80])

    # Build restricted tool registry for this subagent
    from agent.v2.agent_registry import AgentRegistryV2
    registry_v2 = AgentRegistryV2()
    allowed_tools = registry_v2.tool_names_for(definition.name)

    restricted_registry = base_registry.filtered(allowed_tools)

    # Phase-policy wrap
    wrapped_registry = PolicyAwareToolRegistry(
        base=restricted_registry,
        phase_policy=PhasePolicy(allowed_tools=frozenset(restricted_registry.tool_names)),
        repo_path=repo_path,
        phase_name=f"fork-{definition.name}",
    )

    # Build agent config
    if root_agent_config is not None:
        from copy import copy
        cfg = copy(root_agent_config)
    else:
        cfg = AgentConfig()

    cfg.max_steps = definition.max_turns
    cfg.stream = False
    cfg.stream_callback = None
    cfg.thought_callback = None
    cfg.compact_history = False

    # Build agent
    agent = ReActAgent(backend, wrapped_registry, cfg)

    # Fresh context — no parent history
    history = ConversationHistory(max_messages=cfg.history_max_messages)

    # System prompt from agent definition (the body after frontmatter)
    system_messages = _build_system_messages(definition)
    history.add_many(system_messages)

    # User prompt
    history.add(LLMMessage(role="user", content=prompt))

    agent._pending_history = history

    # Fire SubagentStart hook
    _fire_hook(hook_dispatcher, "SubagentStart", session_id=agent_id)

    # Run
    task = Task(
        description=prompt,
        repo_path=repo_path,
        intent="analysis",
        max_steps=cfg.max_steps,
        budget_tokens=cfg.budget_tokens,
        metadata={
            "entrypoint": "fork",
            "agent_name": definition.name,
            "agent_id": agent_id,
            "isolation": definition.isolation,
        },
    )

    try:
        with EventLog.create(task, log_dir=log_dir) as event_log:
            result = agent.run(task, event_log)
    finally:
        _fire_hook(hook_dispatcher, "SubagentStop", session_id=agent_id)

    return _build_fork_result(definition.name, agent_id, result)


def _build_system_messages(definition: AgentDefinition) -> list[LLMMessage]:
    messages: list[LLMMessage] = []

    # Agent-specific system prompt (from .md body)
    if definition.system_prompt:
        messages.append(LLMMessage(
            role="system",
            content=definition.system_prompt,
        ))

    # Universal subagent rules
    messages.append(LLMMessage(
        role="user",
        content=(
            f"[Subagent: {definition.name}]\n"
            f"{_SUBAGENT_SUMMARY_RULE}"
        ),
    ))

    return messages


def _build_fork_result(agent_name: str, agent_id: str, result: RunResult) -> ForkResult:
    status = "completed"
    if result.status == RunStatus.MAX_STEPS:
        status = "partial"
    elif not result.is_success():
        status = "failed"

    summary = (result.summary or "").strip()
    if not summary:
        summary = "Subagent finished without a summary."

    return ForkResult(
        agent_name=agent_name,
        session_id=agent_id,
        status=status,
        summary=summary,
        error=result.error or "",
        turns_used=result.steps_taken,
    )


def _fire_hook(dispatcher: Any, event_name: str, session_id: str = "") -> None:
    if dispatcher is None:
        return
    try:
        from hooks.events import HookContext, HookEvent
        evt = HookEvent(event_name)
        ctx = HookContext(event=evt, session_id=session_id)
        dispatcher.dispatch(evt, ctx)
    except Exception:
        logger.debug("Hook %s failed for session %s", event_name, session_id, exc_info=True)
