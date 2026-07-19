"""
PlanRevisionService — independent storage for plan revisions.

Revisions are stored in a dedicated table outside session metadata
to avoid field bloat, concurrent overwrites, and size concerns.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PlanRevision:
    id: str = ""                # auto-generated: {session_id}_{revision}
    session_id: str = ""
    revision: int = 0
    content: str = ""           # full plan text
    content_hash: str = ""      # SHA256 for dedup
    parent_revision: int = 0    # 0 = original
    change_request: str = ""    # rejection reason / feedback
    created_at: str = ""
    status: str = "pending"     # pending | approved | rejected | superseded

    @classmethod
    def create(cls, session_id: str, revision: int, content: str,
               parent_revision: int = 0, change_request: str = "") -> "PlanRevision":
        return cls(
            id=f"{session_id}_{revision}",
            session_id=session_id,
            revision=revision,
            content=content,
            content_hash=hashlib.sha256(content.encode()).hexdigest()[:16],
            parent_revision=parent_revision,
            change_request=change_request,
            created_at=datetime.now(timezone.utc).isoformat(),
            status="pending",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "revision": self.revision,
            "content": self.content,
            "content_hash": self.content_hash,
            "parent_revision": self.parent_revision,
            "change_request": self.change_request,
            "created_at": self.created_at,
            "status": self.status,
        }


class PlanRevisionService:
    """Manage plan revisions with dedicated storage.

    Uses a JSON file per session under .forge-agent/plan-revisions/
    to avoid DB migration complexity.  Each session's revisions are
    stored in {session_id}.json.
    """

    def __init__(self, repo_path: str) -> None:
        from pathlib import Path
        self._dir = Path(repo_path) / ".forge-agent" / "plan-revisions"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, session_id: str) -> "Path":
        from pathlib import Path
        return self._dir / f"{session_id}.json"

    def _load(self, session_id: str) -> list[dict]:
        path = self._path_for(session_id)
        if not path.is_file():
            return []
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def _save(self, session_id: str, revisions: list[dict]) -> None:
        self._path_for(session_id).write_text(
            json.dumps(revisions, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def append_revision(self, session_id: str, content: str,
                        parent_revision: int = 0,
                        change_request: str = "") -> PlanRevision:
        """Create a new plan revision and persist it."""
        revisions = self._load(session_id)
        rev_num = len(revisions) + 1
        rev = PlanRevision.create(
            session_id, rev_num, content,
            parent_revision=parent_revision,
            change_request=change_request,
        )
        revisions.append(rev.to_dict())
        self._save(session_id, revisions)
        logger.info("Plan revision %d saved for session %s", rev_num, session_id[:8])
        return rev

    def mark_status(self, session_id: str, revision: int, status: str) -> bool:
        """Update a revision's status (approved/rejected/superseded)."""
        revisions = self._load(session_id)
        for r in revisions:
            if r["revision"] == revision:
                r["status"] = status
                self._save(session_id, revisions)
                return True
        return False

    def list_revisions(self, session_id: str) -> list[dict]:
        """Return all revisions for a session, oldest first."""
        return self._load(session_id)

    def get_revision(self, session_id: str, revision: int) -> dict | None:
        """Get a specific revision by number."""
        for r in self._load(session_id):
            if r["revision"] == revision:
                return r
        return None

    def get_latest(self, session_id: str) -> dict | None:
        revisions = self._load(session_id)
        return revisions[-1] if revisions else None

    def compute_diff(self, session_id: str, from_rev: int, to_rev: int) -> dict:
        """Compute a simple line-level diff between two revisions."""
        from_r = self.get_revision(session_id, from_rev)
        to_r = self.get_revision(session_id, to_rev)
        if not from_r or not to_r:
            return {"error": "Revision not found"}

        import difflib
        from_lines = from_r["content"].splitlines(keepends=True)
        to_lines = to_r["content"].splitlines(keepends=True)
        diff = list(difflib.unified_diff(
            from_lines, to_lines,
            fromfile=f"revision {from_rev}",
            tofile=f"revision {to_rev}",
        ))
        return {
            "from_revision": from_rev,
            "to_revision": to_rev,
            "diff": "".join(diff),
            "added_lines": sum(1 for l in diff if l.startswith("+") and not l.startswith("+++")),
            "removed_lines": sum(1 for l in diff if l.startswith("-") and not l.startswith("---")),
        }
