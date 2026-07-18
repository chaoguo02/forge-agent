import { useEffect, useState } from "react";
import { useChatStore } from "../stores/chatStore";

interface StorageStats {
  backend: string;
  total_sessions: number;
  total_messages: number;
  db_size_bytes: number | null;
}

export function EventSidebar() {
  const events = useChatStore((s) => s.events);
  const [stats, setStats] = useState<StorageStats | null>(null);

  useEffect(() => {
    fetch("/api/storage/stats")
      .then((r) => r.json())
      .then(setStats)
      .catch(() => {});
  }, []);

  return (
    <aside className="event-sidebar" id="event-sidebar">
      <div className="event-header">Live Events</div>
      <div className="event-list">
        {events.length === 0 && (
          <div className="empty-state">Waiting for execution…</div>
        )}
        {events.map((ev, i) => {
          const type = ev.type || "";
          const text =
            ev.content?.slice(0, 60) ||
            ev.name?.slice(0, 40) ||
            ev.output?.slice(0, 60) ||
            "";
          return (
            <div key={i} className="event-item">
              <span className="type">{type}</span>
              <span className="text">{text}</span>
            </div>
          );
        })}
      </div>

      {stats && (
        <div style={{ borderTop: "1px solid var(--border)", padding: "10px 14px", fontSize: 11, color: "var(--text-muted)" }}>
          <div style={{ fontWeight: 600, marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.5px" }}>
            Storage
          </div>
          <div>Backend: <strong>{stats.backend}</strong></div>
          <div>Sessions: <strong>{stats.total_sessions}</strong></div>
          <div>Messages: <strong>{stats.total_messages}</strong></div>
          {stats.db_size_bytes != null && (
            <div>DB size: <strong>{(stats.db_size_bytes / 1024).toFixed(0)} KB</strong></div>
          )}
        </div>
      )}
    </aside>
  );
}
