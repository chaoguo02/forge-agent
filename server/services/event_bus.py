"""
Event bus — bridges synchronous SessionRuntime event_callback to async WebSocket.

Architecture:
  SessionRuntime thread  ──publish()──>  asyncio.Queue  ──drain task──>  WebSocket

Each session gets its own queue. The publish() method is called from the
SessionRuntime thread (via event_callback). It pushes events into the queue
using loop.call_soon_threadsafe(). A background asyncio task drains the queue
and broadcasts to all subscribed WebSocket clients.

Usage:
    bus = EventBus()
    bus.subscribe(session_id, websocket)
    bus.start_drain(session_id)

    # In SessionRuntime init:
    runtime = SessionRuntime(..., event_callback=bus.publish)

    # When SessionRuntime finishes:
    bus.unsubscribe_all(session_id)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class SessionSubscriber:
    """Tracks one session's queue + set of WebSocket subscribers."""

    def __init__(self, session_id: str, loop: asyncio.AbstractEventLoop) -> None:
        self.session_id = session_id
        self.loop = loop
        self.queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self.websockets: set[WebSocket] = set()
        self._drain_task: asyncio.Task[None] | None = None

    def subscribe(self, ws: WebSocket) -> None:
        self.websockets.add(ws)

    def unsubscribe(self, ws: WebSocket) -> None:
        self.websockets.discard(ws)

    @property
    def has_subscribers(self) -> bool:
        return bool(self.websockets)

    def publish(self, event: dict[str, Any]) -> None:
        """Called from SessionRuntime thread. Thread-safe via call_soon_threadsafe."""
        self.loop.call_soon_threadsafe(self.queue.put_nowait, event)

    def signal_complete(self) -> None:
        """Signal the drain task that no more events will arrive."""
        self.loop.call_soon_threadsafe(self.queue.put_nowait, None)

    async def _drain(self) -> None:
        """Background task: drain queue and broadcast to all subscribers."""
        try:
            while True:
                event = await self.queue.get()
                if event is None:  # sentinel → shutdown
                    break
                disconnected: list[WebSocket] = []
                serial_errors: list[WebSocket] = []
                for ws in self.websockets:
                    try:
                        await ws.send_json(event)
                    except (ConnectionResetError, ConnectionAbortedError, OSError):
                        disconnected.append(ws)
                    except (TypeError, ValueError) as exc:
                        logger.error("Failed to serialize event: %s — event keys: %s", exc, list(event.keys())[:10])
                        # Serialization error — remove this ws to prevent retrying
                        # the same bad event on it.  The client should reconnect.
                        disconnected.append(ws)
                    except Exception:
                        disconnected.append(ws)
                for ws in disconnected:
                    self.websockets.discard(ws)
        except asyncio.CancelledError:
            pass
        finally:
            # Flush remaining events on cancellation
            while not self.queue.empty():
                try:
                    self.queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

    def start_drain(self) -> None:
        if self._drain_task is None:
            self._drain_task = self.loop.create_task(self._drain())

    async def stop_drain(self) -> None:
        if self._drain_task is not None:
            self._drain_task.cancel()
            try:
                await self._drain_task
            except asyncio.CancelledError:
                pass
            self._drain_task = None


# ─── Event translation ───────────────────────────────────────────────────────

def _translate_event(event: Any) -> list[dict[str, Any]]:
    """Translate ``agent.task.Event`` → list of typed WS messages.

    One Event can produce multiple messages (e.g. ACTION → thought + tool_call).
    Uses server.events dataclasses as the single source of truth for shapes.
    """
    from agent.task import EventType
    from server.events import (
        WsStatus, WsThought, WsToolCall, WsObservation, WsReflection,
        WsSubagentStart, WsSubagentStop, WsPlanReady,
    )

    ev_type = getattr(event, "event_type", "")
    if hasattr(ev_type, "value"):
        ev_type = ev_type.value
    payload = getattr(event, "payload", {}) or {}
    ts = getattr(event, "timestamp", "")
    child_id = getattr(event, "child_session_id", "")

    if ev_type == "task_start":
        return [WsStatus(status="running", timestamp=ts).to_dict()]

    if ev_type == "task_complete":
        # Always emit status:completed so the frontend has an explicit
        # completion signal (clears isRunning, watchdog, etc.).
        _result: dict = {
            "summary": payload.get("summary", ""),
            "steps_taken": payload.get("steps", 0),
        }
        # Forward cache stats if present (prompt caching hit rate)
        _cache = payload.get("cache")
        if _cache:
            _result["cache"] = _cache
        msgs: list[dict] = [WsStatus(status="completed", result=_result, timestamp=ts).to_dict()]
        # When a plan contract was produced (ExitPlanMode), also emit
        # plan_ready so it can be recovered from /trace/events after refresh.
        _contract = payload.get("contract")
        if _contract:
            msgs.append(WsPlanReady(
                plan_text=payload.get("summary", ""),
                contract=_contract,
                result={
                    "summary": payload.get("summary", ""),
                    "steps_taken": payload.get("steps", 0),
                },
                timestamp=ts,
            ).to_dict())
        return msgs

    if ev_type == "task_failed":
        error_text = payload.get("error", str(payload.get("reason", "unknown")))
        status = "cancelled" if "cancel" in str(error_text).lower() else "failed"
        return [WsStatus(status=status,
            error=error_text,
            timestamp=ts).to_dict()]

    if ev_type == "action":
        action = payload.get("action", {}) or {}
        step = payload.get("step", 0)
        msgs: list[dict] = []

        thought = action.get("thought", "")
        if thought and thought.strip():
            msgs.append(WsThought(content=thought, step=step,
                child_session_id=child_id, timestamp=ts).to_dict())

        for tc in (action.get("tool_calls") or []):
            msgs.append(WsToolCall(
                name=tc.get("name", ""), params=tc.get("params", {}),
                step=step, id=tc.get("id", ""),
                child_session_id=child_id, timestamp=ts).to_dict())

        atype = action.get("action_type", "")
        msg_text = action.get("message", "")
        if atype in ("finish", "give_up") and msg_text:
            msgs.append(WsStatus(status=atype, message=msg_text, timestamp=ts).to_dict())

        return msgs

    if ev_type == "observation":
        obs = payload.get("observation", {}) or {}
        _obs_meta = obs.get("metadata", {}) or {}
        return [WsObservation(
            tool_name=obs.get("tool_name", ""), output=obs.get("output", ""),
            error=obs.get("error"), status=obs.get("status", ""),
            step=payload.get("step", 0), id=payload.get("tool_call_id"),
            diff=_obs_meta.get("diff", ""),
            child_session_id=child_id, timestamp=ts).to_dict()]

    if ev_type == "reflection":
        return [WsReflection(
            content=payload.get("reason", "") or str(payload.get("reflection", "")),
            timestamp=ts).to_dict()]

    if ev_type in ("subagent_start",):
        return [WsSubagentStart(
            child_session_id=payload.get("child_session_id", ""),
            agent_name=payload.get("agent_name", ""), timestamp=ts).to_dict()]

    if ev_type in ("subagent_stop", "subagent_complete"):
        return [WsSubagentStop(
            child_session_id=payload.get("child_session_id", ""),
            status=payload.get("status", "completed"), timestamp=ts).to_dict()]

    # Fallback: send raw event as-is
    return [{"type": ev_type, "payload": payload, "timestamp": ts}]


class EventBus:
    """Manages per-session event queues and WebSocket subscribers."""

    def __init__(self, repo_path: str = "") -> None:
        self._sessions: dict[str, SessionSubscriber] = {}
        self._lock = asyncio.Lock()
        self._publish_lock = threading.Lock()  # protects _sessions reads from sync thread
        self._repo_path = repo_path
        self.recorder: Any = None  # StatsRecorder instance, set by agent_service
        self.trace_store: Any = None  # StorageBackend, set by agent_service
        self.trace_cache: Any = None  # InMemoryTraceCache, set by agent_service

    # ── Session lifecycle ──────────────────────────────────────────────────

    async def create_session(self, session_id: str) -> SessionSubscriber:
        async with self._lock:
            existing = self._sessions.get(session_id)
            if existing is not None:
                return existing
            loop = asyncio.get_running_loop()
            sub = SessionSubscriber(session_id, loop)
            self._sessions[session_id] = sub
            return sub

    async def destroy_session(self, session_id: str) -> None:
        async with self._lock:
            sub = self._sessions.get(session_id)
            if sub is None or sub.has_subscribers:
                return  # re-subscribed between unsubscribe and destroy — keep alive
            self._sessions.pop(session_id, None)
        if sub is not None:
            sub.signal_complete()
            await sub.stop_drain()
        if self.trace_cache is not None:
            try:
                self.trace_cache.clear_session(session_id)
            except Exception:
                logger.debug("Trace cache cleanup failed", exc_info=True)

    def get_subscriber(self, session_id: str) -> SessionSubscriber | None:
        return self._sessions.get(session_id)

    # ── Publish (called from SessionRuntime thread) ────────────────────────

    def _persist_trace_event(self, session_id: str, msg: dict[str, Any], *, source: str = "event_bus") -> dict[str, Any]:
        stored = msg
        if self.trace_store is not None:
            try:
                stored = self.trace_store.insert_trace_event(session_id, msg, source=source)
            except Exception:
                logger.exception("Trace persistence failed — session=%s type=%s", session_id[:8], msg.get("type"))
                stored = msg
        if self.trace_cache is not None:
            try:
                self.trace_cache.append(session_id, stored)
            except Exception:
                logger.debug("Trace cache append failed", exc_info=True)
        return stored

    def _publish_msg(self, session_id: str, msg: dict[str, Any], *, source: str = "event_bus") -> None:
        stored = self._persist_trace_event(session_id, msg, source=source)
        with self._publish_lock:
            sub = self._sessions.get(session_id)
        if sub is not None and sub.has_subscribers:
            sub.publish(stored)

    def publish(self, event: Any) -> None:
        """Synchronous callback — called from SessionRuntime thread.

        Translates ``agent.task.Event`` objects into the standardized WS
        message format and pushes them to session subscribers.

        Routes events to the correct session when ``event.session_id`` is set.
        Falls back to broadcast (all sessions) only when no session_id is
        available (backward compatibility for code paths that haven't been
        updated yet).

        Standard WS message types:
            status          — session state change (running/completed/failed)
            thought         — model's thinking text
            tool_call       — tool invocation (name + params)
            observation     — tool result (output/error)
            reflection      — model reflection
            subagent_start  — child session spawned
            subagent_stop   — child session finished
        """
        try:
            msgs = _translate_event(event)
            target_session_id = getattr(event, "session_id", None)
            if target_session_id:
                # Route to the specific session that generated this event
                for msg in msgs:
                    logger.info("EVENT → %s | type=%s step=%s",
                                 target_session_id[:8], msg.get("type"), msg.get("step", ""))
                    self._publish_msg(target_session_id, msg)
                if target_session_id not in self._sessions:
                    logger.debug("EVENT persisted without subscriber: session=%s", target_session_id[:8])
            else:
                # Drop unroutable events silently — broadcasting to all sessions
                # is a correctness risk (information leak) and cannot be triggered
                # by any current code path.  Events always carry a session_id.
                logger.debug("EVENT dropped (no session_id): type=%s",
                               getattr(event, "event_type", "?"))
            # Stats recording moved to first-party instrumentation in agent/core.py.
            # The recorder field is kept for backward compat but no longer called here.
        except Exception:
            logger.exception("EventBus.publish failed")

    def publish_raw(self, session_id: str, msg: dict[str, Any]) -> None:
        """Push a pre-formatted WS message to one session's subscribers.

        Prefer ``publish_typed()`` for new code — it enforces the
        event schema via server.events dataclasses.
        """
        try:
            self._publish_msg(session_id, msg, source="raw")
        except Exception:
            logger.exception("EventBus.publish_raw failed")

    def publish_typed(self, session_id: str, event: Any) -> None:
        """Push a typed WS event (from server.events) to one session.

        The event must be a dataclass with a ``to_dict()`` method.
        This is the preferred API for new code — it ensures the event
        schema matches the frontend's expected shape.
        """
        try:
            self._publish_msg(session_id, event.to_dict(), source="typed")
        except Exception:
            logger.exception("EventBus.publish_typed failed")

    # ── Subscriber management ──────────────────────────────────────────────

    async def subscribe(self, session_id: str, ws: WebSocket) -> None:
        sub = self.get_subscriber(session_id)
        if sub is None:
            sub = await self.create_session(session_id)
        sub.subscribe(ws)
        sub.start_drain()

    async def unsubscribe(self, session_id: str, ws: WebSocket) -> None:
        sub = self.get_subscriber(session_id)
        if sub is not None:
            sub.unsubscribe(ws)
            if not sub.has_subscribers:
                await self.destroy_session(session_id)
