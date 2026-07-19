/**
 * SubagentDetail — child session execution log viewer.
 *
 * CC-aligned: shows full timeline of a subagent session with
 * back-to-parent navigation.  Opens when user clicks a child
 * session in SessionTree or a subagent_stop event in the timeline.
 */
import { useEffect, useState } from "react";
import { useSessionStore } from "../stores/sessionStore";
import { useChatStore } from "../stores/chatStore";
import { WsEventBlock } from "./WsEventBlock";
import * as api from "../api/sessions";
import type { WsMessage, SessionDetail } from "../types";

interface SubagentDetailProps {
  childSessionId: string;
  onClose: () => void;
}

export function SubagentDetail({ childSessionId, onClose }: SubagentDetailProps) {
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [events, setEvents] = useState<WsMessage[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const [d, evs] = await Promise.all([
          api.getSession(childSessionId),
          api.getTraceEvents(childSessionId),
        ]);
        if (!cancelled) {
          setDetail(d);
          setEvents(evs);
        }
      } catch {
        // ignore
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [childSessionId]);

  const statusIcon: Record<string, string> = {
    running: "◎", completed: "✓", failed: "✗", queued: "○", cancelled: "◼",
  };

  return (
    <div style={{
      position: "absolute", top: 0, left: 0, right: 0, bottom: 0,
      background: "var(--bg)", zIndex: 10, overflow: "auto",
      display: "flex", flexDirection: "column",
    }}>
      {/* Header */}
      <div style={{
        padding: "10px 16px",
        borderBottom: "1px solid var(--border)",
        display: "flex", alignItems: "center", gap: 10,
        background: "var(--bg-elev)",
        position: "sticky", top: 0, zIndex: 1,
      }}>
        <button type="button" onClick={onClose}
          style={{
            background: "none", border: "none", cursor: "pointer",
            fontSize: 16, color: "var(--text-muted)", padding: "2px 8px",
          }}
        >
          ← Back
        </button>
        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
          {detail ? (
            <>
              <span style={{ color: "var(--accent)", fontWeight: 600 }}>
                {detail.agent_name}
              </span>
              {" · "}
              <span style={{ color: statusIcon[detail.status] ? "var(--text)" : "var(--text-muted)" }}>
                {statusIcon[detail.status] || "●"} {detail.status}
              </span>
              {" · "}
              <span>{childSessionId.slice(0, 8)}</span>
            </>
          ) : (
            childSessionId.slice(0, 8)
          )}
        </span>
        {detail?.metadata?.worktree_path && (
          <span style={{ fontSize: 11, color: "var(--accent)", marginLeft: "auto" }}>
            Worktree
          </span>
        )}
      </div>

      {/* Timeline */}
      <div style={{ flex: 1, padding: "12px 16px" }}>
        {loading ? (
          <div style={{ textAlign: "center", color: "var(--text-muted)", padding: 40 }}>
            Loading subagent log…
          </div>
        ) : events.length === 0 ? (
          <div style={{ textAlign: "center", color: "var(--text-muted)", padding: 40 }}>
            No events recorded for this subagent.
          </div>
        ) : (
          events.map((ev, i) => (
            <WsEventBlock key={i} event={ev} />
          ))
        )}
      </div>
    </div>
  );
}
