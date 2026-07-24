/**
 * Typed WebSocket event discriminated union.
 *
 * Mirrors server/events.py dataclass shapes.  The 'type' field is the
 * discriminator — handler maps use Extract<> for type narrowing.
 *
 * Pattern: CorvidAgent shared type layer + react-socket typed events.
 * Source: https://github.com/CorvidLabs/corvid-agent/issues/957
 */

// ── Status ──────────────────────────────────────────────────────────────

export interface WsStatusEvent {
  type: "status";
  status: "running" | "completed" | "failed" | "finish" | "gave_up" | "cancelled" | "compacted";
  message?: string;
  error?: string;
  result?: { summary?: string; steps_taken?: number; total_tokens?: number };
  timestamp?: string;
  step?: number;
  duration_ms?: number;
  token_estimate?: number;
  child_session_id?: string;
}

// ── Thought / Reflection ────────────────────────────────────────────────

export interface WsThoughtEvent {
  type: "thought";
  content: string;
  timestamp?: string;
  step?: number;
  duration_ms?: number;
  token_estimate?: number;
  child_session_id?: string;
}

export interface WsThoughtDeltaEvent {
  type: "thought_delta";
  text: string;
  timestamp?: string;
  step?: number;
  child_session_id?: string;
}

export interface WsReflectionEvent {
  type: "reflection";
  content: string;
  timestamp?: string;
  step?: number;
  duration_ms?: number;
  token_estimate?: number;
}

// ── Tool call / Observation ─────────────────────────────────────────────

export interface WsToolCallEvent {
  type: "tool_call";
  name: string;
  params?: Record<string, unknown>;
  id?: string;
  timestamp?: string;
  step?: number;
  duration_ms?: number;
  token_estimate?: number;
  child_session_id?: string;
}

export interface WsObservationEvent {
  type: "observation";
  tool_name?: string;
  output?: string;
  error?: string;
  status?: string;
  id?: string;
  paired?: boolean;
  diff?: string;
  timestamp?: string;
  step?: number;
  duration_ms?: number;
  token_estimate?: number;
  child_session_id?: string;
}

// ── Subagent ────────────────────────────────────────────────────────────

export interface WsSubagentStartEvent {
  type: "subagent_start";
  child_session_id: string;
  agent_name?: string;
  timestamp?: string;
  step?: number;
}

export interface WsSubagentStopEvent {
  type: "subagent_stop";
  child_session_id: string;
  status?: string;
  timestamp?: string;
  step?: number;
}

// ── Approval ────────────────────────────────────────────────────────────

export interface WsApprovalRequiredEvent {
  type: "approval_required";
  request_id: string;
  tool_name: string;
  params?: Record<string, unknown>;
  thought?: string;
  decision_reason?: string;
  tool_use_id?: string;
  permission_mode?: string;
  risk_level?: string;
  timestamp?: string;
  step?: number;
}

export interface WsApprovalTimeoutEvent {
  type: "approval_timeout";
  request_id: string;
  timestamp?: string;
}

// ── Plan ────────────────────────────────────────────────────────────────

export interface WsPlanReadyEvent {
  type: "plan_ready";
  plan_text?: string;
  contract?: Record<string, unknown> | null;
  revision?: number;
  max_revisions?: number;
  result?: { summary?: string; steps_taken?: number; total_tokens?: number };
  timestamp?: string;
  step?: number;
}

// ── Worktree ────────────────────────────────────────────────────────────

export interface WsWorktreeResolvedEvent {
  type: "worktree_resolved";
  child_session_id: string;
  action: string;
  status: string;
  message?: string;
  timestamp?: string;
  step?: number;
}

// ── Memory activity ─────────────────────────────────────────────────────

export interface WsMemoryRecallEvent {
  type: "memory_recall";
  injected_count: number;
  candidate_count: number;
  omitted_count: number;
  top_names: string[];
  timestamp?: string;
}

export interface WsMemoryWrittenEvent {
  type: "memory_written";
  name: string;
  description: string;
  source: string;
  confidence: number;
  timestamp?: string;
}

// ── Discriminated union ─────────────────────────────────────────────────

export type WsMessage =
  | WsStatusEvent
  | WsThoughtEvent
  | WsThoughtDeltaEvent
  | WsReflectionEvent
  | WsToolCallEvent
  | WsObservationEvent
  | WsSubagentStartEvent
  | WsSubagentStopEvent
  | WsApprovalRequiredEvent
  | WsApprovalTimeoutEvent
  | WsPlanReadyEvent
  | WsWorktreeResolvedEvent
  | WsMemoryRecallEvent
  | WsMemoryWrittenEvent;

// ── Typed handler utility ───────────────────────────────────────────────

/** Narrow a WsMessage to a specific subtype. */
export type WsMessageOfType<T extends WsMessage["type"]> = Extract<WsMessage, { type: T }>;

// ── Transport-level envelope ────────────────────────────────────────────

/**
 * WsMessage with optional trace sequence number injected by the backend
 * transport layer (EventBus WebSocket broadcast + /timeline REST).
 *
 * ``seq`` is NOT a domain property of individual event types — it is
 * a per-session monotonic counter that the backend stamps on every
 * event at persist/broadcast time.  Use this type in store handlers
 * and transport adapters; render components should use ``WsMessage``.
 */
export type WsEnvelope = WsMessage & { seq?: number };
