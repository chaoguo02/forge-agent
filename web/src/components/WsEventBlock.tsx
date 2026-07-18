import type { WsMessage } from "../types";

function escapeHtml(s: string): string {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/** Renders a live WS event as a timeline block. */
export function WsEventBlock({ event }: { event: WsMessage }) {
  switch (event.type) {
    case "thought":
      return (
        <div className="message assistant">
          <div className="message-row">
            <div className="message-avatar" style={{ background: "var(--bg-soft)", color: "var(--text-dim)", fontSize: 10 }}>🤔</div>
            <div className="message-bubble" style={{ opacity: 0.75, fontStyle: "italic" }}>
              {escapeHtml(event.content || "")}
            </div>
          </div>
        </div>
      );

    case "tool_call":
      return (
        <div className="message" style={{ marginBottom: 4 }}>
          <div className="message-row">
            <div className="message-avatar" style={{ background: "var(--tool-soft)", color: "var(--tool)", fontSize: 10 }}>🔧</div>
            <div className="tool-call-card" style={{ flex: 1, margin: 0 }}>
              <div className="name">{escapeHtml(event.name || "")}</div>
              <div className="params">{escapeHtml(JSON.stringify(event.params || {}, null, 2).slice(0, 300))}</div>
            </div>
          </div>
        </div>
      );

    case "observation":
      return (
        <div className="message" style={{ marginBottom: 4 }}>
          <div className="message-row">
            <div className="message-avatar" style={{ background: "var(--success-soft)", color: "var(--success)", fontSize: 10 }}>
              {event.status === "error" ? "⚠" : "✓"}
            </div>
            <div className="message-bubble" style={{ background: "var(--code-bg)", fontSize: 12, fontFamily: "var(--font-mono)", padding: "6px 10px" }}>
              {escapeHtml((event.output || event.error || "").slice(0, 200))}
            </div>
          </div>
        </div>
      );

    case "reflection":
      return (
        <div className="message assistant">
          <div className="message-row">
            <div className="message-avatar" style={{ background: "var(--bg-soft)", color: "var(--text-dim)", fontSize: 10 }}>💭</div>
            <div className="message-bubble" style={{ opacity: 0.6, fontStyle: "italic", fontSize: 13 }}>
              {escapeHtml(event.content || "")}
            </div>
          </div>
        </div>
      );

    case "subagent_start":
      return (
        <div className="message" style={{ marginBottom: 4 }}>
          <div className="message-row">
            <div className="message-avatar" style={{ background: "var(--accent-soft)", color: "var(--accent)", fontSize: 10 }}>⊞</div>
            <div className="message-bubble" style={{ fontSize: 12, color: "var(--text-dim)" }}>
              Subagent <strong>{escapeHtml(event.agent_name || "")}</strong> started ({escapeHtml(event.child_session_id || "").slice(0, 8)})
            </div>
          </div>
        </div>
      );

    case "subagent_stop":
      return (
        <div className="message" style={{ marginBottom: 4 }}>
          <div className="message-row">
            <div className="message-avatar" style={{ background: "var(--bg-soft)", color: "var(--text-dim)", fontSize: 10 }}>⊟</div>
            <div className="message-bubble" style={{ fontSize: 12, color: "var(--text-dim)" }}>
              Subagent completed: {escapeHtml(event.status || "")}
            </div>
          </div>
        </div>
      );

    case "status":
      if (event.status === "finish" || event.status === "gave_up") {
        return (
          <div className="message assistant">
            <div className="message-row">
              <div className="message-avatar" style={{ background: "var(--success-soft)", color: "var(--success)" }}>✓</div>
              <div className="message-bubble">{escapeHtml(event.message || "")}</div>
            </div>
          </div>
        );
      }
      // status running/completed/failed — rendered by ChatView
      return null;

    default:
      return null;
  }
}
