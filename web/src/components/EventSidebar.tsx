import { useChatStore } from "../stores/chatStore";

export function EventSidebar() {
  const events = useChatStore((s) => s.events);

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
            (ev.payload?.action as Record<string, unknown>)?.thought?.toString().slice(0, 60) ||
            (ev.payload?.observation as Record<string, unknown>)?.output?.toString().slice(0, 60) ||
            "";
          return (
            <div key={i} className="event-item">
              <span className="type">{type}</span>
              <span className="text">{text}</span>
            </div>
          );
        })}
      </div>
    </aside>
  );
}
