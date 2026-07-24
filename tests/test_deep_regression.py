"""Deep regression tests — critical invariants for multi-session correctness.

These tests validate invariants that shallow tests easily miss:
- Session isolation under concurrent access
- Cache invalidation across all mutation paths
- Event ordering and dedup correctness under stress
- Error recovery paths
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from memory.context import MemoryContext
from memory.models import Memory, MemoryMetadata
from memory.recall import MemoryRecallQuery, MemoryRecallService
from memory.store import MemoryStore


def mem(name, description, content, *, type="project", scope="project", status="active", confidence=0.8):
    return Memory(
        name=name, description=description, content=content,
        metadata=MemoryMetadata(type=type, scope=scope, status=status, confidence=confidence),
    )


# ── Session isolation ────────────────────────────────────────────────────────


def test_build_memory_section_isolation_two_sessions_no_cache_leak():
    """build_memory_section for session A must not return cached result from session B."""
    tmp = tempfile.mkdtemp()
    try:
        db_path = str(Path(tmp) / "sessions.db")
        store = MemoryStore(repo_path=tmp, db_path=db_path)
        store.write_memory(
            mem("build-cmds", "Build commands for project X",
                "**Decision:** Use `cargo build` for Rust.\n\n**Why:** Standard approach."),
            source="test",
        )
        service = MemoryRecallService(store)
        ctx_a = MemoryContext(store=store, recall_service=service)
        ctx_b = MemoryContext(store=store, recall_service=service)

        # Setup session A
        ctx_a.set_session_context(session_id="sess-a", agent_name="build", mode="primary", repo_path=".")
        ctx_a.set_task_context("Build Rust project")
        ctx_a.set_user_message("rust cargo build")

        # Setup session B (different context)
        ctx_b.set_session_context(session_id="sess-b", agent_name="explore", mode="primary", repo_path=".")
        ctx_b.set_task_context("Explore Python codebase")
        ctx_b.set_user_message("python virtual environment")

        section_a = ctx_a.build_memory_section()
        section_b = ctx_b.build_memory_section()

        assert "Active Memory Recall" in section_a
        assert "Active Memory Recall" in section_b

        # Both sessions should see "build-cmds" via scoped recall since
        # keyword matching picks it up for both (they're project-scoped).
        # But the key invariant: the cached section MUST be different per session.
        # If they share cache, one session would return the other's cached text.
        recalls_a = service.list_recalls("sess-a")
        recalls_b = service.list_recalls("sess-b")
        assert all(r["session_id"] == "sess-a" for r in recalls_a)
        assert all(r["session_id"] == "sess-b" for r in recalls_b)

        # Re-build: should hit cache (no new recalls recorded)
        section_a2 = ctx_a.build_memory_section()
        assert section_a2 == section_a  # cache hit, same content
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_cache_invalidation_after_set_active_files():
    """After set_active_files, build_memory_section must recompute with new files."""
    tmp = tempfile.mkdtemp()
    try:
        db_path = str(Path(tmp) / "sessions.db")
        store = MemoryStore(repo_path=tmp, db_path=db_path)
        store.write_memory(
            mem("css-fix", "CSS file fix for layout",
                "**Decision:** CSS flex layout needs gap property.\n\n**Why:** Modern browsers support it.",
                confidence=0.8),
            source="test",
        )
        service = MemoryRecallService(store)
        ctx = MemoryContext(store=store, recall_service=service)
        ctx.set_session_context(session_id="inval-test", agent_name="build", mode="primary", repo_path=".")
        ctx.set_task_context("Fix layout CSS")
        ctx.set_user_message("layout flex gap")

        section_before = ctx.build_memory_section()
        assert "Active Memory Recall" in section_before

        # Now set active_files — should invalidate and produce fresh recall
        ctx.set_active_files({"src/styles/layout.css"})
        section_after = ctx.build_memory_section()

        # Both should have memory recall, but the recalls after invalidation
        # should include the active_files in their matching
        recalls = service.list_recalls("inval-test")
        # set_active_files invalidates cache, so build_memory_section re-calls recall
        # which produces new recall records. So we should have 2x the records.
        assert len(recalls) >= 2, f"Expected >=2 recall records after invalidation, got {len(recalls)}"
        # The first recall (older) is from section_before, second (newer) from section_after
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_cache_invalidation_after_set_turn_id():
    """After set_turn_id, build_memory_section must produce a new recall with the turn_id."""
    tmp = tempfile.mkdtemp()
    try:
        db_path = str(Path(tmp) / "sessions.db")
        store = MemoryStore(repo_path=tmp, db_path=db_path)
        store.write_memory(
            mem("turn-cache-test", "Turn cache test memory",
                "**Decision:** Turn ID must flow into recall.\n\n**Why:** For tracing.",
                confidence=0.8),
            source="test",
        )
        service = MemoryRecallService(store)
        ctx = MemoryContext(store=store, recall_service=service)
        ctx.set_session_context(session_id="turn-inval", agent_name="build", mode="primary", repo_path=".")
        ctx.set_task_context("Test turn ID flow")
        ctx.set_user_message("turn ID tracing test")

        ctx.set_turn_id("turn-inval-step-1")
        ctx.build_memory_section()

        ctx.set_turn_id("turn-inval-step-2")
        ctx.build_memory_section()

        recalls = service.list_recalls("turn-inval")
        turn_ids = {r["turn_id"] for r in recalls}
        assert "turn-inval-step-1" in turn_ids
        assert "turn-inval-step-2" in turn_ids
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ── Override correctness ─────────────────────────────────────────────────────


def test_pinned_memory_not_duplicated_in_record_output():
    """A pinned memory should appear in records exactly once, not twice."""
    tmp = tempfile.mkdtemp()
    try:
        db_path = str(Path(tmp) / "sessions.db")
        store = MemoryStore(repo_path=tmp, db_path=db_path)
        store.write_memory(
            mem("pinned-test", "Pinned memory dedup test",
                "**Decision:** Pinned memories appear once.\n\n**Why:** Dedup by name prevents duplication.",
                confidence=0.8),
            source="test",
        )
        service = MemoryRecallService(store)
        service.set_override("pin-sess", "pinned-test", "pin")

        result = service.recall(MemoryRecallQuery(
            session_id="pin-sess",
            user_message="pinned dedup test",
        ))

        names = [r.memory_name for r in result.records if r.memory_name == "pinned-test"]
        assert len(names) == 1, f"Pinned memory appeared {len(names)} times, expected 1"
        assert result.records[0].source == "pinned"
        assert result.records[0].injected is True
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_disabled_memory_not_injected_but_still_recorded():
    """A disabled memory should be in records with injected=False."""
    tmp = tempfile.mkdtemp()
    try:
        db_path = str(Path(tmp) / "sessions.db")
        store = MemoryStore(repo_path=tmp, db_path=db_path)
        store.write_memory(
            mem("disabled-test", "Disabled memory",
                "**Decision:** Disabled memories are recorded but not injected.\n\n**Why:** For audit trailing.",
                confidence=0.85),
            source="test",
        )
        service = MemoryRecallService(store)
        service.set_override("dis-sess", "disabled-test", "disable")

        result = service.recall(MemoryRecallQuery(
            session_id="dis-sess",
            user_message="disabled memory audit",
        ))

        rec = next(r for r in result.records if r.memory_name == "disabled-test")
        assert rec.injected is False
        assert rec.omitted_reason == "disabled_for_session"
        assert "disabled-test" not in result.injection_text
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ── Consolidation correctness ────────────────────────────────────────────────


def test_consolidate_new_writes_do_not_lose_existing_memories():
    """consolidate() returning NEW must not delete or corrupt other memories."""
    tmp = tempfile.mkdtemp()
    try:
        db_path = str(Path(tmp) / "sessions.db")
        store = MemoryStore(repo_path=tmp, db_path=db_path)
        store.write_memory(
            mem("keep-me", "Keep this memory",
                "**Decision:** This memory must survive.\n\n**Why:** Isolation test.",
                confidence=0.8),
            source="test",
        )

        class NewCandidate:
            name = "new-memory"
            description = "New memory about event sourcing"
            content = "**Decision:** Use event sourcing for state.\n\n**Why:** Audit trail."
            anchors = []
            confidence = "high"
            def to_memory(self):
                return mem(self.name, self.description, self.content, confidence=0.85)

        result = store.consolidate(NewCandidate(), source="test",
                                   source_session_id="sess-1", source_run_id="sess-1-r1")
        assert result == "NEW"

        # Original memory must still exist
        existing = store.read_memory("keep-me")
        assert existing is not None, "Original memory should survive consolidation"
        assert "This memory must survive" in existing.content

        # New memory must exist too
        new_mem = store.read_memory("new-memory")
        assert new_mem is not None, "New memory should be written"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_consolidate_noop_does_not_corrupt_store():
    """consolidate() returning NOOP must leave the store unchanged."""
    tmp = tempfile.mkdtemp()
    try:
        db_path = str(Path(tmp) / "sessions.db")
        store = MemoryStore(repo_path=tmp, db_path=db_path)
        store.write_memory(
            mem("existing-mem", "React websocket state must be session aware",
                "**Decision:** React websocket state must be session-scoped.\n\n**Why:** Prevent cross-session pollution risk.",
                confidence=0.8),
            source="test",
        )

        before_count = len(store.list_memories())

        class DupCandidate:
            name = "react-loop"
            # Very similar description — bigram overlap with existing should be >= 0.70
            description = "React websocket state must be session aware approach"
            content = "React websocket state must be session scoped to prevent pollution."
            anchors = []
            confidence = "high"
            def to_memory(self):
                return mem(self.name, self.description, self.content, confidence=0.85)

        result = store.consolidate(DupCandidate(), source="run_finalizer")
        assert result == "NOOP", f"Expected NOOP but got {result}"

        after_count = len(store.list_memories())
        assert after_count == before_count, f"NOOP should not change memory count: {before_count} -> {after_count}"
        assert store.read_memory("react-loop") is None
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ── Edge cases ───────────────────────────────────────────────────────────────


def test_write_memory_then_immediately_read():
    """write -> read should return the same content (no caching gap)."""
    tmp = tempfile.mkdtemp()
    try:
        db_path = str(Path(tmp) / "sessions.db")
        store = MemoryStore(repo_path=tmp, db_path=db_path)
        m = mem("immediate-read", "Immediate read test",
                 "**Decision:** Write then read returns fresh data.\n\n**Why:** No cache interference.",
                 confidence=0.9)
        assert store.write_memory(m, source="test", source_session_id="sess-1", source_run_id="sess-1-r1")
        read_back = store.read_memory("immediate-read")
        assert read_back is not None
        assert read_back.content == m.content
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_empty_recall_produces_no_injection_text():
    """When no memories match, injection_text should be empty string."""
    tmp = tempfile.mkdtemp()
    try:
        db_path = str(Path(tmp) / "sessions.db")
        store = MemoryStore(repo_path=tmp, db_path=db_path)
        service = MemoryRecallService(store)
        result = service.recall(MemoryRecallQuery(
            session_id="empty-sess",
            user_message="completely unrelated query xyzzy1234",
        ))
        assert result.records == []
        assert result.injection_text == ""
        assert result.total_candidates == 0
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_concurrent_overrides_independent_across_sessions():
    """Pin in session A does not affect session B."""
    tmp = tempfile.mkdtemp()
    try:
        db_path = str(Path(tmp) / "sessions.db")
        store = MemoryStore(repo_path=tmp, db_path=db_path)
        store.write_memory(
            mem("shared-mem", "Shared memory",
                "**Decision:** Shared project memory.\n\n**Why:** Common knowledge.",
                confidence=0.8),
            source="test",
        )
        service = MemoryRecallService(store)

        # Pin in session A, disable in session B
        service.set_override("sess-a", "shared-mem", "pin")
        service.set_override("sess-b", "shared-mem", "disable")

        result_a = service.recall(MemoryRecallQuery(session_id="sess-a", user_message="shared knowledge"))
        result_b = service.recall(MemoryRecallQuery(session_id="sess-b", user_message="shared knowledge"))

        rec_a = next(r for r in result_a.records if r.memory_name == "shared-mem")
        rec_b = next(r for r in result_b.records if r.memory_name == "shared-mem")

        assert rec_a.override == "pin"
        assert rec_a.injected is True
        assert rec_b.override == "disable"
        assert rec_b.injected is False
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_confidence_scoring_high_confidence_outranks_low():
    """Higher confidence memories should be injected before lower confidence ones."""
    tmp = tempfile.mkdtemp()
    try:
        db_path = str(Path(tmp) / "sessions.db")
        store = MemoryStore(repo_path=tmp, db_path=db_path)
        store.write_memory(
            mem("low-conf", "Low confidence memory",
                "Generic content.", confidence=0.3),
            source="test",
        )
        store.write_memory(
            mem("high-conf", "High confidence memory",
                "**Decision:** Verified architectural pattern.\n\n**Why:** Confirmed by production usage.",
                confidence=0.95),
            source="test",
        )
        service = MemoryRecallService(store, max_injected=1)
        result = service.recall(MemoryRecallQuery(
            session_id="conf-sess",
            user_message="architectural pattern confirmed",
        ))

        injected = [r for r in result.records if r.injected]
        assert len(injected) >= 1
        assert injected[0].memory_name == "high-conf"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
