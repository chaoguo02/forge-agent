import { useEffect, useRef } from "react";
import { useSessionStore } from "../stores/sessionStore";
import { useChatStore } from "../stores/chatStore";
import { MessageBubble } from "./MessageBubble";
import { WsEventBlock } from "./WsEventBlock";
import * as api from "../api/sessions";
import type { TimelineItem } from "../types";

export function ChatView() {
  const { activeId, activeDetail } = useSessionStore();
  const { timeline, isRunning, error, sendChat, loadMessages, connectWs, disconnectWs, clear } =
    useChatStore();
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Load persisted messages + connect WS when session changes
  useEffect(() => {
    if (activeId) {
      loadMessages(activeId);
      connectWs(activeId);
    }
    return () => {
      disconnectWs();
    };
  }, [activeId, loadMessages, connectWs, disconnectWs]);

  // Scroll to bottom on new timeline items
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [timeline]);

  const handleSend = () => {
    const text = inputRef.current?.value.trim();
    if (!text || !activeId || isRunning) return;
    if (inputRef.current) inputRef.current.value = "";
    sendChat(activeId, text);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <>
      <section className="chat view active" data-view-name="chat">
        {timeline.length === 0 && (
          <div className="welcome">
            <h1>Grace Code</h1>
            <p>Select a session or create a new one to start.</p>
          </div>
        )}
        <div id="messages">
          {timeline.map((item, i) =>
            item.source === "message" ? (
              <MessageBubble key={`m-${i}`} message={item.msg} />
            ) : (
              <WsEventBlock key={`ws-${i}`} event={item.ws} />
            )
          )}
          {isRunning && (
            <div className="message assistant">
              <div className="message-row">
                <div className="message-avatar">GC</div>
                <div className="message-bubble">
                  <span className="loading-dots">Thinking</span>…
                </div>
              </div>
            </div>
          )}
          {error && (
            <div className="message">
              <div className="message-row">
                <div
                  className="message-avatar"
                  style={{ background: "var(--error-soft)", color: "var(--error)" }}
                >!</div>
                <div className="message-bubble" style={{ background: "var(--error-soft)" }}>
                  {error}
                </div>
              </div>
            </div>
          )}
        </div>
        <div ref={bottomRef} />
      </section>

      <footer className="composer">
        <div className="composer-inner">
          <textarea
            ref={inputRef}
            id="prompt-input"
            placeholder="Send a message… (Enter to send, Shift+Enter for newline)"
            rows={1}
            autoComplete="off"
            disabled={isRunning || !activeId}
            onKeyDown={handleKeyDown}
          />
          <button
            className="btn-send"
            type="button"
            disabled={isRunning || !activeId}
            onClick={handleSend}
          >
            {isRunning ? "● Running" : "Send"}
          </button>
        </div>
        <div className="composer-meta">
          <span>
            {activeDetail
              ? `${activeDetail.agent_name} · ${activeDetail.status}`
              : ""}
          </span>
          <span>
            {activeDetail?.message_count != null
              ? `${activeDetail.message_count} msgs · ~${activeDetail.total_tokens_estimate ?? 0} tok`
              : ""}
          </span>
        </div>
      </footer>
    </>
  );
}
