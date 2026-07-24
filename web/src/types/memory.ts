export type MemoryType = "user" | "feedback" | "project" | "reference";
export type MemoryStatus = "active" | "deprecated";
export type MemoryScope = "session" | "project" | "global";
export type MemoryLayer = "project" | "global" | "archive";

export interface MemoryItem {
  source?: string;
  source_session_id?: string;
  created_at?: string;
  name: string;
  description: string;
  type: MemoryType;
  status: MemoryStatus;
  scope: MemoryScope;
  layer?: MemoryLayer;
  confidence: number;
  updated_at: string;
  validated_at?: string;
  ttl_seconds?: number | null;
  expires_at?: string;
  access_count: number;
  anchors_count: number;
  preview?: string;
  content?: string;
}

export interface MemoryOverview {
  enabled: boolean;
  preview: boolean;
  total: number;
  active: number;
  deprecated: number;
  archived: number;
  expiring: number;
  by_type: Record<MemoryType, number>;
  by_scope: Record<MemoryScope, number>;
  by_layer: Record<MemoryLayer, number>;
}

export interface MemoryRecallItem {
  session_id: string;
  memory_name: string;
  source: "always" | "semantic" | "scoped" | "pinned" | string;
  score: number;
  reason: string;
  confidence: number;
  scope: MemoryScope | string;
  injected: boolean;
  omitted_reason?: string;
  created_at: string;
  description?: string;
  type?: MemoryType | string;
  override?: string;
}

export interface MemoryRecallResponse {
  session_id: string;
  items: MemoryRecallItem[];
  records?: MemoryRecallItem[];
  injection_text?: string;
  total_candidates?: number;
  created_at?: string;
}

export interface MemoryResponse {
  overview: MemoryOverview;
  items: MemoryItem[];
}

