from __future__ import annotations

from agent.task import Task
from memory.extractor import MemoryCandidate, MemoryExtractor
from memory.models import Anchor


def test_low_confidence_candidate_is_rejected():
    candidate = MemoryCandidate(
        type="project",
        name="low-confidence",
        description="A durable decision",
        content="**Decision:** Use active recall because it avoids repeated context setup.",
        confidence="low",
        confidence_reason="Unverified",
    )

    assert not MemoryExtractor._passes_discipline(candidate, None)


def test_vague_unanchored_summary_is_rejected():
    candidate = MemoryCandidate(
        type="project",
        name="task-completed",
        description="Task completed",
        content="Task completed successfully. Made changes and updated files for the current session.",
        confidence="high",
    )

    assert not MemoryExtractor._passes_discipline(candidate, None)


def test_durable_anchored_decision_is_accepted():
    candidate = MemoryCandidate(
        type="project",
        name="session-aware-recall",
        description="Memory recall must be session-aware",
        content=(
            "**Decision:** Memory recall must be scoped per session.\n\n"
            "**Why:** Shared recall state can leak prompt context across concurrent sessions.\n"
            "**How to apply:** Include session_id in recall queries and cache keys."
        ),
        anchors=[Anchor(kind="file", path="memory/context.py")],
        confidence="high",
        confidence_reason="Verified architectural decision from implementation.",
    )

    assert MemoryExtractor._passes_discipline(candidate, None)


def test_candidate_memory_confidence_score_and_reason_are_preserved():
    candidate = MemoryCandidate(
        type="project",
        name="recall-discipline",
        description="Automatic memories require a confidence reason",
        content=(
            "**Decision:** Automatic memory extraction must include a reason.\n\n"
            "**Why:** Users need to audit whether the memory is durable."
        ),
        confidence="medium",
        confidence_reason="Non-obvious memory policy useful across future sessions.",
    )

    memory = candidate.to_memory()

    assert memory.metadata.confidence == 0.65
    assert "**Confidence reason:** Non-obvious memory policy" in memory.content


def test_rule_fallback_no_longer_writes_generic_completed_task():
    extractor = MemoryExtractor(enable_rule_fallback=True)
    task = Task(description="Fix one typo", repo_path=".")

    candidates = extractor._extract_rule_fallback(task, None, "Completed successfully")

    assert candidates == []
