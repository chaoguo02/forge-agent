from __future__ import annotations

from memory.context import MemoryContext
from memory.models import Memory, MemoryMetadata, MemoryStatus
from memory.recall import MemoryRecallQuery, MemoryRecallService


class InMemoryStore:
    def __init__(self, memories):
        self.memories = {m.name: m for m in memories}
        self.accessed = []
        self.writes = []

    def read_memory(self, name):
        return self.memories.get(name)

    def list_memories(self):
        from memory.models import MemorySummary
        return [MemorySummary(name=m.name, description=m.description, type=m.metadata.type.value, updated_at=m.updated_at) for m in self.memories.values()]

    def list_by_scope(self, scope="project", min_confidence=0.0):
        return [
            m for m in self.memories.values()
            if m.metadata.scope.value == scope and m.metadata.confidence >= min_confidence
        ]

    def get_index_content(self, max_lines=None):
        return ""

    def write_memory(self, memory, source="", source_session_id="", source_run_id=""):
        self.memories[memory.name] = memory
        self.writes.append((memory.name, source, source_session_id, source_run_id))
        return True

    def record_access(self, name):
        self.accessed.append(name)
        return True


def mem(name, description, content, *, type="project", scope="project", status="active", confidence=0.8):
    return Memory(
        name=name,
        description=description,
        content=content,
        metadata=MemoryMetadata(type=type, scope=scope, status=status, confidence=confidence),
    )


def test_recall_is_session_scoped_and_does_not_share_surfaced_state():
    store = InMemoryStore([
        mem("react-loop", "React loop decisions", "Use a stable reducer for React websocket timeline."),
    ])
    service = MemoryRecallService(store)

    a = service.recall(MemoryRecallQuery(session_id="a", user_message="react websocket loop"))
    b = service.recall(MemoryRecallQuery(session_id="b", user_message="react websocket loop"))

    assert any(r.memory_name == "react-loop" and r.injected for r in a.records)
    assert any(r.memory_name == "react-loop" and r.injected for r in b.records)
    assert all(r.session_id == "a" for r in a.records)
    assert all(r.session_id == "b" for r in b.records)


def test_disable_override_omits_only_that_session():
    store = InMemoryStore([
        mem("memory-system", "Memory system", "Active recall must be session-aware."),
    ])
    service = MemoryRecallService(store)
    service.set_override("a", "memory-system", "disable")

    a = service.recall(MemoryRecallQuery(session_id="a", user_message="active recall memory"))
    b = service.recall(MemoryRecallQuery(session_id="b", user_message="active recall memory"))

    assert any(r.memory_name == "memory-system" and not r.injected and r.omitted_reason == "disabled_for_session" for r in a.records)
    assert any(r.memory_name == "memory-system" and r.injected for r in b.records)


def test_deprecated_memories_are_excluded():
    store = InMemoryStore([
        mem("old", "Old", "Deprecated memory", status="deprecated"),
        mem("new", "New", "Active memory recall", status="active"),
    ])
    service = MemoryRecallService(store)

    result = service.recall(MemoryRecallQuery(session_id="s", user_message="memory recall"))

    names = {r.memory_name for r in result.records}
    assert "old" not in names
    assert "new" in names


def test_memory_context_build_section_records_session_scoped_recall():
    store = InMemoryStore([
        mem("react-loop", "React loop decisions", "**Decision:** React websocket state is session-aware.\n\n**Why:** Prevents cross-session pollution."),
    ])
    service = MemoryRecallService(store)
    context = MemoryContext(store=store, recall_service=service)

    context.set_session_context(session_id="sess-a", agent_name="build", mode="primary", repo_path=".", session_title="React work")
    context.set_task_context("Fix react websocket loop")
    context.set_user_message("react websocket session state")
    section_a = context.build_memory_section()

    context.set_session_context(session_id="sess-b", agent_name="build", mode="primary", repo_path=".", session_title="Memory work")
    context.set_task_context("Improve memory extraction")
    context.set_user_message("memory extraction discipline")
    section_b = context.build_memory_section()

    assert "Active Memory Recall" in section_a
    assert all(item["session_id"] == "sess-a" for item in service.list_recalls("sess-a"))
    assert all(item["session_id"] == "sess-b" for item in service.list_recalls("sess-b"))
    assert section_a != section_b


def test_memory_recall_event_callback_is_session_scoped():
    store = InMemoryStore([
        mem("runtime-memory", "Runtime memory", "**Decision:** Runtime recall emits memory events.\n\n**Why:** UI trace should show recall."),
    ])
    events = []
    service = MemoryRecallService(store, event_callback=lambda session_id, result: events.append((session_id, result)))

    service.recall(MemoryRecallQuery(session_id="event-session", user_message="runtime recall trace"))

    assert len(events) == 1
    assert events[0][0] == "event-session"
    assert events[0][1].records


def test_semantic_recall_resolves_chunks_to_full_memory():
    class FakeRetriever:
        def retrieve(self, user_message, task_description=""):
            return [{"source_name": "semantic-memory", "content": "chunk", "score": 0.91}]

    store = InMemoryStore([
        mem("semantic-memory", "Semantic memory", "**Decision:** Semantic recall resolves chunk sources.\n\n**Why:** Injection needs full memory metadata."),
    ])
    service = MemoryRecallService(store, retriever=FakeRetriever())

    result = service.recall(MemoryRecallQuery(session_id="semantic-session", user_message="different wording"))

    record = next(r for r in result.records if r.memory_name == "semantic-memory")
    assert record.source == "semantic"
    assert record.injected is True
    assert "Semantic recall resolves chunk sources" in result.injection_text


def test_active_files_in_recall_query_improves_scoring():
    """Memories whose anchors match active_files should score higher in recall."""
    from memory.models import Anchor

    store = InMemoryStore([
        Memory(
            name="file-memory", description="Fix a bug in core.py",
            content="**Decision:** core.py needs refactoring.\n\n**Why:** The file has too many responsibilities.",
            metadata=MemoryMetadata(type="project", scope="project", status="active", confidence=0.8),
            anchors=[Anchor(kind="file", path="src/core.py", content_hash=""),
                     Anchor(kind="file", path="src/utils.py", content_hash="")],
        ),
        Memory(
            name="unrelated-memory", description="Update README",
            content="**Decision:** README needs updates.\n\n**Why:** Outdated instructions.",
            metadata=MemoryMetadata(type="project", scope="project", status="active", confidence=0.8),
            anchors=[],
        ),
    ])
    service = MemoryRecallService(store)

    result = service.recall(MemoryRecallQuery(
        session_id="file-test",
        user_message="fix the core module",
        active_files=("src/core.py", "src/main.py"),
    ))

    file_rec = next(r for r in result.records if r.memory_name == "file-memory")
    unrelated_rec = next(r for r in result.records if r.memory_name == "unrelated-memory")
    # File-anchored memory should score higher because active_files tokens match
    assert file_rec.score > unrelated_rec.score
    assert file_rec.injected is True


def test_active_files_are_session_scoped():
    """active_files on one session must not leak to another."""
    store = InMemoryStore([
        mem("file-a", "File A memory", "**Decision:** File A.\n\n**Why:** Context for file A.", confidence=0.8),
        mem("file-b", "File B memory", "**Decision:** File B.\n\n**Why:** Context for file B.", confidence=0.8),
    ])
    service = MemoryRecallService(store)

    result_a = service.recall(MemoryRecallQuery(
        session_id="sess-a", user_message="memory",
        active_files=("tests/test_a.py",),
    ))
    result_b = service.recall(MemoryRecallQuery(
        session_id="sess-b", user_message="memory",
        active_files=("tests/test_b.py",),
    ))

    # Both sessions get their own independent recalls
    assert result_a.session_id == "sess-a"
    assert result_b.session_id == "sess-b"
    # Each result is recorded independently
    recalls_a = service.list_recalls("sess-a")
    recalls_b = service.list_recalls("sess-b")
    assert len(recalls_a) > 0
    assert len(recalls_b) > 0
    assert all(r["session_id"] == "sess-a" for r in recalls_a)
    assert all(r["session_id"] == "sess-b" for r in recalls_b)


def test_memory_context_passes_active_files_to_recall_query():
    """MemoryContext.build_memory_section() must include active_files in the recall query."""
    store = InMemoryStore([
        mem("chatstore-fix", "chatStore.ts state fix",
            "**Decision:** chatStore.ts needs the session-scoped dedup map.\n\n**Why:** Without it, events from different sessions collide.",
            confidence=0.8),
    ])
    service = MemoryRecallService(store)
    context = MemoryContext(store=store, recall_service=service)

    context.set_session_context(session_id="files-sess", agent_name="build", mode="primary", repo_path=".")
    context.set_task_context("Fix chat store session isolation")
    context.set_user_message("chatStore session dedup")
    # Simulate the agent having accessed specific files
    context.set_active_files({"src/stores/chatStore.ts", "src/hooks/useWebSocket.ts"})

    section = context.build_memory_section()

    assert "Active Memory Recall" in section
    # Verify the recall was recorded — active_files tokens should influence scoring
    recalls = service.list_recalls("files-sess")
    assert len(recalls) > 0, "Recall should be recorded"
    # The memory about chatStore should be injected (score boosted by active_files match)
    chat_rec = next(r for r in recalls if r["memory_name"] == "chatstore-fix")
    assert chat_rec["injected"] is True
    # Verify active_files actually contributed to the score reason
    assert "chatstore" in chat_rec.get("reason", "").lower()


def test_turn_id_is_recorded_in_recall():
    """turn_id from MemoryRecallQuery must be persisted in recall records."""
    store = InMemoryStore([
        mem("turn-memory", "Turn tracking", "**Decision:** Turn IDs enable precise recall tracing.\n\n**Why:** Debugging needs per-turn granularity.", confidence=0.8),
    ])
    service = MemoryRecallService(store)

    result = service.recall(MemoryRecallQuery(
        session_id="turn-sess",
        user_message="recall tracing",
        turn_id="turn-sess-step-3",
    ))

    assert result.records[0].turn_id == "turn-sess-step-3"
    # verify via list_recalls too
    recalls = service.list_recalls("turn-sess")
    assert recalls[0]["turn_id"] == "turn-sess-step-3"


def test_memory_context_passes_turn_id_to_recall():
    """MemoryContext.set_turn_id() must flow through to the recall query and records."""
    store = InMemoryStore([
        mem("ctx-turn", "Context turn", "**Decision:** Context wires turn ID.\n\n**Why:** End-to-end tracing.", confidence=0.8),
    ])
    service = MemoryRecallService(store)
    context = MemoryContext(store=store, recall_service=service)

    context.set_session_context(session_id="ctx-sess", agent_name="build", mode="primary", repo_path=".")
    context.set_task_context("Debug turn tracing")
    context.set_user_message("turn tracking context")
    context.set_turn_id("ctx-sess-step-7")

    context.build_memory_section()

    recalls = service.list_recalls("ctx-sess")
    assert len(recalls) > 0
    assert recalls[0]["turn_id"] == "ctx-sess-step-7"


def test_source_run_id_flows_through_write_memory():
    """source_run_id must be accepted by InMemoryStore.write_memory."""
    store = InMemoryStore([])
    mem_obj = mem("run-memory", "Run attribution", "**Decision:** Run ID attribution works.\n\n**Why:** Traceability.", confidence=0.8)

    ok = store.write_memory(mem_obj, source="run_finalizer", source_session_id="sess-1", source_run_id="sess-1-r2")
    assert ok is True
    assert store.writes[-1] == ("run-memory", "run_finalizer", "sess-1", "sess-1-r2")


def test_prune_old_recalls_does_not_crash():
    """prune_old_recalls should succeed even with no actual DB (fallback)."""
    store = InMemoryStore([])
    service = MemoryRecallService(store)
    result = service.prune_old_recalls(retention_days=7)
    assert isinstance(result, dict)
    assert "pruned" in result


# ── Consolidation tests ──────────────────────────────────────────────────────


def test_bigram_similarity_identical():
    from memory.store import _bigram_similarity
    assert _bigram_similarity("hello", "hello") == 1.0
    assert _bigram_similarity("abc", "xyz") == 0.0


def test_token_similarity_identical():
    from memory.store import _token_similarity
    assert _token_similarity("a b c", "a b c") == 1.0
    assert _token_similarity("a b c", "x y z") == 0.0


def test_consolidate_same_name_merges_higher_confidence():
    """Same name → UPDATED, higher confidence wins."""
    import tempfile
    from pathlib import Path
    from memory.store import MemoryStore

    tmp = tempfile.mkdtemp()
    try:
        db_path = str(Path(tmp) / "sessions.db")
        store = MemoryStore(repo_path=tmp, db_path=db_path)
        # Write an initial memory with medium confidence
        init = mem("same-name", "Initial desc", "Initial content.", confidence=0.5)
        store.write_memory(init, source="test")

        # Candidate with same name, higher confidence
        class FakeCandidate:
            name = "same-name"
            description = "Better desc"
            content = "Better content with more detail."
            confidence = "high"
            def to_memory(self):
                return mem(self.name, self.description, self.content, confidence=0.85)

        result = store.consolidate(FakeCandidate(), source="test")
        assert result == "UPDATED"

        updated = store.read_memory("same-name")
        assert updated is not None
        assert updated.description == "Better desc"
        assert "Better content" in updated.content
        assert updated.metadata.confidence == 0.85
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_consolidate_same_name_lower_confidence_keeps_original():
    """Same name, lower confidence → UPDATED but content unchanged."""
    import tempfile
    from pathlib import Path
    from memory.store import MemoryStore

    tmp = tempfile.mkdtemp()
    try:
        db_path = str(Path(tmp) / "sessions.db")
        store = MemoryStore(repo_path=tmp, db_path=db_path)
        init = mem("established", "Established memory",
                    "**Decision:** Established content.\n\n**Why:** Long-standing knowledge.",
                    confidence=0.9)
        store.write_memory(init, source="test")

        class FakeCandidate:
            name = "established"
            description = "Weak re-attempt"
            content = "New but low-confidence content."
            confidence = "low"
            def to_memory(self):
                return mem(self.name, self.description, self.content, confidence=0.25)

        result = store.consolidate(FakeCandidate(), source="test")
        assert result == "UPDATED"
        stored = store.read_memory("established")
        # Original content preserved because new confidence is lower
        assert "Established content" in stored.content
        assert stored.metadata.confidence == 0.9
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_consolidate_near_duplicate_description_returns_noop():
    """Similar description (bigram overlap ≥ 70%) → NOOP."""
    import tempfile
    from pathlib import Path
    from memory.store import MemoryStore

    tmp = tempfile.mkdtemp()
    try:
        db_path = str(Path(tmp) / "sessions.db")
        store = MemoryStore(repo_path=tmp, db_path=db_path)
        existing = mem("existing-mem",
                        "React websocket state is session aware",
                        "**Decision:** Use session-scoped websocket state.\n\n**Why:** Prevent cross-session pollution.",
                        confidence=0.8)
        store.write_memory(existing, source="test")

        class FakeCandidate:
            name = "react-loop"
            description = "React websocket state session aware approach"
            content = "Similar content about websocket and session state management."
            anchors = []
            confidence = "high"
            def to_memory(self):
                return mem(self.name, self.description, self.content, confidence=0.85)

        result = store.consolidate(FakeCandidate(), source="run_finalizer")
        assert result == "NOOP"
        # The candidate was NOT written
        assert store.read_memory("react-loop") is None
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_consolidate_unique_memory_returns_new():
    """No match → NEW, memory is written."""
    import tempfile
    from pathlib import Path
    from memory.store import MemoryStore

    tmp = tempfile.mkdtemp()
    try:
        db_path = str(Path(tmp) / "sessions.db")
        store = MemoryStore(repo_path=tmp, db_path=db_path)
        # Pre-existing unrelated memory
        store.write_memory(mem("unrelated", "Unrelated", "Totally different.", confidence=0.8), source="test")

        class FakeCandidate:
            name = "unique-memory"
            description = "Unique memory about build configuration"
            content = "**Decision:** Use webpack for bundling.\n\n**Why:** Better tree-shaking with ES modules."
            anchors = []
            confidence = "high"
            def to_memory(self):
                return mem(self.name, self.description, self.content, confidence=0.85)

        result = store.consolidate(FakeCandidate(), source="run_finalizer",
                                   source_session_id="sess-1", source_run_id="sess-1-r3")
        assert result == "NEW"

        stored = store.read_memory("unique-memory")
        assert stored is not None
        assert "webpack" in stored.content
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ── Token estimator tests ─────────────────────────────────────────────────────


def test_token_estimator_returns_positive_for_content():
    from memory.token_estimator import count_tokens
    n = count_tokens("hello world this is a test sentence for token counting")
    assert n > 0
    # Even tiktoken should be in a reasonable range
    assert 5 <= n <= 30


def test_token_estimator_short_text_is_not_zero():
    from memory.token_estimator import count_tokens
    assert count_tokens("hi") >= 1


def test_token_estimator_empty_yields_zero():
    from memory.token_estimator import count_tokens
    assert count_tokens("") == 0


def test_injection_overhead_increases_with_record_count():
    from memory.token_estimator import injection_overhead
    assert injection_overhead(0) == 0
    assert injection_overhead(1) > 0
    assert injection_overhead(5) > injection_overhead(1)


def test_recall_injection_respects_token_budget():
    """When total tokens exceed max_tokens, later memories are omitted."""
    # Create many memories with moderate content so budget fills up
    memories = []
    for i in range(20):
        memories.append(mem(
            f"mem-{i}",
            f"Memory number {i}",
            "**Decision:** Token budget memory.\n\n**Why:** Test budget enforcement.",
            confidence=0.8,
        ))
    store = InMemoryStore(memories)
    # Tight enough that not all 20 fit, loose enough that at least 1 does
    service = MemoryRecallService(store, max_tokens=200, max_injected=20)

    result = service.recall(MemoryRecallQuery(
        session_id="budget-sess",
        user_message="memory tokens budget test",
    ))

    injected_names = [r.memory_name for r in result.records if r.injected]
    omitted_token = [r for r in result.records if r.omitted_reason == "token_budget"]
    assert len(injected_names) > 0, "At least one should be injected"
    assert len(omitted_token) > 0, "Token budget should cause omissions"
    assert len(injected_names) < len(result.records), "Not all should fit within budget"


def test_memory_context_preserves_token_estimator_through_pipeline():
    """full chain: MemoryContext → build_memory_section uses token estimator."""
    store = InMemoryStore([
        mem("tok-pipe", "Token pipeline",
            "**Decision:** Token estimation flows through the full pipeline.\n\n**Why:** Needed for accurate budgeting.",
            confidence=0.8),
    ])
    service = MemoryRecallService(store)
    context = MemoryContext(store=store, recall_service=service)

    context.set_session_context(session_id="tok-sess", agent_name="build", mode="primary", repo_path=".")
    context.set_task_context("Test token budget pipeline")
    context.set_user_message("token estimation pipeline")

    section = context.build_memory_section()

    assert "Active Memory Recall" in section
    assert "tok-pipe" in section
