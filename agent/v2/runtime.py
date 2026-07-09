"""V2 Session Runtime — fork-based multi-agent orchestration."""

from __future__ import annotations

import copy
import logging
from pathlib import Path

from agent.core import AgentConfig, ReActAgent
from agent.event_log import EventLog
from agent.policy import PhasePolicy
from agent.task import RunResult, RunStatus, Task
from agent.v2.agent_registry import AgentRegistryV2
from agent.v2.models import AgentDefinition, ForkResult
from agent.policy_registry import PolicyAwareToolRegistry
from agent.v2.session_store import SessionStore
from agent.v2.subagent import fork_subagent
from agent.v2.task_tool import AgentTool
from context.history import ConversationHistory
from llm.base import LLMBackend, LLMMessage
from tools.base import ToolRegistry

logger = logging.getLogger(__name__)


class SessionRuntime:
    """V2 session runtime with fork-based subagent orchestration.

    Coordinator agents (build, plan) carry the `task` tool and can
    dispatch fork subagents.  Each fork runs in a fresh context with
    tools restricted to its agent definition allow-list.
    """

    def __init__(
        self,
        *,
        store: SessionStore,
        backend: LLMBackend,
        base_registry: ToolRegistry,
        agent_registry: AgentRegistryV2,
        root_agent_config: AgentConfig,
        log_dir: str,
        memory_context=None,
        hook_dispatcher=None,
        mcp_integration=None,
    ) -> None:
        self._store = store
        self._backend = backend
        self._base_registry = base_registry
        self._agent_registry = agent_registry
        self._root_agent_config = root_agent_config
        self._log_dir = log_dir
        self._memory_context = memory_context
        self._hook_dispatcher = hook_dispatcher
        self._mcp_integration = mcp_integration

    @property
    def agent_registry(self) -> AgentRegistryV2:
        return self._agent_registry

    # ── Root session ──

    def create_root_session(
        self,
        *,
        agent_name: str,
        repo_path: str,
        title: str,
        metadata: dict | None = None,
    ):
        spec = self._agent_registry.get(agent_name)
        return self._store.create_session(
            agent_name=agent_name,
            mode="primary",
            repo_path=repo_path,
            title=title,
            metadata=metadata or {},
        )

    def run_session(
        self,
        session_id: str,
        *,
        agent_name: str,
        task_description: str,
        intent: str,
        messages: list[LLMMessage] | None = None,
        max_steps_override: int | None = None,
        budget_tokens_override: int | None = None,
    ) -> RunResult:
        session = self._store.get_session(session_id)
        if session is None:
            raise ValueError(f"Unknown v2 session: {session_id}")

        spec = self._agent_registry.get(agent_name)
        registry = self._build_registry_for_session(spec, session)
        agent_cfg = self._build_agent_config(spec)

        agent = ReActAgent(
            self._backend,
            registry,
            agent_cfg,
            memory_context=self._memory_context if spec.mode == "primary" else None,
        )

        persisted_messages = self._store.list_messages(session_id)
        if messages:
            for message in messages:
                self._store.append_message(session_id, message)
            persisted_messages = self._store.list_messages(session_id)
        elif not persisted_messages:
            self._store.append_message(session_id, LLMMessage(role="user", content=task_description))
            persisted_messages = self._store.list_messages(session_id)

        history = ConversationHistory(max_messages=agent_cfg.history_max_messages)
        injected_messages = self._build_runtime_messages(spec, task_description)
        history.add_many(injected_messages + persisted_messages)
        agent._pending_history = history

        task = Task(
            description=task_description,
            repo_path=session.repo_path,
            intent=intent,
            max_steps=max_steps_override or agent_cfg.max_steps,
            budget_tokens=budget_tokens_override or agent_cfg.budget_tokens,
            metadata={
                "entrypoint": "v2",
                "mode": f"v2-{agent_name}",
                "session_id": session_id,
                "parent_session_id": session.parent_id,
                "root_session_id": session.root_id,
                "agent_name": agent_name,
                "v2_bypass_path_scope_policy": True,
                "v2_disable_legacy_analysis_prompting": True,
            },
        )

        self._store.update_status(session_id, "running")
        self._fire_hook("SessionStart", session_id=session_id)

        initial_count = len(persisted_messages)
        with EventLog.create(task, log_dir=self._log_dir) as log:
            result = agent.run(task, log)

        for message in history.to_list()[initial_count:]:
            self._store.append_message(session_id, message)

        if result.is_success():
            self._store.set_summary(session_id, result.summary, status="completed")
        else:
            self._store.update_status(session_id, "failed", error=result.error or result.summary)
            self._store.set_summary(session_id, result.summary, status="failed")

        self._fire_hook("Stop", session_id=session_id)
        return result

    # ── Fork subagent ──

    def fork_session(
        self,
        *,
        definition: AgentDefinition,
        description: str,
        prompt: str,
    ) -> ForkResult:
        """Dispatch a fork subagent.

        The subagent runs in a fresh context — no parent history inherited.
        Tools are restricted to the agent definition's allow-list.
        Only the final summary is returned to the caller.
        """
        return fork_subagent(
            definition=definition,
            prompt=prompt,
            repo_path=".",
            base_registry=self._base_registry,
            backend=self._backend,
            log_dir=self._log_dir,
            root_agent_config=self._root_agent_config,
            hook_dispatcher=self._hook_dispatcher,
        )

    # ── Internal helpers ──

    def _fire_hook(self, event_name: str, session_id: str = "") -> None:
        if self._hook_dispatcher is None:
            return
        from hooks.events import HookContext, HookEvent
        try:
            evt = HookEvent(event_name)
            ctx = HookContext(event=evt, session_id=session_id)
            self._hook_dispatcher.dispatch(evt, ctx)
        except Exception:
            pass

    def _build_registry_for_session(self, spec: AgentDefinition, session) -> ToolRegistry:
        is_plan = spec.name == "plan"
        mcp_tool_names = self._mcp_tool_names_for_spec(spec)

        if is_plan:
            from agent.v2.agent_registry import _BUILD_ALLOWED, _PLAN_ALLOWED
            registry = self._base_registry.filtered(_BUILD_ALLOWED | mcp_tool_names)
            plan_mode_allowed = _PLAN_ALLOWED
        else:
            from agent.v2.agent_registry import _BUILD_ALLOWED
            registry = self._base_registry.filtered(_BUILD_ALLOWED | mcp_tool_names)
            plan_mode_allowed = None

        # Coordinator agents get the task tool
        if spec.name in ("build", "plan"):
            registry.register(AgentTool(self, session.id))

        wrapped = PolicyAwareToolRegistry(
            base=registry,
            phase_policy=PhasePolicy(allowed_tools=frozenset(registry.tool_names)),
            repo_path=session.repo_path,
            phase_name="v2_execution",
            plan_mode_allowed=plan_mode_allowed,
        )
        return wrapped

    def _mcp_tool_names_for_spec(self, spec: AgentDefinition) -> frozenset[str]:
        if self._mcp_integration is None:
            return frozenset()
        if spec.name not in {"build", "general"}:
            return frozenset()
        return getattr(self._mcp_integration, "tool_names", frozenset())

    def _build_agent_config(self, spec: AgentDefinition) -> AgentConfig:
        cfg = copy.copy(self._root_agent_config)
        if spec.mode != "primary":
            cfg.max_steps = min(cfg.max_steps, spec.max_turns)
            cfg.compact_history = False
            cfg.stream = False
            cfg.stream_callback = None
            cfg.thought_callback = None
        return cfg

    def _build_runtime_messages(self, spec: AgentDefinition, task_description: str) -> list[LLMMessage]:
        if spec.mode != "primary":
            return []
        messages: list[LLMMessage] = []

        if spec.name == "plan":
            from agent.prompt import get_plan_mode_injection
            messages.append(LLMMessage(role="user", content=get_plan_mode_injection()))

        subagent_descriptions = "\n".join(
            f"- **{s.name}**: {s.description}" for s in self._agent_registry.list_subagents()
        )
        content = (
            "[Available Subagents]\n"
            "You have a `task` tool to delegate subtasks to isolated fork subagents.\n"
            f"Available subagent types:\n{subagent_descriptions}\n\n"
            "Fork delegation rules:\n"
            "- Each fork subagent runs in a FRESH context — it sees NONE of your conversation history.\n"
            "- Put ALL necessary context in the prompt: constraints, key facts, file paths, expected output.\n"
            "- The subagent's final message is its ONLY return value to you.\n"
            "- Use subagents for independent, clearly-scoped work.\n"
            "- Do simple tasks directly without delegating.\n"
            "- Never hand off understanding — you can delegate execution, not comprehension.\n"
            "- When the user explicitly asks to use the task tool or delegate, call it instead of answering directly."
        )
        messages.append(LLMMessage(role="user", content=content))
        return messages


def default_session_db_path(repo_path: str) -> str:
    return str(Path(repo_path) / ".forge-agent" / "v2" / "sessions.db")


def memory_freshness_text(name: str, store) -> str:
    """Return a freshness warning for a memory file based on mtime.

    Returns '' for fresh files (<=1 day), relative age warning for older.
    """
    import os as _os
    from datetime import datetime as _datetime

    try:
        path = store._file_path(name)
        if not path.exists():
            return ""
        mtime = _datetime.fromtimestamp(_os.path.getmtime(path))
        age_days = (_datetime.now() - mtime).days
        if age_days <= 1:
            return ""
        return f"{age_days} days ago — verify against current code"
    except Exception:
        return ""
