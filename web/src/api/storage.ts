import { apiGet } from "./client";

export interface StorageStats {
  backend: string;
  total_sessions: number;
  total_messages: number;
  total_memories?: number;
  db_size_bytes: number | null;
}

export function getStorageStats(signal?: AbortSignal): Promise<StorageStats> {
  return apiGet("/api/storage/stats", signal);
}
