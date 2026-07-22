"""
server/services/chat_pipeline.py

ChatPipeline — 6-stage orchestrator for a single chat execution.

Extracted from ``_run_and_notify()`` nested function in AgentService (P1-10).
Each stage is a pure method that reads/writes a ``ChatExecutionContext``,
making the pipeline independently testable.

Usage::

    pipeline = ChatPipeline(service)
    ctx = ChatExecutionContext(session_id="abc", prompt="fix the bug", ...)
    pipeline.resolve_mentions(ctx)
    backend = pipeline.apply_model_switch(ctx)
    pipeline.inject_session_context(ctx)
    pipeline.build_callbacks(ctx)
    pipeline.execute(ctx, backend)
    pipeline.finish(ctx, result)
"""

from __future__ import annotations

import logging
import os
import re as _re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from agent.task import RunResult, TaskIntent

if TYPE_CHECKING:
    from agent.session.runtime import SessionRuntime
    from llm.base import LLMBackend
    from server.services.agent_service import AgentService
    from server.services.event_bus import EventBus

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

# Sensitive paths that must NOT be resolved via @mention expansion
_DENY_PREFIXES: tuple[str, ...] = (
    ".git/", ".git", ".forge-agent/", ".grace/",
    ".claude/", ".env", "settings.json", "secrets",
)

_AT_RE = _re.compile(r"(?:^|\s)@(\S+)")
_MENTION_MAX_CHARS: int = 5000


# ── ChatExecutionContext ─────────────────────────────────────────────────────


@dataclass
class ChatExecutionContext:
    """Immutable per-chat-run data.  Built once, passed through each stage."""

    session_id: str
    prompt: str
    agent_name: str = "build"
    intent: TaskIntent | None = None
    permission_mode: str = "acceptEdits"
    repo_path: str = "."

    # ── Resolved by the pipeline (not for caller to set) ──
    resolved_prompt: str = ""
    injected_session_context: bool = False
    confirm_callback: Callable | None = None
    stream_callback: Callable | None = None


# ── ChatPipeline ─────────────────────────────────────────────────────────────


class ChatPipeline:
    """6-stage orchestrator for a single chat execution.

    Replaces the 280-line ``_run_and_notify()`` nested function in
    ``AgentService.run_chat_async()`` (P1-10).
    """

    def __init__(self, service: "AgentService") -> None:
        """Create a pipeline backed by *service*'s runtime and config."""
        self._service = service
        self._metrics_callbacks: list[Callable] = []
        """Hook-based observability: callbacks invoked after LLM invocation.
        Each callback receives a ``RetryMetrics`` dataclass.  Zero-overhead
        when empty (P2-18)."""

    # ── helpers ──────────────────────────────────────────────────────────

    @property
    def _runtime(self) -> "SessionRuntime":
        return self._service._runtime  # type: ignore[attr-defined]

    @property
    def _event_bus(self) -> "EventBus | None":
        return self._service._event_bus  # type: ignore[attr-defined]

    @property
    def _backend(self) -> "LLMBackend":
        return self._service._backend  # type: ignore[attr-defined]

    @property
    def _config(self) -> Any:
        return self._service._config  # type: ignore[attr-defined]

    # ── Stage 1: @mention resolution ─────────────────────────────────────

    def resolve_mentions(self, ctx: ChatExecutionContext) -> None:
        """Scan ``@<path>`` references in *ctx.prompt* → *ctx.resolved_prompt*.

        Blocked paths (``_DENY_PREFIXES``, project-external, directories)
        are kept as-is — no expansion, no error.
        """
        repo_root = Path(ctx.repo_path).resolve()

        def _resolve_one(match: _re.Match) -> str:
            ref = match.group(1).rstrip(".,;:!?")
            for prefix in _DENY_PREFIXES:
                if ref.startswith(prefix) or prefix in ref:
                    return match.group(0)
            full = (repo_root / ref).resolve()
            try:
                full.relative_to(repo_root)
            except ValueError:
                return match.group(0)
            if full.is_file():
                try:
                    content = full.read_text(encoding="utf-8")[: _MENTION_MAX_CHARS]
                    lines = content.count("\n") + 1
                    return (
                        f"\n[FILE: {ref} ({lines} lines)]\n"
                        f"{content}\n"
                        f"[/FILE]\n"
                    )
                except Exception:
                    return match.group(0)
            return match.group(0)

        ctx.resolved_prompt = _AT_RE.sub(_resolve_one, ctx.prompt)

    # ── Stage 2: model switch ────────────────────────────────────────────

    def apply_model_switch(
        self, ctx: ChatExecutionContext,
    ) -> "LLMBackend | None":
        """Pop pending model switch → create per-session backend.

        Returns the new backend if a switch was applied, or ``None``
        if no pending switch exists.
        """
        pending = self._runtime.pop_pending_model(ctx.session_id)
        if not pending:
            return None

        model, provider = pending
        logger.info(
            "Model switch — session=%s model=%s provider=%s",
            ctx.session_id[:8], model, provider,
        )
        from llm.router import create_backend_from_config

        ec = self._service._effective_llm_config  # type: ignore[attr-defined]
        session_backend = create_backend_from_config({
            "provider": provider or ec["provider"],
            "model": model,
            "api_key": ec["api_key"],
            "base_url": ec["base_url"],
            "max_tokens": ec["max_tokens"],
            "timeout_seconds": ec["timeout_seconds"],
        })
        self._runtime.set_backend_for_session(ctx.session_id, session_backend)
        return session_backend

    # ── Stage 3: session context injection ───────────────────────────────

    def inject_session_context(self, ctx: ChatExecutionContext) -> None:
        """Inject previous session summary once per root session."""
        session_service = self._service.session_service  # type: ignore[attr-defined]
        rec = session_service.get_session(ctx.session_id)
        if rec is None:
            return
        already = rec.metadata.get("session_context_injected")
        if already:
            return

        try:
            from context.compaction import load_session_summary

            summary_path = Path(ctx.repo_path) / ".grace" / "session_summary.md"
            summary = load_session_summary(str(summary_path))
            if summary:
                from llm.base import LLMMessage

                storage = self._service._storage  # type: ignore[attr-defined]
                storage.append_message(ctx.session_id, LLMMessage(
                    role="user",
                    content=f"[Previous Session Context]\n{summary}",
                ))
                storage.append_message(ctx.session_id, LLMMessage(
                    role="assistant", content="Understood.",
                ))
                ctx.injected_session_context = True
        except Exception:
            logger.debug("Session summary injection skipped", exc_info=True)

        # Mark as injected regardless of success (don't retry every round)
        try:
            import json

            store = self._service._storage.store  # type: ignore[attr-defined]
            meta = dict(rec.metadata)
            meta["session_context_injected"] = True
            with store._connect() as conn:
                conn.execute(
                    "UPDATE sessions SET metadata_json = ? WHERE id = ?",
                    (json.dumps(meta, ensure_ascii=True), ctx.session_id),
                )
        except Exception:
            pass

    # ── Stage 4: build callbacks ─────────────────────────────────────────

    def build_callbacks(self, ctx: ChatExecutionContext) -> None:
        """Create web_confirm callback + stream callback for this session."""
        ctx.confirm_callback = self._service._build_web_confirm_callback(  # type: ignore[attr-defined]
            ctx.session_id,
        )
        self._runtime.set_web_confirm_callback(
            ctx.session_id, ctx.confirm_callback,
        )

        if self._event_bus is not None:
            eb = self._event_bus
            sid = ctx.session_id

            def _stream_cb(text: str) -> None:
                try:
                    from server.events import WsThoughtDelta
                    eb.publish_typed(sid, WsThoughtDelta(text=text))
                except Exception:
                    pass

            ctx.stream_callback = _stream_cb
            self._runtime.set_stream_callback(ctx.session_id, _stream_cb)

    # ── Stage 5: execute ─────────────────────────────────────────────────

    def execute(
        self, ctx: ChatExecutionContext,
    ) -> RunResult:
        """Run the agent via SessionRuntime.run_session().

        Returns the ``RunResult`` — *does not* push any WS events.
        Call ``finish()`` afterwards to handle plan_ready / completed / failed.
        """
        self._service._maybe_reload_rules()  # type: ignore[attr-defined]

        # Apply pending effort/thinking/permission_mode
        pending_effort = self._runtime.pop_pending_effort(ctx.session_id)
        pending_thinking = self._runtime.pop_pending_thinking(ctx.session_id)
        _ = self._runtime.pop_pending_permission_mode_override(ctx.session_id)

        # Register agent name for stats tracking
        if self._event_bus is not None and self._event_bus.recorder is not None:
            self._event_bus.recorder.set_session_agent(
                ctx.session_id, ctx.agent_name,
            )

        result = self._runtime.run_session(
            session_id=ctx.session_id,
            agent_name=ctx.agent_name,
            task_description=ctx.resolved_prompt or ctx.prompt,
            intent=ctx.intent,
        )

        # Accumulate cross-round stats in session metadata
        self._service._accumulate_session_stats(ctx.session_id, result)  # type: ignore[attr-defined]
        return result

    # ── Stage 6: finish ──────────────────────────────────────────────────

    def finish(self, ctx: ChatExecutionContext, result: RunResult) -> None:
        """Push completion events to the EventBus.

        Emits ``plan_ready`` when a plan contract was produced, or
        ``status:completed`` otherwise.
        """
        if self._event_bus is None:
            return

        _is_plan = ctx.agent_name == "plan"
        _has_plan = _is_plan or bool(result.contract)

        if _has_plan:
            _contract = result.contract
            from server.events import WsPlanReady

            self._event_bus.publish_typed(ctx.session_id, WsPlanReady(
                plan_text=result.summary,
                contract=_contract,
                revision=0,
                max_revisions=5,
                result={
                    "summary": result.summary,
                    "steps_taken": result.steps_taken,
                    "total_tokens": result.total_tokens,
                },
            ))
        else:
            # No plan — the model's last assistant message is the
            # completion notification.  Don't push a redundant WsStatus
            # event; the frontend renders the model's own response as
            # the final answer.
            pass

    # ── Convenience: run everything in a background thread ───────────────

    def run_in_background(self, ctx: ChatExecutionContext) -> None:
        """Run all 6 stages in a daemon thread."""
        import traceback

        def _pipeline() -> None:
            try:
                self.resolve_mentions(ctx)
                self.apply_model_switch(ctx)
                self.inject_session_context(ctx)
                self.build_callbacks(ctx)
                result = self.execute(ctx)
                self.finish(ctx, result)
            except Exception as exc:
                logger.exception("ChatPipeline failed for session %s", ctx.session_id)
                if self._event_bus is not None:
                    self._event_bus.publish_raw(ctx.session_id, {
                        "type": "status",
                        "status": "failed",
                        "error": str(exc),
                    })
            finally:
                self._runtime.release_session(ctx.session_id)
                self._runtime.release_backend_for_session(ctx.session_id)

        thread = threading.Thread(target=_pipeline, daemon=True)
        thread.start()
