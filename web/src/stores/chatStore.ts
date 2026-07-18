import { create } from "zustand";
import type { Message, WsMessage, ChatResponse } from "../types";
import * as api from "../api/sessions";

interface ChatState {
  messages: Message[];
  events: WsMessage[];
  isRunning: boolean;
  steps: number;
  tokens: number;
  error: string | null;
  ws: WebSocket | null;

  setMessages: (msgs: Message[]) => void;
  addEvent: (ev: WsMessage) => void;
  clearEvents: () => void;
  clear: () => void;
  sendChat: (sessionId: string, prompt: string) => Promise<void>;
  connectWs: (sessionId: string) => void;
  disconnectWs: () => void;
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  events: [],
  isRunning: false,
  steps: 0,
  tokens: 0,
  error: null,
  ws: null,

  setMessages: (msgs) => set({ messages: msgs }),

  addEvent: (ev) =>
    set((s) => ({ events: [ev, ...s.events].slice(0, 100) })),

  clearEvents: () => set({ events: [] }),

  clear: () =>
    set({ messages: [], events: [], steps: 0, tokens: 0, error: null }),

  sendChat: async (sessionId, prompt) => {
    set({ isRunning: true, error: null });
    try {
      const result = await api.chat(sessionId, prompt);
      const msgs = await api.getMessages(sessionId);
      set({
        messages: msgs,
        isRunning: false,
        steps: result.steps_taken,
        tokens: result.total_tokens,
      });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Chat failed";
      set({ error: msg, isRunning: false });
    }
  },

  connectWs: (sessionId) => {
    get().disconnectWs();
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${proto}//${window.location.host}/api/ws/sessions/${sessionId}`;
    const ws = new WebSocket(url);
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data) as WsMessage;
        if (msg.type === "complete" || msg.type === "pong") return;
        get().addEvent(msg);
      } catch { /* skip */ }
    };
    ws.onclose = () => set({ ws: null });
    set({ ws });
  },

  disconnectWs: () => {
    const { ws } = get();
    if (ws) {
      ws.close();
      set({ ws: null });
    }
  },
}));
