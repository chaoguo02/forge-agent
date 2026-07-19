"""
Memory router — CRUD for long-term memory.

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

    name: str = Field(description="Memory slug (filename without .md).")
    description: str = Field(description="One-line summary.")
    type: str = Field(description="user | feedback | project | reference.")
    status: str = Field(description="active | deprecated.")
    scope: str = Field(description="session | project | global.")
    confidence: float = Field(description="0.0–1.0.")
    updated_at: str = Field(description="ISO-8601.")


class MemoryDetailResponse(MemoryItemResponse):
    """Full memory with content."""

    content: str = Field(description="Markdown body.")
    anchors: list[dict] = Field(default_factory=list, description="File/symbol anchors.")


class MemoryCreateRequest(BaseModel):
    """Request body for POST /api/memory."""

    name: str = Field(min_length=1, description="Slug — also the filename.")
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

    # ── GET /api/memory ─────────────────────────────────────────────────

    @router.get("", response_model=list[MemoryItemResponse])
    async def list_memories(
        type: str | None = None,
        status: str | None = None,
        scope: str | None = None,
        service=Depends(get_service),
    ) -> list[dict]:
        """List all memories with optional filters.

        **Query Parameters:**
        - ``type`` (str, optional): ``user`` | ``feedback`` | ``project`` | ``reference``.
        - ``status`` (str, optional): ``active`` | ``deprecated``.
        - ``scope`` (str, optional): ``session`` | ``project`` | ``global``.
        """
        store = _store(service)
        if store is None:
            return []
        summaries = store.list_memories()
        results = []
        for s in summaries:
            # Read full memory to get metadata fields
            mem = store.read_memory(s.name)
            meta = mem.metadata if mem else None
            if type and (meta is None or meta.type != type):
                continue
            if status and (meta is None or meta.status != status):
                continue
            if scope and (meta is None or meta.scope != scope):
                continue
            results.append({
                "name": s.name,
                "description": s.description,
                "type": meta.type if meta else s.type,
                "status": meta.status if meta else "active",
                "scope": meta.scope if meta else "project",
                "confidence": meta.confidence if meta else 0.7,
                "updated_at": s.updated_at,
            })
        return results

    # ── GET /api/memory/{name} ──────────────────────────────────────────

    @router.get("/{name}", response_model=MemoryDetailResponse)
    async def get_memory(
        name: str,
        service=Depends(get_service),
    ) -> dict:
        """Get a single memory with full content."""
        store = _store(service)
        if store is None:
            raise HTTPException(status_code=503, detail="Memory store not available")
        mem = store.read_memory(name)
        if mem is None:
            raise HTTPException(status_code=404, detail=f"Memory not found: {name}")
        return {
            "name": mem.name,
            "description": mem.description,
            "content": mem.content,
            "type": mem.metadata.type,
            "status": mem.metadata.status,
            "scope": mem.metadata.scope,
            "confidence": mem.metadata.confidence,
            "updated_at": mem.updated_at,
            "anchors": [a.to_dict() for a in mem.anchors],
        }

    # ── POST /api/memory ───────────────────────────────────────────────

    @router.post("", status_code=201)
    async def create_memory(
        body: MemoryCreateRequest,
        service=Depends(get_service),
    ) -> dict:
        """Create a new memory."""
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
        return {"name": body.name, "status": "created"}

    # ── PATCH /api/memory/{name} ───────────────────────────────────────

    @router.patch("/{name}")
    async def update_memory(
        name: str,
        body: MemoryUpdateRequest,
        service=Depends(get_service),
    ) -> dict:
        """Update an existing memory."""
        store = _store(service)
        if store is None:
            raise HTTPException(status_code=503, detail="Memory store not available")
        mem = store.read_memory(name)
        if mem is None:
            raise HTTPException(status_code=404, detail=f"Memory not found: {name}")

        changed = False
        if body.description is not None:
            mem.description = body.description
            changed = True
        if body.content is not None:
            mem.content = body.content
            changed = True
        if body.confidence is not None:
            mem.metadata.confidence = body.confidence
            changed = True
        if body.status is not None:
            from memory.models import MemoryStatus
            mem.metadata.status = MemoryStatus(body.status) if body.status in ("active", "deprecated") else MemoryStatus.ACTIVE
            changed = True
        if changed:
            store.write_memory(mem, source="web_api")
        return {"name": name, "status": "updated", "changed": changed}

    # ── DELETE /api/memory/{name} ──────────────────────────────────────

    @router.delete("/{name}")
    async def delete_memory(
        name: str,
        service=Depends(get_service),
    ) -> dict:
        """Delete a memory."""
        store = _store(service)
        if store is None:
            raise HTTPException(status_code=503, detail="Memory store not available")
        ok = store.delete_memory(name)
        if not ok:
            raise HTTPException(status_code=404, detail=f"Memory not found: {name}")
        return {"name": name, "deleted": True}

    return router
