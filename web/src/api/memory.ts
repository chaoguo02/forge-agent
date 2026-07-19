import { apiGet, apiPost, apiPatch, apiDelete } from "./client";
import type { MemoryItem, MemoryOverview, MemoryResponse } from "../types/memory";

/** Fetch all memories from the API and build an overview. */
export async function getMemorySnapshot(): Promise<MemoryResponse> {
  try {
    const items: MemoryItem[] = await apiGet("/api/memory");
    const overview = buildOverview(items);
    return { overview, items };
  } catch {
    return { overview: emptyOverview(), items: [] };
  }
}

/** Fetch a single memory with full content. */
export async function getMemoryDetail(name: string): Promise<Record<string, unknown>> {
  return apiGet(`/api/memory/${encodeURIComponent(name)}`);
}

/** Create a new memory. */
export async function createMemory(data: {
  name: string; description: string; content?: string; type?: string;
}): Promise<{ name: string; status: string }> {
  return apiPost("/api/memory", data);
}

/** Update an existing memory. */
export async function updateMemory(name: string, data: Record<string, unknown>): Promise<{ name: string; status: string }> {
  return apiPatch(`/api/memory/${encodeURIComponent(name)}`, data);
}

/** Delete a memory. */
export async function deleteMemory(name: string): Promise<{ name: string; deleted: boolean }> {
  return apiDelete(`/api/memory/${encodeURIComponent(name)}`);
}

function buildOverview(items: MemoryItem[]): MemoryOverview {
  const byType: Record<string, number> = { user: 0, feedback: 0, project: 0, reference: 0 };
  const byScope: Record<string, number> = { session: 0, project: 0, global: 0 };
  const byLayer: Record<string, number> = { project: 0, global: 0, archive: 0 };
  let active = 0, deprecated = 0, archived = 0, expiring = 0;
  const now = Date.now();

  for (const item of items) {
    byType[item.type] = (byType[item.type] || 0) + 1;
    byScope[item.scope] = (byScope[item.scope] || 0) + 1;
    const layer = item.status === "deprecated" ? "archive" : "project";
    byLayer[layer] = (byLayer[layer] || 0) + 1;
    if (item.status === "active") active++;
    if (item.status === "deprecated") deprecated++;
    if (layer === "archive") archived++;
    if (item.expires_at) {
      const ms = new Date(item.expires_at).getTime() - now;
      if (ms > 0 && ms < 7 * 86400000) expiring++;
    }
  }
  return {
    enabled: true, preview: false, total: items.length,
    active, deprecated, archived, expiring,
    by_type: byType as MemoryOverview["by_type"],
    by_scope: byScope as MemoryOverview["by_scope"],
    by_layer: byLayer as MemoryOverview["by_layer"],
  };
}

function emptyOverview(): MemoryOverview {
  return {
    enabled: true, preview: false, total: 0, active: 0, deprecated: 0,
    archived: 0, expiring: 0,
    by_type: { user: 0, feedback: 0, project: 0, reference: 0 },
    by_scope: { session: 0, project: 0, global: 0 },
    by_layer: { project: 0, global: 0, archive: 0 },
  };
}
