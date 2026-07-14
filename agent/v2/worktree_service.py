"""Fail-closed Git worktree isolation for forked agents."""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass
from enum import Enum
from typing import Any

from agent.v2.models import AgentIsolation

logger = logging.getLogger(__name__)


class WorktreeIsolationError(RuntimeError):
    """Raised when declared worktree isolation cannot be provisioned."""


class WorktreeChange(str, Enum):
    NONE = "none"
    UNCOMMITTED = "uncommitted"
    COMMITTED = "committed"
    BOTH = "both"
    UNKNOWN = "unknown"


class WorktreeMergeStatus(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    NO_CHANGES = "no_changes"
    MERGED = "merged"
    FAILED = "failed"


@dataclass(frozen=True)
class WorktreeMergeResult:
    status: WorktreeMergeStatus
    error: str = ""


def _get_runtime(repo_path: str) -> Any:
    from tools.runtime import LocalRuntime
    return LocalRuntime(workspace_root=repo_path)


def _worktree_root(repo_path: str) -> str:
    from runtime.state_paths import ProjectStatePaths
    return str(ProjectStatePaths.for_project(repo_path).worktrees)


def create_worktree(
    repo_path: str,
    definition_name: str,
    agent_id: str,
    *,
    isolation: AgentIsolation = AgentIsolation.FORK,
    runtime: Any | None = None,
) -> tuple[Any | None, str]:
    """Provision declared isolation and return its effective project root."""
    if isolation is not AgentIsolation.WORKTREE:
        return None, repo_path
    try:
        from tools.snapshot import WorktreeManager
        manager = WorktreeManager(
            repo_path,
            runtime=runtime or _get_runtime(repo_path),
            worktree_root=_worktree_root(repo_path),
        )
        worktree = manager.create(f"agent-{definition_name}-{agent_id}")
        logger.info(
            "Worktree created for '%s': %s (branch: %s)",
            definition_name, worktree.path, worktree.branch,
        )
        return worktree, worktree.path
    except Exception as exc:
        raise WorktreeIsolationError(
            f"Worktree isolation failed for {definition_name!r}: {exc}"
        ) from exc


def inspect_changes(worktree: Any, runtime: Any | None = None) -> WorktreeChange:
    """Inspect tracked, untracked, and committed changes using Git facts."""
    if worktree is None:
        return WorktreeChange.NONE
    try:
        child_runtime = runtime or _get_runtime(str(worktree.path))
        status = child_runtime.execute(
            "git", args=["status", "--porcelain", "--untracked-files=all"],
            cwd=worktree.path, timeout=30,
        )
        ahead = child_runtime.execute(
            "git", args=["rev-list", "--count", f"{worktree.base_branch}..HEAD"],
            cwd=worktree.path, timeout=30,
        )
        if not status.success or not ahead.success:
            return WorktreeChange.UNKNOWN
        has_uncommitted = bool(status.stdout.strip())
        has_committed = int(ahead.stdout.strip() or "0") > 0
        if has_uncommitted and has_committed:
            return WorktreeChange.BOTH
        if has_uncommitted:
            return WorktreeChange.UNCOMMITTED
        if has_committed:
            return WorktreeChange.COMMITTED
        return WorktreeChange.NONE
    except (OSError, TypeError, ValueError):
        return WorktreeChange.UNKNOWN


def merge_worktree(
    worktree: Any,
    repo_path: str,
    definition_name: str,
    prompt: str = "",
    runtime: Any | None = None,
) -> WorktreeMergeResult:
    """Commit child changes and merge them through project-bound runtimes."""
    if worktree is None:
        return WorktreeMergeResult(WorktreeMergeStatus.NOT_APPLICABLE)
    change = inspect_changes(worktree)
    if change is WorktreeChange.UNKNOWN:
        return WorktreeMergeResult(
            WorktreeMergeStatus.FAILED,
            "Unable to determine worktree change state",
        )
    if change is WorktreeChange.NONE:
        return WorktreeMergeResult(WorktreeMergeStatus.NO_CHANGES)
    try:
        child_runtime = _get_runtime(str(worktree.path))
        if change in (WorktreeChange.UNCOMMITTED, WorktreeChange.BOTH):
            staged = child_runtime.execute(
                "git", args=["add", "-A"], cwd=worktree.path, timeout=30,
            )
            if not staged.success:
                return WorktreeMergeResult(
                    WorktreeMergeStatus.FAILED, staged.stderr or "git add failed",
                )
            message = f"Subagent {definition_name}: {prompt[:200]}"
            message_path = ""
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".txt", delete=False, encoding="utf-8",
                ) as handle:
                    handle.write(message)
                    message_path = handle.name
                committed = child_runtime.execute(
                    "git", args=["commit", "-F", message_path],
                    cwd=worktree.path, timeout=30,
                )
                if not committed.success:
                    return WorktreeMergeResult(
                        WorktreeMergeStatus.FAILED,
                        committed.stderr or "git commit failed",
                    )
            finally:
                if message_path:
                    try:
                        os.unlink(message_path)
                    except OSError:
                        pass

        from tools.snapshot import WorktreeManager
        parent_runtime = runtime or _get_runtime(repo_path)
        manager = WorktreeManager(
            repo_path,
            runtime=parent_runtime,
            worktree_root=_worktree_root(repo_path),
        )
        manager.merge(worktree, delete_after=False)
        logger.info("Worktree merged: %s -> %s", worktree.branch, repo_path)
        return WorktreeMergeResult(WorktreeMergeStatus.MERGED)
    except Exception as exc:
        logger.warning("Worktree merge failed: %s", exc)
        return WorktreeMergeResult(WorktreeMergeStatus.FAILED, str(exc))


def has_changes(worktree: Any, runtime: Any | None = None) -> bool:
    """Compatibility predicate backed by the typed Git fact state."""
    return inspect_changes(worktree, runtime) in {
        WorktreeChange.UNCOMMITTED,
        WorktreeChange.COMMITTED,
        WorktreeChange.BOTH,
    }


def discard_worktree(
    worktree: Any, repo_path: str, runtime: Any | None = None,
) -> None:
    if worktree is None:
        return
    try:
        from tools.snapshot import WorktreeManager
        manager = WorktreeManager(
            repo_path,
            runtime=runtime or _get_runtime(repo_path),
            worktree_root=_worktree_root(repo_path),
        )
        manager.discard(worktree)
    except Exception as exc:
        logger.debug("Worktree discard failed (non-critical): %s", exc)
