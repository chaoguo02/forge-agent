from __future__ import annotations

from pathlib import Path
import tempfile

from core.base import Action, ActionType, ToolRegistry
from llm.base import MockBackend
from memory.context import MemoryContext
from memory.models import Memory, MemoryMetadata
from memory.recall import MemoryRecallService
from memory.store import MemoryStore
from agent.event_log import EventLog
from agent.task import Task


def _write_memory(store: MemoryStore, name: str, content: str) -> None:
    assert store.write_memory(Memory(
        name=name,
        description="Runtime active recall memory",
        content=content,
        metadata=MemoryMetadata(type="project", scope="project", confidence=0.85),
    ))


def test_session_runtime_run_injects_active_memory_recall_into_backend():
    from agent.session.models import SessionMode
    from agent.session.session_store import SessionStore
    from agent.session.runtime import SessionRuntime
    from agent.session.agent_registry import AgentRegistryV2
    from agent.core import AgentConfig

    tmp = tempfile.mkdtemp()
    try:
        db_path = str(Path(tmp) / "sessions.db")
        session_store = SessionStore(db_path)
        rec = session_store.create_session(
            agent_name="build",
            mode=SessionMode.PRIMARY,
            repo_path=tmp,
            title="Runtime Recall",
        )
        memory_store = MemoryStore(repo_path=tmp, db_path=db_path)
        _write_memory(
            memory_store,
            "runtime-recall",
            "**Decision:** Runtime prompts must include Active Memory Recall.\n\n**Why:** The agent should use durable project context.",
        )
        recall_service = MemoryRecallService(memory_store)
        memory_context = MemoryContext(store=memory_store, recall_service=recall_service)
        backend = MockBackend([
            Action(ActionType.FINISH, thought="Use memory", message="Done"),
        ])
        runtime = SessionRuntime(
            store=session_store,
            backend=backend,
            base_registry=ToolRegistry(),
            agent_registry=AgentRegistryV2(project_dir=tmp),
            root_agent_config=AgentConfig(max_steps=2, stream=False),
            log_dir=tmp,
            memory_context=memory_context,
        )

        runtime.run_session(
            rec.id,
            agent_name="build",
            task_description="Use runtime active recall memory",
        )

        flattened = "\n".join(str(msg.content) for call in backend.received_messages for msg in call)
        assert "Active Memory Recall" in flattened
        assert "runtime-recall" in flattened
        recalls = recall_service.list_recalls(rec.id)
        assert any(item["memory_name"] == "runtime-recall" and item["injected"] for item in recalls)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_run_finalizer_structured_precipitation_records_source_session_id():
    from agent.run_finalizer import RunFinalizer
    from agent.event_log import EventLog
    from agent.task import Task

    tmp = tempfile.mkdtemp()
    try:
        db_path = str(Path(tmp) / "sessions.db")
        memory_store = MemoryStore(repo_path=tmp, db_path=db_path)
        recall_service = MemoryRecallService(memory_store)
        memory_context = MemoryContext(store=memory_store, recall_service=recall_service)
        finalizer = RunFinalizer(memory_context, backend=None)
        task = Task(
            task_id="source-session",
            description="Fix high severity bug",
            repo_path=tmp,
            metadata={"session_id": "source-session"},
        )
        log = EventLog(Path(tmp) / "events.jsonl")
        findings = [{
            "severity": "HIGH",
            "category": "bug",
            "title": "Session scoped source attribution",
            "description": "Structured precipitation memories must retain their source session.",
            "recommendation": "Pass source_session_id through structured memory writes.",
        }]

        written = finalizer.extract(task, log, "Done", accumulated_findings=findings, skip_llm=True)

        assert written == 1
        generated = recall_service.list_generated("source-session")
        assert len(generated) == 1
        assert generated[0]["source_session_id"] == "source-session"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_source_run_id_written_to_memory_via_store():
    """source_run_id passed to store.write_memory must be persisted in the DB."""
    import shutil

    from agent.run_finalizer import RunFinalizer
    from agent.event_log import EventLog
    from agent.task import Task

    tmp = tempfile.mkdtemp()
    try:
        db_path = str(Path(tmp) / "sessions.db")
        memory_store = MemoryStore(repo_path=tmp, db_path=db_path)
        recall_service = MemoryRecallService(memory_store)
        memory_context = MemoryContext(store=memory_store, recall_service=recall_service)
        # Simulate what runtime.py does: set a run_id
        memory_context.set_run_id("my-sess-r3")
        finalizer = RunFinalizer(memory_context, backend=None)
        task = Task(
            task_id="run-attribution",
            description="High severity bug found",
            repo_path=tmp,
            metadata={"session_id": "run-attribution"},
        )
        log = EventLog(Path(tmp) / "events.jsonl")
        findings = [{
            "severity": "HIGH",
            "category": "bug",
            "title": "Run attribution tracking",
            "description": "Memories must record which run produced them for audit trails.",
            "recommendation": "Store source_run_id in memory_entries.",
        }]

        written = finalizer.extract(task, log, "Done", accumulated_findings=findings, skip_llm=True)

        assert written == 1
        generated = recall_service.list_generated("run-attribution")
        assert len(generated) == 1
        assert generated[0]["source_run_id"] == "my-sess-r3"
        # Also verify via the session_id (generated memories are queried by source_session_id)
        assert generated[0]["source_session_id"] == "run-attribution"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
