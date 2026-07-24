import { apiGet, apiDelete } from "./client";

export interface PlanEntry {
  filename: string;
  session_id: string | null;
  title: string;
  preview: string;
  size_bytes: number;
  created_at: string;
  session: {
    id: string;
    agent_name: string;
    title: string;
    status: string;
  } | null;
}

export interface PlanDetail extends PlanEntry {
  content: string;
}

export interface PlanListResponse {
  plans: PlanEntry[];
  total: number;
  has_more: boolean;
}

export interface PlanRevision {
  id: string;
  session_id: string;
  revision: number;
  content: string;
  content_hash: string;
  parent_revision: number;
  change_request: string;
  status: string;
  created_at: string;
}

export interface PlanRevisionDiff {
  from_revision: number;
  to_revision: number;
  from_content: string;
  to_content: string;
  diff: string;
}

export function listPlans(limit = 50, offset = 0): Promise<PlanListResponse> {
  return apiGet(`/api/plans?limit=${limit}&offset=${offset}`);
}

export function getPlan(filename: string): Promise<PlanDetail> {
  return apiGet(`/api/plans/${encodeURIComponent(filename)}`);
}

export function deletePlan(filename: string): Promise<{ filename: string; deleted: boolean }> {
  return apiDelete(`/api/plans/${encodeURIComponent(filename)}`);
}

export function listPlanRevisions(sessionId: string): Promise<PlanRevision[]> {
  return apiGet(`/api/sessions/${encodeURIComponent(sessionId)}/plan-revisions`);
}

export function getPlanRevision(sessionId: string, revision: number): Promise<PlanRevision> {
  return apiGet(`/api/sessions/${encodeURIComponent(sessionId)}/plan-revisions/${revision}`);
}

export function diffPlanRevisions(sessionId: string, fromRev: number, toRev: number): Promise<PlanRevisionDiff> {
  return apiGet(`/api/sessions/${encodeURIComponent(sessionId)}/plan-revisions/${fromRev}/diff/${toRev}`);
}
