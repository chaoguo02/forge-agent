"use strict";

// ── State ──────────────────────────────────────────────────────────────────
const State = {
  sessions: [],
  activeSessionId: null,
  activeView: "chat",
  isBusy: false,
  ws: null,
};

// ── DOM refs ───────────────────────────────────────────────────────────────
const $ = (s) => document.querySelector(s);
const els = {
  sessionList: $("#session-list"),
  newSessionBtn: $("#new-session-btn"),
  messages: $("#messages"),
  welcome: $("#welcome"),
  input: $("#prompt-input"),
  sendBtn: $("#send-btn"),
  clearBtn: $("#clear-btn"),
  statusDot: $("#status-dot"),
  statusText: $("#status-text"),
  sessionMeta: $("#session-meta"),
  usageMeta: $("#usage-meta"),
  eventList: $("#event-list"),
  eventSidebar: $("#event-sidebar"),
  themeBtn: $("#theme-btn"),
  viewTabs: document.querySelectorAll(".view-tab"),
  views: {
    chat: $("#chat-view"),
    tasks: $("#tasks-view"),
    plan: $("#plan-view"),
    events: $("#events-view"),
  },
};

// ── API client ─────────────────────────────────────────────────────────────
async function apiGet(path) {
  const r = await fetch(path);
  if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(d.detail || `${r.status}`); }
  return r.json();
}

async function apiPost(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `${r.status}`);
  return data;
}

// ── Helpers ────────────────────────────────────────────────────────────────
function escapeHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function setStatus(state, text) {
  els.statusDot.className = "status-dot" + (state === "busy" ? " busy" : state === "error" ? " error" : "");
  els.statusText.textContent = text || (state === "busy" ? "Working…" : state === "error" ? "Error" : "Ready");
}

function scrollToBottom() {
  const view = els.views.chat;
  view.scrollTop = view.scrollHeight;
}

function renderMarkdown(md) {
  if (!md) return "";
  const codeBlocks = [];
  let text = String(md).replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, body) => {
    const idx = codeBlocks.length;
    codeBlocks.push({ lang, body });
    return `\0CODE${idx}\0`;
  });
  text = escapeHtml(text);
  text = text.replace(/^### (.+)$/gm, "<h3>$1</h3>");
  text = text.replace(/^## (.+)$/gm, "<h2>$1</h2>");
  text = text.replace(/^# (.+)$/gm, "<h1>$1</h1>");
  text = text.replace(/^> (.+)$/gm, "<blockquote>$1</blockquote>");
  text = text.replace(/\*\*(\S.*?\S)\*\*/g, "<strong>$1</strong>");
  text = text.replace(/\*(\S.*?\S)\*/g, "<em>$1</em>");
  text = text.replace(/`([^`]+)`/g, "<code>$1</code>");
  text = text.replace(/^- (.+)$/gm, "• $1");
  text = text.replace(/\n/g, "<br>");
  text = text.replace(/\0CODE(\d+)\0/g, (_, idx) => {
    const cb = codeBlocks[+idx];
    return `<pre><code>${escapeHtml(cb.body)}</code></pre>`;
  });
  return text;
}

// ── Sessions ───────────────────────────────────────────────────────────────
async function loadSessions() {
  try {
    State.sessions = await apiGet("/api/sessions?limit=50");
    renderSessions();
  } catch (e) {
    els.sessionList.innerHTML = `<div class="empty-state">${escapeHtml(e.message)}</div>`;
  }
}

function renderSessions() {
  els.sessionList.innerHTML = "";
  if (!State.sessions.length) {
    els.sessionList.innerHTML = '<div class="empty-state">No sessions yet.</div>';
    return;
  }
  for (const s of State.sessions) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "session-item";
    if (s.id === State.activeSessionId) item.classList.add("active");
    const preview = s.summary
      ? s.summary.slice(0, 80)
      : (s.title || s.id).slice(0, 30);
    item.innerHTML = `
      <div class="session-preview">${escapeHtml(preview)}</div>
      <div class="session-meta">${escapeHtml(s.agent_name)} · ${escapeHtml(s.status)}</div>
    `;
    item.addEventListener("click", () => openSession(s.id));
    els.sessionList.appendChild(item);
  }
}

async function openSession(id) {
  if (State.isBusy) return;
  State.activeSessionId = id;
  setStatus("busy", "Loading session…");
  try {
    const detail = await apiGet(`/api/sessions/${encodeURIComponent(id)}`);
    const msgs = await apiGet(`/api/sessions/${encodeURIComponent(id)}/messages`);
    renderSessions();
    clearChat();
    els.sessionMeta.textContent = `${detail.agent_name} · ${detail.status}`;
    for (const m of msgs) {
      renderMessage(m);
    }
    if (!msgs.length) {
      showWelcome(false);
    }
    scrollToBottom();
    setStatus("ready", "Ready");
    connectWS(id);
  } catch (e) {
    setStatus("error", e.message);
  }
}

async function createSession() {
  try {
    setStatus("busy", "Creating session…");
    const resp = await apiPost("/api/sessions", {
      agent_name: "build",
      repo_path: window.__repoPath || ".",
      title: "Session " + new Date().toLocaleTimeString(),
    });
    await loadSessions();
    await openSession(resp.session_id);
  } catch (e) {
    setStatus("error", e.message);
    alert("Failed to create session: " + e.message);
  }
}

// ── Chat ───────────────────────────────────────────────────────────────────
function clearChat() {
  els.messages.innerHTML = "";
  els.welcome.style.display = "";
}

function showWelcome(show) {
  els.welcome.style.display = show ? "" : "none";
}

function appendMessage(msg) {
  showWelcome(false);
  const el = document.createElement("div");
  el.className = "message " + msg.role;
  const avatar = msg.role === "user" ? "U" : msg.role === "assistant" ? "GC" : "T";
  el.innerHTML = `
    <div class="message-row">
      <div class="message-avatar">${avatar}</div>
      <div class="message-bubble">${renderMarkdown(msg.content || "")}</div>
    </div>
  `;
  els.messages.appendChild(el);
  scrollToBottom();
  return el;
}

function appendToolCall(tc) {
  const el = document.createElement("div");
  el.className = "tool-call-card";
  const args = typeof tc.params === "string" ? tc.params : JSON.stringify(tc.params || {}, null, 2);
  el.innerHTML = `<div class="name">🔧 ${escapeHtml(tc.name || tc.id || "")}</div>
    <div class="params">${escapeHtml(args.slice(0, 200))}</div>`;
  els.messages.appendChild(el);
  scrollToBottom();
}

function appendEvent(msg) {
  // Add to event sidebar
  const empty = els.eventList.querySelector(".empty-state");
  if (empty) empty.remove();
  const el = document.createElement("div");
  el.className = "event-item";
  const type = msg.type || "";
  const text = msg.payload?.action?.thought?.slice(0, 60)
    || msg.payload?.observation?.output?.slice(0, 60)
    || "";
  el.innerHTML = `<span class="type">${escapeHtml(type)}</span>
    <span class="text">${escapeHtml(text)}</span>`;
  els.eventList.prepend(el);
  while (els.eventList.children.length > 100) {
    els.eventList.removeChild(els.eventList.lastChild);
  }
}

function renderMessage(m) {
  appendMessage(m);
  if (m.tool_calls) {
    for (const tc of m.tool_calls) {
      appendToolCall(tc);
    }
  }
}

async function sendMessage() {
  const text = els.input.value.trim();
  if (!text || !State.activeSessionId || State.isBusy) return;
  els.input.value = "";
  State.isBusy = true;
  setStatus("busy", "Running…");
  els.sendBtn.disabled = true;
  els.input.disabled = true;

  // Show user message immediately
  appendMessage({ role: "user", content: text });

  // Clear events
  els.eventList.innerHTML = '<div class="empty-state">Running…</div>';

  try {
    const result = await apiPost(`/api/sessions/${State.activeSessionId}/chat`, {
      prompt: text,
    });
    // Load fresh messages
    const msgs = await apiGet(`/api/sessions/${State.activeSessionId}/messages`);
    clearChat();
    for (const m of msgs) {
      renderMessage(m);
    }
    setStatus("ready", result.status);
    els.usageMeta.textContent = `${result.steps_taken} steps · ${result.total_tokens} tokens`;
    await loadSessions(); // refresh sidebar
  } catch (e) {
    setStatus("error", e.message);
    const errMsg = document.createElement("div");
    errMsg.className = "message";
    errMsg.innerHTML = `<div class="message-row"><div class="message-avatar" style="background:var(--error-soft);color:var(--error);">!</div>
      <div class="message-bubble" style="background:var(--error-soft);">${escapeHtml(e.message)}</div></div>`;
    els.messages.appendChild(errMsg);
  } finally {
    State.isBusy = false;
    els.sendBtn.disabled = false;
    els.input.disabled = false;
    els.input.focus();
  }
}

// ── WebSocket ──────────────────────────────────────────────────────────────
function connectWS(sessionId) {
  if (State.ws) { State.ws.close(); State.ws = null; }
  if (!sessionId) return;
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${proto}//${window.location.host}/api/ws/sessions/${sessionId}`;
  const ws = new WebSocket(url);
  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      if (msg.type === "complete" || msg.type === "pong") return;
      appendEvent(msg);
    } catch (e) { /* skip */ }
  };
  ws.onclose = () => { State.ws = null; };
  State.ws = ws;
}

// ── Theme ───────────────────────────────────────────────────────────────────
function toggleTheme() {
  const html = document.documentElement;
  const current = html.getAttribute("data-theme") || "light";
  const next = current === "light" ? "dark" : "light";
  html.setAttribute("data-theme", next);
  try { localStorage.setItem("grace-theme", next); } catch {}
  els.themeBtn.textContent = next === "light" ? "🌙" : "☀️";
}

function restoreTheme() {
  try {
    const saved = localStorage.getItem("grace-theme");
    if (saved) document.documentElement.setAttribute("data-theme", saved);
    const current = document.documentElement.getAttribute("data-theme") || "light";
    els.themeBtn.textContent = current === "light" ? "🌙" : "☀️";
  } catch {}
}

// ── View switching ─────────────────────────────────────────────────────────
function switchView(name) {
  State.activeView = name;
  for (const tab of els.viewTabs) {
    tab.classList.toggle("active", tab.dataset.view === name);
  }
  for (const [key, el] of Object.entries(els.views)) {
    el.hidden = el.dataset.viewName !== name;
    el.classList.toggle("active", el.dataset.viewName === name);
  }
}

// ── Events ─────────────────────────────────────────────────────────────────
els.newSessionBtn.addEventListener("click", createSession);

els.sendBtn.addEventListener("click", sendMessage);

els.input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

els.clearBtn.addEventListener("click", () => {
  clearChat();
  showWelcome(true);
  els.eventList.innerHTML = '<div class="empty-state">Waiting for execution…</div>';
  els.sessionMeta.textContent = "";
  els.usageMeta.textContent = "";
});

els.themeBtn.addEventListener("click", toggleTheme);

for (const tab of els.viewTabs) {
  tab.addEventListener("click", () => switchView(tab.dataset.view));
}

// ── Keyboard shortcut: Ctrl+Enter also sends ───────────────────────────────
document.addEventListener("keydown", (e) => {
  if (e.ctrlKey && e.key === "Enter") {
    e.preventDefault();
    sendMessage();
  }
});

// ── Init ───────────────────────────────────────────────────────────────────
async function init() {
  restoreTheme();
  // Try to get repo path from a meta tag or server state
  try {
    const sessions = await apiGet("/api/sessions?limit=1");
    window.__repoPath = window.location.pathname || ".";
  } catch {}
  await loadSessions();
  if (State.sessions.length > 0) {
    await openSession(State.sessions[0].id);
  }
  // Focus input
  els.input.focus();
}

init();
