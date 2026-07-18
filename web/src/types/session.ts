export interface SessionSummary {
  id: string;
  agent_name: string;
  title: string;
  status: string;
  mode: string;
  summary: string;
  error: string;
  parent_id: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface SessionDetail {
  id: string;
  parent_id: string | null;
  root_id: string | null;
  agent_name: string;
  title: string;
  status: string;
  mode: string;
  summary: string;
  error: string;
  agent_kind: string;
  context_origin: string;
  execution_placement: string;
  workspace_mode: string;
  agent_depth: number;
  generation: number;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  metadata: Record<string, unknown>;
}

export interface ToolCall {
  name: string;
  params: Record<string, unknown>;
  id?: string;
}

export interface Message {
  role: "user" | "assistant" | "tool";
  content: string;
  tool_calls?: ToolCall[];
  tool_call_id?: string | null;
}

export interface ChatResponse {
  session_id: string;
  status: string;
  summary: string;
  steps_taken: number;
  total_tokens: number;
  error: string | null;
  termination_reason: string | null;
}

export interface EventItem {
  event_id: string;
  event_type: string;
  task_id: string;
  timestamp: string;
  payload: Record<string, unknown>;
}

export interface EventsResponse {
  events: EventItem[];
  total: number;
  has_more: boolean;
}

export interface WsMessage {
  type: string;
  payload?: Record<string, unknown>;
  timestamp?: string;
  event_id?: string;
  step?: number;
  action?: Record<string, unknown>;
  observation?: Record<string, unknown>;
  result?: Record<string, unknown>;
  error?: string;
}
