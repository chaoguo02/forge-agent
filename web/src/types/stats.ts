/** Aggregate stats for a completed session */
export interface SessionStats {
  session_id: string;
  agent_name: string;
  total_steps: number;
  total_tokens: number;
  total_duration_ms: number;
  status: string;
  tool_summary: Record<string, number>;
  created_at: string;
}

/** One step in a session's execution log */
export interface StepLog {
  id: number;
  session_id: string;
  step_number: number;
  tool_name: string;
  tool_params: string;
  status: string;
  duration_ms: number;
  tokens: number;
  timestamp: string;
}

/** Daily aggregate stats */
export interface DailyRollup {
  date: string;
  session_count: number;
  total_tokens: number;
  total_duration_ms: number;
  tool_summary: Record<string, number>;
  status_summary: Record<string, number>;
}

/** One file diff from a session */
export interface SessionDiff {
  id: number;
  session_id: string;
  step_number: number;
  file_path: string;
  diff_content: string;
  status: "pending" | "approved" | "rejected";
  review_comment: string;
  created_at: string;
  /** Enriched fields from /api/diffs/pending */
  session_title?: string;
  session_agent?: string;
}
