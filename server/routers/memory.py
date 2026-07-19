"""
Memory router — CRUD for long-term memory, backed by SQLite.

Mounted under ``/api/memory``.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── Schemas ────────────────────────────────────────────────────────────────


class MemoryItemResponse(BaseModel):
    """A single memory item (summary, no content)."""

    name: str = Field(description="Memory slug.")
    description: str = Field(description="One-line summary.")
    type: str = Field(description="user | feedback | project | reference.")
    status: str = Field(description="active | deprecated.")
    scope: str = Field(description="session | project | global.")
    confidence: float = Field(description="0.0–1.0.")
    access_count: int = Field(description="Times accessed.")
    updated_at: str = Field(description="ISO-8601.")


class MemoryDetailResponse(MemoryItemResponse):
    """Full memory with content."""

    content: str = Field(description="Markdown body.")
    source: str = Field(default="", description="Origin.")
    source_session_id: str = Field(default="", description="Session that created it.")


class MemoryListResponse(BaseModel):
    """List + overview."""

    items: list[MemoryItemResponse]
    overview: dict = Field(description="Aggregate stats.")


class MemoryCreateRequest(BaseModel):
    """Request body for POST /api/memory."""

    name: str = Field(min_length=1, description="Slug.")
    description: str = Field(min_length=1, description="One-line summary.")
    content: str = Field(default="", description="Markdown body.")
    type: str = Field(default="project", description="user | feedback | project | reference.")
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class MemoryUpdateRequest(BaseModel):
    """Request body for PATCH /api/memory/{name}."""

    description: str | None = None
    content: str | None = None
    type: str | None = None
    status: str | None = None
    confidence: float | None = None


# ── Router ─────────────────────────────────────────────────────────────────


def create_memory_router(get_service: Any) -> APIRouter:
    """Create the memory router with dependency injection."""
    router = APIRouter(prefix="/api/memory", tags=["memory"])

    def _store(service):
        return getattr(service, "_memory_store", None)

    def _db(service):
        return getattr(service, "_storage", None)

    # ── GET /api/memory ─────────────────────────────────────────────────

    @router.get("", response_model=MemoryListResponse)
    async def list_memories(
        type: str | None = None,
        status: str | None = None,
        scope: str | None = None,
        confidence_min: float | None = None,
        limit: int = 100,
        offset: int = 0,
        service=Depends(get_service),
    ) -> dict:
        """List all memories with optional filters and aggregate overview.

        **Query Parameters:**
        - ``type`` (str, optional): ``user`` | ``feedback`` | ``project`` | ``reference``.
        - ``status`` (str, optional): ``active`` | ``deprecated``.
        - ``scope`` (str, optional): ``session`` | ``project`` | ``global``.
        - ``confidence_min`` (float, optional): Minimum confidence filter.
        - ``limit`` (int, default 100): Max results.
        - ``offset`` (int, default 0): Pagination.

        **Response (200):** ``{ items: [...], overview: {...} }``
        """
        db = _db(service)
        if db is None:
            return {"items": [], "overview": {}}

        rows = db.query_memories(
            type_=type, status=status, scope=scope,
            confidence_min=confidence_min, limit=limit, offset=offset,
        )
        items = [
            {
                "name": r["name"], "description": r["description"],
                "type": r["type"], "status": r["status"],
                "scope": r["scope"], "confidence": r["confidence"],
                "access_count": r["access_count"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]
        overview = db.get_memory_overview()
        return {"items": items, "overview": overview}

    # ── GET /api/memory/{name} ──────────────────────────────────────────

    @router.get("/{name}", response_model=MemoryDetailResponse)
    async def get_memory(
        name: str,
        service=Depends(get_service),
    ) -> dict:
        """Get a single memory with full content from DB."""
        db = _db(service)
        if db is None:
            raise HTTPException(status_code=503, detail="Storage not available")
        row = db.get_memory_entry(name)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Memory not found: {name}")
        return {
            "name": row["name"], "description": row["description"],
            "content": row["content"], "type": row["type"],
            "status": row["status"], "scope": row["scope"],
            "confidence": row["confidence"],
            "access_count": row["access_count"],
            "source": row["source"],
            "source_session_id": row["source_session_id"],
            "updated_at": row["updated_at"],
        }

    # ── POST /api/memory ───────────────────────────────────────────────

    @router.post("", status_code=201)
    async def create_memory(
        body: MemoryCreateRequest,
        service=Depends(get_service),
    ) -> dict:
        """Create a new memory (file + DB)."""
        store = _store(service)
        if store is None:
            raise HTTPException(status_code=503, detail="Memory store not available")

        from memory.models import Memory, MemoryMetadata, MemoryType, MemoryStatus, MemoryScope

        mem = Memory(
            name=body.name,
            description=body.description,
            content=body.content,
            metadata=MemoryMetadata(
                type=MemoryType(body.type) if body.type in ("user", "feedback", "project", "reference") else MemoryType.PROJECT,
                status=MemoryStatus.ACTIVE,
                scope=MemoryScope.PROJECT,
                confidence=body.confidence,
            ),
        )
        ok = store.write_memory(mem, source="web_api")
        if not ok:
            raise HTTPException(status_code=409, detail=f"Memory '{body.name}' already exists")
        # Sync to DB
        db = _db(service)
        if db:
            db.upsert_memory_entry(
                name=mem.name, description=mem.description, content=mem.content,
                type_=mem.metadata.type, status=mem.metadata.status,
                scope=mem.metadata.scope, confidence=mem.metadata.confidence,
                source="web_api",
            )
        return {"name": body.name, "status": "created"}

    # ── PATCH /api/memory/{name} ───────────────────────────────────────

    @router.patch("/{name}")
    async def update_memory(
        name: str,
        body: MemoryUpdateRequest,
        service=Depends(get_service),
    ) -> dict:
        """Update an existing memory (file + DB)."""
        store = _store(service)
        if store is None:
            raise HTTPException(status_code=503, detail="Memory store not available")
        mem = store.read_memory(name)
        if mem is None:
            raise HTTPException(status_code=404, detail=f"Memory not found: {name}")

        changed = False
        if body.description is not None:
            mem.description = body.description; changed = True
        if body.content is not None:
            mem.content = body.content; changed = True
        if body.confidence is not None:
            mem.metadata.confidence = body.confidence; changed = True
        if body.type is not None:
            from memory.models import MemoryType
            mem.metadata.type = MemoryType(body.type) if body.type in ("user", "feedback", "project", "reference") else mem.metadata.type
            changed = True
        if body.status is not None:
            from memory.models import MemoryStatus
            mem.metadata.status = MemoryStatus(body.status) if body.status in ("active", "deprecated") else MemoryStatus.ACTIVE
            changed = True
        if changed:
            store.write_memory(mem, source="web_api")
            # Sync to DB
            db = _db(service)
            if db:
                db.upsert_memory_entry(
                    name=mem.name, description=mem.description, content=mem.content,
                    type_=mem.metadata.type, status=mem.metadata.status,
                    scope=mem.metadata.scope, confidence=mem.metadata.confidence,
                    access_count=mem.metadata.access_count,
                )
        return {"name": name, "status": "updated", "changed": changed}

    # ── DELETE /api/memory/{name} ──────────────────────────────────────

    @router.delete("/{name}")
    async def delete_memory(
        name: str,
        service=Depends(get_service),
    ) -> dict:
        """Delete a memory (file + DB)."""
        store = _store(service)
        if store is None:
            raise HTTPException(status_code=503, detail="Memory store not available")
        ok = store.delete_memory(name)
        if not ok:
            raise HTTPException(status_code=404, detail=f"Memory not found: {name}")
        db = _db(service)
        if db:
            db.delete_memory_entry(name)
        return {"name": name, "deleted": True}

    # ── POST /api/memory/sync ─────────────────────────────────────────

    @router.post("/sync")
    async def sync_memories(
        service=Depends(get_service),
    ) -> dict:
        """Manually trigger file→DB sync."""
        db = _db(service)
        if db is None:
            raise HTTPException(status_code=503, detail="Storage not available")
        count = db.sync_memory_from_files(service.repo_path)
        return {"synced": count}

    return router
