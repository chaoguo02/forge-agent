import { useEffect } from "react";
import { useSessionStore } from "../stores/sessionStore";

export function SessionSidebar() {
  const { sessions, activeId, isLoading, loadSessions, openSession, createSession } =
    useSessionStore();

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  return (
    <aside className="sidebar">
      <div className="sidebar-head">
        <div className="brand">
          <span className="brand-mark">GC</span>
          <span className="brand-name">Grace Code</span>
        </div>
        <button className="btn-primary" type="button" onClick={() => createSession()}>
          + New chat
        </button>
      </div>
      <div className="sidebar-section sidebar-sessions">
        <div className="sidebar-title">Sessions</div>
        <div id="session-list" className="session-list">
          {isLoading && sessions.length === 0 && (
            <div className="empty-state">Loading…</div>
          )}
          {!isLoading && sessions.length === 0 && (
            <div className="empty-state">No sessions yet.</div>
          )}
          {sessions.map((s) => (
            <button
              key={s.id}
              type="button"
              className={`session-item ${s.id === activeId ? "active" : ""}`}
              onClick={() => openSession(s.id)}
            >
              <div className="session-preview">
                {s.summary
                  ? s.summary.slice(0, 80)
                  : (s.title || s.id).slice(0, 30)}
              </div>
              <div className="session-meta">
                {s.agent_name} · {s.status}
              </div>
            </button>
          ))}
        </div>
      </div>
    </aside>
  );
}
