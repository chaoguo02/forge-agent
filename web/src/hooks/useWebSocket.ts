/**
 * WebSocket connection helpers (P2-16).
 *
 * useWebSocket — React hook for component-level WS lifecycle.
 * connectWebSocket — standalone helper for store-level WS management.
 */
import type { WsMessage } from "../types";

interface WsCallbacks {
  onOpen: () => void;
  onMessage: (ev: WsMessage) => void;
  onError: () => void;
  onClose: (info: string, isAbnormal: boolean) => void;
  reconnect: (sessionId: string) => void;
}

let _wsRef: WebSocket | null = null;
let _reconnectTimer: ReturnType<typeof setTimeout> | null = null;

export function disconnectWebSocket(): void {
  if (_reconnectTimer) {
    clearTimeout(_reconnectTimer);
    _reconnectTimer = null;
  }
  if (_wsRef) {
    _wsRef.close();
    _wsRef = null;
  }
}

export function connectWebSocket(
  sessionId: string,
  callbacks: WsCallbacks,
): void {
  disconnectWebSocket();

  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${proto}//${window.location.host}/api/ws/sessions/${sessionId}`;
  const ws = new WebSocket(url);
  _wsRef = ws;

  ws.onopen = () => callbacks.onOpen();
  ws.onmessage = (ev) => {
    try {
      const raw = JSON.parse(ev.data) as Record<string, unknown>;
      if (raw.type === "pong") return;
      callbacks.onMessage(raw as unknown as WsMessage);
    } catch {
      /* ignore malformed */
    }
  };
  ws.onerror = () => callbacks.onError();
  ws.onclose = (ev) => {
    const info = `code=${ev.code}${ev.reason ? ` reason=${ev.reason}` : ""}`;
    callbacks.onClose(info, ev.code !== 1000 && ev.code !== 1001);
  };
}

export function scheduleReconnect(
  sessionId: string,
  retries: number,
  cb: (sessionId: string) => void,
): void {
  const delay = Math.min(1000 * Math.pow(2, retries), 16000);
  _reconnectTimer = setTimeout(() => cb(sessionId), delay);
}
