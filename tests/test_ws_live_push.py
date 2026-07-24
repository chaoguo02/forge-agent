"""Real WebSocket live push integration tests.

Tests the EventBus -> SessionSubscriber -> WebSocket delivery pipeline
with actual asyncio WebSocket connections.  This is the last piece of
Phase 1B runtime reliability -- verifying that memory_recall and
memory_written events surface on the WebSocket in production shape.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import threading
import time
from typing import Any

import pytest
import uvicorn
import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from server.events import WsMemoryRecall, WsMemoryWritten
from server.services.event_bus import EventBus

logger = logging.getLogger(__name__)


# -- Helpers ------------------------------------------------------------------

def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _TestServer:
    """Minimal FastAPI server with an EventBus-backed WebSocket endpoint.

    The EventBus is created inside _build_app() so its event loop matches
    the uvicorn server's event loop -- this is critical for start_drain().
    """

    def __init__(self) -> None:
        self.port = _find_free_port()
        self.bus: EventBus | None = None
        self._thread: threading.Thread | None = None
        self._server: uvicorn.Server | None = None

    def _build_app(self) -> FastAPI:
        self.bus = EventBus(repo_path="")
        bus = self.bus
        app = FastAPI()

        @app.websocket("/api/ws/sessions/{session_id}")
        async def session_events_ws(websocket: WebSocket, session_id: str) -> None:
            await websocket.accept()
            await bus.subscribe(session_id, websocket)
            try:
                while True:
                    data = await websocket.receive_text()
                    msg = json.loads(data)
                    if msg.get("action") == "ping":
                        await websocket.send_json({"type": "pong"})
            except WebSocketDisconnect:
                pass
            except Exception:
                pass
            finally:
                await bus.unsubscribe(session_id, websocket)

        @app.get("/health")
        async def health():
            return {"status": "ok"}

        return app

    def start(self) -> None:
        app = self._build_app()
        config = uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        for _ in range(50):
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.1):
                    break
            except (ConnectionRefusedError, OSError):
                time.sleep(0.05)
        else:
            self.stop()
            raise RuntimeError("Test server did not start within timeout")

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)


@pytest.fixture(scope="function")
def test_server():
    srv = _TestServer()
    srv.start()
    yield srv
    srv.stop()


# -- Tests -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_recall_pushed_to_live_websocket(test_server: _TestServer):
    """WsMemoryRecall published via EventBus arrives on a real WebSocket."""
    uri = f"ws://127.0.0.1:{test_server.port}/api/ws/sessions/live-recall"

    async with websockets.connect(uri) as ws:
        # Publish memory_recall (simulates MemoryRecallService callback)
        await asyncio.sleep(0.1)
        test_server.bus.publish_typed("live-recall", WsMemoryRecall(
            injected_count=3, candidate_count=7, omitted_count=4,
            top_names=["react-loop", "memory-discipline", "build-config"],
        ))
        test_server.bus.publish_typed("live-recall", WsMemoryWritten(
            name="extraction-quality",
            description="Memory extraction requires confidence reasons",
            source="run_finalizer", confidence=0.85,
        ))

        # Collect events
        events: list[dict[str, Any]] = []
        for _ in range(2):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                events.append(json.loads(raw))
            except asyncio.TimeoutError:
                break

        assert len(events) >= 1, f"Expected >=1 event, got {len(events)}"
        recall_ev = next((e for e in events if e.get("type") == "memory_recall"), None)
        assert recall_ev is not None, f"No memory_recall in {events}"
        assert recall_ev["injected_count"] == 3
        assert recall_ev["candidate_count"] == 7
        assert recall_ev["omitted_count"] == 4
        assert "react-loop" in recall_ev["top_names"]

        written_ev = next((e for e in events if e.get("type") == "memory_written"), None)
        if written_ev is not None:
            assert written_ev["name"] == "extraction-quality"
            assert written_ev["source"] == "run_finalizer"
            assert written_ev["confidence"] == 0.85


@pytest.mark.asyncio
async def test_two_websockets_both_receive_same_memory_event(test_server: _TestServer):
    """Two clients for the same session both receive the published event."""
    uri = f"ws://127.0.0.1:{test_server.port}/api/ws/sessions/multi-sub"

    async def connect_and_collect() -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        async with websockets.connect(uri) as ws:
            await asyncio.sleep(0.1)
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                events.append(json.loads(raw))
            except asyncio.TimeoutError:
                pass
        return events

    task_a = asyncio.create_task(connect_and_collect())
    task_b = asyncio.create_task(connect_and_collect())
    await asyncio.sleep(0.25)  # let both connect

    test_server.bus.publish_typed("multi-sub", WsMemoryRecall(
        injected_count=1, candidate_count=3, omitted_count=2,
        top_names=["shared-memory"],
    ))

    results = await asyncio.wait_for(asyncio.gather(task_a, task_b), timeout=5.0)
    for i, events in enumerate(results):
        assert len(events) >= 1, f"Subscriber {i} got {len(events)} events"
        assert events[0]["type"] == "memory_recall"
        assert "shared-memory" in events[0]["top_names"]


@pytest.mark.asyncio
async def test_different_sessions_are_isolated(test_server: _TestServer):
    """Events to session A must NOT arrive on session B's WebSocket."""
    uri_a = f"ws://127.0.0.1:{test_server.port}/api/ws/sessions/sess-a"
    uri_b = f"ws://127.0.0.1:{test_server.port}/api/ws/sessions/sess-b"

    async with websockets.connect(uri_a) as ws_a, websockets.connect(uri_b) as ws_b:
        await asyncio.sleep(0.15)

        # Publish only to session B
        test_server.bus.publish_typed("sess-b", WsMemoryRecall(
            injected_count=5, candidate_count=5, omitted_count=0,
            top_names=["b-only"],
        ))

        # B should receive it
        try:
            raw = await asyncio.wait_for(ws_b.recv(), timeout=2.0)
            assert json.loads(raw)["type"] == "memory_recall"
        except asyncio.TimeoutError:
            pytest.fail("Session B should have received the event")

        # A should NOT receive anything
        try:
            raw = await asyncio.wait_for(ws_a.recv(), timeout=1.0)
            ev = json.loads(raw)
            pytest.fail(f"Session A received an event it shouldn't: {ev['type']}")
        except asyncio.TimeoutError:
            pass  # correct -- isolation works


@pytest.mark.asyncio
async def test_memory_written_all_fields_integral(test_server: _TestServer):
    """WsMemoryWritten with full fields arrives correctly over WebSocket."""
    uri = f"ws://127.0.0.1:{test_server.port}/api/ws/sessions/write-test"

    async with websockets.connect(uri) as ws:
        await asyncio.sleep(0.1)

        test_server.bus.publish_typed("write-test", WsMemoryWritten(
            name="react-state-session-aware",
            description="React websocket state must be session-scoped",
            source="structured_precipitation",
            confidence=0.92,
        ))

        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
            ev = json.loads(raw)
        except asyncio.TimeoutError:
            pytest.fail("Expected memory_written but timed out")

        assert ev["type"] == "memory_written"
        assert ev["name"] == "react-state-session-aware"
        assert ev["description"] == "React websocket state must be session-scoped"
        assert ev["source"] == "structured_precipitation"
        assert ev["confidence"] == 0.92


@pytest.mark.asyncio
async def test_eventbus_queue_delivers_to_subscriber():
    """Direct EventBus publish_typed -> queue delivery (unit-level, no server).

    Since has_subscribers gate requires an actual WebSocket, this test
    manually creates a subscriber and publishes directly to its queue to
    verify the thread-safe publish path works correctly.
    """
    loop = asyncio.get_running_loop()
    bus = EventBus(repo_path="")
    sub = await bus.create_session("direct-test")

    # Manually add a "fake" websocket so has_subscribers is True
    # (the drain task won't actually send to it, but publish won't skip us)
    sub.websockets.add(object())  # type: ignore[arg-type]

    assert sub.queue.empty()
    bus.publish_typed("direct-test", WsMemoryRecall(
        injected_count=2, candidate_count=4, omitted_count=2,
        top_names=["mem-1", "mem-2"],
    ))
    await asyncio.sleep(0.1)
    assert not sub.queue.empty()

    event = await sub.queue.get()
    assert event["type"] == "memory_recall"
    assert event["injected_count"] == 2
    assert event["candidate_count"] == 4
    assert event["top_names"] == ["mem-1", "mem-2"]

    await bus.destroy_session("direct-test")
