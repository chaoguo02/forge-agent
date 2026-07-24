from __future__ import annotations

from agent.task import Event, EventType
from agent.session.models import SessionMode
from app.storage.sqlite import SqliteStorageBackend
from server.events import WsApprovalRequired
from server.services.event_bus import EventBus


def _create_storage(tmp_path):
    storage = SqliteStorageBackend(str(tmp_path / "sessions.db"))
    session = storage.create_session(
        agent_name="build",
        mode=SessionMode.PRIMARY,
        repo_path=str(tmp_path),
        title="Trace session",
    )
    return storage, session


def test_sqlite_trace_events_are_sequenced_and_queryable(tmp_path):
    storage, session = _create_storage(tmp_path)

    first = storage.insert_trace_event(session.id, {"type": "thought", "content": "one"})
    second = storage.insert_trace_event(session.id, {"type": "tool_call", "name": "Read"})

    assert first["seq"] == 1
    assert second["seq"] == 2
    assert [event["type"] for event in storage.list_trace_events(session.id)] == ["thought", "tool_call"]
    assert [event["type"] for event in storage.list_trace_events(session.id, after_seq=1)] == ["tool_call"]


def test_event_bus_persists_translated_runtime_events_without_subscribers(tmp_path):
    storage, session = _create_storage(tmp_path)
    bus = EventBus(repo_path=str(tmp_path))
    bus.trace_store = storage

    bus.publish(Event(
        event_type=EventType.ACTION,
        task_id=session.id,
        session_id=session.id,
        payload={
            "step": 3,
            "action": {
                "thought": "Need to inspect the file",
                "tool_calls": [{"name": "Read", "params": {"file_path": "web/src/App.tsx"}, "id": "tc-1"}],
            },
        },
    ))

    events = storage.list_trace_events(session.id)
    assert [(event["type"], event["seq"]) for event in events] == [("thought", 1), ("tool_call", 2)]
    assert events[0]["content"] == "Need to inspect the file"
    assert events[1]["name"] == "Read"


def test_event_bus_persists_direct_typed_events(tmp_path):
    storage, session = _create_storage(tmp_path)
    bus = EventBus(repo_path=str(tmp_path))
    bus.trace_store = storage

    bus.publish_typed(session.id, WsApprovalRequired(
        request_id="approval-1",
        tool_name="Write",
        params={"file_path": "web/src/App.tsx"},
    ))

    events = storage.list_trace_events(session.id)
    assert len(events) == 1
    assert events[0]["seq"] == 1
    assert events[0]["type"] == "approval_required"
    assert events[0]["request_id"] == "approval-1"
