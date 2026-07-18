import type { Message, ToolCall } from "../types";

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function renderMarkdown(md: string): string {
  if (!md) return "";
  const codeBlocks: { lang: string; body: string }[] = [];
  let text = md.replace(
    /```(\w*)\n([\s\S]*?)```/g,
    (_: string, lang: string, body: string) => {
      const idx = codeBlocks.length;
      codeBlocks.push({ lang, body });
      return `\0CODE${idx}\0`;
    }
  );
  text = escapeHtml(text);
  text = text.replace(/^### (.+)$/gm, "<h3>$1</h3>");
  text = text.replace(/^## (.+)$/gm, "<h2>$1</h2>");
  text = text.replace(/^# (.+)$/gm, "<h1>$1</h1>");
  text = text.replace(/> (.+)$/gm, "<blockquote>$1</blockquote>");
  text = text.replace(/\*\*(\S.*?\S)\*\*/g, "<strong>$1</strong>");
  text = text.replace(/\*(\S.*?\S)\*/g, "<em>$1</em>");
  text = text.replace(/`([^`]+)`/g, "<code>$1</code>");
  text = text.replace(/\n/g, "<br>");
  text = text.replace(/\0CODE(\d+)\0/g, (_: string, idx: string) => {
    const cb = codeBlocks[+idx];
    return `<pre><code>${escapeHtml(cb.body)}</code></pre>`;
  });
  return text;
}

function ToolCallCard({ tc }: { tc: ToolCall }) {
  const args =
    typeof tc.params === "string"
      ? tc.params
      : JSON.stringify(tc.params || {}, null, 2);
  return (
    <div className="tool-call-card">
      <div className="name">🔧 {escapeHtml(tc.name || tc.id || "")}</div>
      <div className="params">{escapeHtml(args.slice(0, 200))}</div>
    </div>
  );
}

export function MessageBubble({ message }: { message: Message }) {
  const avatar =
    message.role === "user" ? "U" : message.role === "assistant" ? "GC" : "T";
  return (
    <div className={`message ${message.role}`}>
      <div className="message-row">
        <div className="message-avatar">{avatar}</div>
        <div
          className="message-bubble"
          dangerouslySetInnerHTML={{
            __html: renderMarkdown(message.content || ""),
          }}
        />
      </div>
      {message.tool_calls?.map((tc, i) => (
        <ToolCallCard key={i} tc={tc} />
      ))}
    </div>
  );
}
