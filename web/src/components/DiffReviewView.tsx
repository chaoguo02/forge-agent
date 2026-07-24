import { useEffect, useMemo, useState } from "react";
import { getSessionDiffs, getPendingDiffs, updateDiffStatus } from "../api/diffs";
import { getSessionStats, getSessionSteps } from "../api/stats";
import { DiffBlock } from "./DiffBlock";
import { useSessionStore } from "../stores/sessionStore";
import type { SessionDiff, SessionStats, StepLog } from "../types/stats";

function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="plan-empty">
      <div className="plan-empty-icon">R</div>
      <div className="plan-empty-title">{title}</div>
      <div className="plan-empty-body">{body}</div>
    </div>
  );
}

function countDiffLines(diff: string): { added: number; removed: number; total: number } {
  const lines = diff.split("\n");
  let added = 0;
  let removed = 0;
  for (const line of lines) {
    if (line.startsWith("+") && !line.startsWith("+++")) added++;
    else if (line.startsWith("-") && !line.startsWith("---")) removed++;
  }
  return { added, removed, total: lines.length };
}

function formatDuration(ms?: number) {
  if (!ms || ms <= 0) return "—";
  const sec = Math.round(ms / 1000);
  if (sec < 60) return `${sec}s`;
  return `${Math.floor(sec / 60)}m ${sec % 60}s`;
}

function statusTone(status?: string | null) {
  if (status === "completed" || status === "finish") return "good";
  if (status === "failed" || status === "gave_up") return "bad";
  if (status === "running") return "busy";
  return "neutral";
}

function collectVerificationSignals(steps: StepLog[]) {
  const signals = steps.filter((step) => {
    const tool = (step.tool_name || "").toLowerCase();
    const params = (step.tool_params || "").toLowerCase();
    return tool.includes("bash")
      || tool.includes("powershell")
      || params.includes("test")
      || params.includes("build")
      || params.includes("lint")
      || params.includes("typecheck")
      || params.includes("tsc")
      || params.includes("playwright");
  });
  return signals.slice(-6).reverse();
}

export function DiffReviewView() {
  const activeId = useSessionStore((s) => s.activeId);
  const activeDetail = useSessionStore((s) => s.activeDetail);

  const [globalDiffs, setGlobalDiffs] = useState<SessionDiff[]>([]);
  const [sessionDiffs, setSessionDiffs] = useState<SessionDiff[]>([]);
  const [stats, setStats] = useState<SessionStats | null>(null);
  const [steps, setSteps] = useState<StepLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [submittingId, setSubmittingId] = useState<number | null>(null);
  const [submittingAny, setSubmittingAny] = useState(false);
  const [comments, setComments] = useState<Record<number, string>>({});
  const [expandedDiffs, setExpandedDiffs] = useState<Set<number>>(new Set());
  const [errors, setErrors] = useState<Record<number, string>>({});

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([
      getPendingDiffs().catch(() => []),
      activeId ? getSessionDiffs(activeId).catch(() => []) : Promise.resolve([]),
      activeId ? getSessionStats(activeId).catch(() => null) : Promise.resolve(null),
      activeId ? getSessionSteps(activeId).catch(() => []) : Promise.resolve([]),
    ]).then(([pendingData, sessionDiffData, statsData, stepsData]) => {
      if (cancelled) return;
      setGlobalDiffs(pendingData as SessionDiff[]);
      setSessionDiffs(sessionDiffData as SessionDiff[]);
      setStats(statsData as SessionStats | null);
      setSteps(stepsData as StepLog[]);
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, [activeId]);

  const pendingQueue = useMemo(
    () => globalDiffs
      .filter((item) => item.status === "pending")
      .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()),
    [globalDiffs],
  );

  const sessionPending = sessionDiffs.filter((item) => item.status === "pending").length;
  const sessionLineStats = useMemo(() => {
    return sessionDiffs.reduce((acc, diff) => {
      const next = countDiffLines(diff.diff_content);
      return { added: acc.added + next.added, removed: acc.removed + next.removed, total: acc.total + next.total };
    }, { added: 0, removed: 0, total: 0 });
  }, [sessionDiffs]);

  const verificationSignals = useMemo(() => collectVerificationSignals(steps), [steps]);
  const failedSignals = verificationSignals.filter((step) => step.status === "error" || step.status === "failed").length;
  const readiness = !activeId
    ? "Open a session to review its outcome"
    : loading
      ? "Loading review signals"
      : failedSignals > 0
        ? "Needs attention"
        : sessionPending > 0
          ? "Pending decisions"
          : activeDetail?.status === "completed"
            ? "Ready for handoff"
            : activeDetail?.status === "running"
              ? "Run in progress"
              : "Review available";

  const handleDecision = async (diff: SessionDiff, status: "approved" | "rejected") => {
    if (submittingAny) return;
    setSubmittingAny(true);
    setSubmittingId(diff.id);
    setErrors((prev) => { const next = { ...prev }; delete next[diff.id]; return next; });
    try {
      await updateDiffStatus(diff.id, status, comments[diff.id] || "");
      setGlobalDiffs((prev) => prev.filter((item) => item.id !== diff.id));
      setSessionDiffs((prev) => prev.map((item) => item.id === diff.id ? { ...item, status } : item));
    } catch {
      setErrors((prev) => ({ ...prev, [diff.id]: `Failed to ${status} diff — try again` }));
    } finally {
      setSubmittingAny(false);
      setSubmittingId(null);
    }
  };

  const toggleExpand = (id: number) => {
    setExpandedDiffs((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <section className="view active" data-view-name="reviews">
      <div className="plan-page review-page">
        <div className="plan-hero review-hero">
          <div>
            <div className="summary-label">Review Workspace</div>
            <h2 className="plan-hero-title">Quality, changes, and readiness</h2>
            <p className="plan-hero-body">
              Use this page after or during a run to understand what changed, what was verified, and what still needs a decision.
            </p>
          </div>
          <div className="plan-hero-stats">
            <div className="meta-pill">
              <div className="meta-pill-label">Readiness</div>
              <div className="meta-pill-value">{readiness}</div>
            </div>
            <div className="meta-pill">
              <div className="meta-pill-label">Pending</div>
              <div className="meta-pill-value">{pendingQueue.length}</div>
            </div>
          </div>
        </div>

        <div className="stats-grid">
          <div className="stats-card">
            <div className="stats-card-header">
              <div>
                <div className="summary-label">Session outcome</div>
                <h3 className="stats-card-title">{activeDetail?.title || "No session selected"}</h3>
              </div>
              <span className={`summary-status-dot ${statusTone(activeDetail?.status)}`} />
            </div>
            <div className="session-drawer-grid">
              <div className="session-drawer-stat"><span>Status</span><strong>{stats?.status || activeDetail?.status || "—"}</strong></div>
              <div className="session-drawer-stat"><span>Steps</span><strong>{stats?.total_steps ?? activeDetail?.message_count ?? "—"}</strong></div>
              <div className="session-drawer-stat"><span>Tokens</span><strong>{(stats?.total_tokens ?? activeDetail?.total_tokens_estimate ?? 0).toLocaleString()}</strong></div>
              <div className="session-drawer-stat"><span>Runtime</span><strong>{formatDuration(stats?.total_duration_ms)}</strong></div>
            </div>
          </div>

          <div className="stats-card">
            <div className="stats-card-header">
              <div>
                <div className="summary-label">Changed files</div>
                <h3 className="stats-card-title">Active session diff summary</h3>
              </div>
            </div>
            <div className="session-drawer-grid">
              <div className="session-drawer-stat"><span>Files</span><strong>{sessionDiffs.length}</strong></div>
              <div className="session-drawer-stat"><span>Pending</span><strong>{sessionPending}</strong></div>
              <div className="session-drawer-stat"><span>Added</span><strong>+{sessionLineStats.added}</strong></div>
              <div className="session-drawer-stat"><span>Removed</span><strong>−{sessionLineStats.removed}</strong></div>
            </div>
          </div>
        </div>

        <div className="stats-card stats-card-wide">
          <div className="stats-card-header">
            <div>
              <div className="summary-label">Verification</div>
              <h3 className="stats-card-title">Build, test, and command signals</h3>
            </div>
          </div>
          {loading ? (
            <div className="empty-state">Loading verification signals...</div>
          ) : verificationSignals.length === 0 ? (
            <EmptyState title="No verification signals yet" body="Build, test, lint, or typecheck commands will appear here when this session records them." />
          ) : (
            <div className="stats-session-list">
              {verificationSignals.map((step) => (
                <div key={step.id} className="stats-session-row">
                  <div className="stats-session-main">
                    <strong>{step.tool_name}</strong>
                    <span>{step.status}</span>
                    <span>Step {step.step_number}</span>
                    <span>{formatDuration(step.duration_ms)}</span>
                    <span>{step.tokens ? `${step.tokens.toLocaleString()} tok` : "—"}</span>
                  </div>
                  <div className="stats-session-subtle">{step.tool_params}</div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="stats-card stats-card-wide">
          <div className="stats-card-header">
            <div>
              <div className="summary-label">Pending change decisions</div>
              <h3 className="stats-card-title">Proposed file changes that still need action</h3>
            </div>
          </div>

          {loading ? (
            <div className="review-loading-card">Loading pending decisions...</div>
          ) : pendingQueue.length === 0 ? (
            <EmptyState title="No pending change decisions" body="Proposed file changes will appear here only when they still require an explicit approve or reject decision." />
          ) : (
            <div className="review-list">
              {pendingQueue.map((diff) => {
                const lineStats = countDiffLines(diff.diff_content);
                const isExpanded = expandedDiffs.has(diff.id);
                return (
                  <div key={diff.id} className="review-card">
                    <div className="review-card-header">
                      <div>
                        <div className="review-card-file-row">
                          <span className="review-card-file-icon">F</span>
                          <h3 className="review-card-title">{diff.file_path}</h3>
                        </div>
                        <div className="review-card-meta">
                          <button
                            className="review-session-link"
                            type="button"
                            onClick={() => useSessionStore.getState().openSession(diff.session_id)}
                            title="Open session in Chat view"
                          >
                            {diff.session_title || diff.session_id.slice(0, 8)}
                          </button>
                          <span>Step {diff.step_number}</span>
                          <span>{diff.session_agent || "agent"}</span>
                          <span className="review-diff-summary">+{lineStats.added} / −{lineStats.removed}</span>
                        </div>
                      </div>
                      <div className="review-card-actions">
                        <button className="btn-approve" type="button" disabled={submittingId === diff.id} onClick={() => handleDecision(diff, "approved")}>Approve</button>
                        <button className="btn-reject" type="button" disabled={submittingId === diff.id} onClick={() => handleDecision(diff, "rejected")}>Reject</button>
                      </div>
                    </div>

                    {errors[diff.id] && (
                      <div style={{ marginTop: 8, padding: "6px 12px", borderRadius: 8, background: "var(--red, #f44336)", color: "#fff", fontSize: 12 }}>
                        {errors[diff.id]}
                      </div>
                    )}

                    <button type="button" className="review-diff-toggle" onClick={() => toggleExpand(diff.id)}>
                      <span>{isExpanded ? "▼ Hide diff" : `▶ Show diff (${lineStats.total} lines, +${lineStats.added}/−${lineStats.removed})`}</span>
                    </button>

                    {isExpanded && <DiffBlock diff={diff.diff_content} />}

                    <div className="review-comment-row">
                      <input
                        className="review-comment-input"
                        type="text"
                        placeholder="Leave an optional review comment..."
                        value={comments[diff.id] || ""}
                        onChange={(e) => setComments((prev) => ({ ...prev, [diff.id]: e.target.value }))}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
