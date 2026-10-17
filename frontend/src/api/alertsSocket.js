/**
 * /ws/alerts client (API A3): subprotocol auth, heartbeat watchdog,
 * jittered 1s→30s reconnect, and a resync callback on every (re)open. The
 * ticker keeps its 10s poll alongside this socket — live frames arrive
 * immediately, and a dead socket degrades to Phase-4 polling, never to
 * silence.
 *
 * URL derivation mirrors `api/client.js`: REST uses a relative `/api/v1`
 * base behind the same-origin proxy (design §9), so the socket must too —
 * `ws(s)://<location.host>`, never a second origin. `VITE_API_BASE` from
 * the plan was never wired in this repo, so location is the single source.
 * @module api/alertsSocket
 */

import { getAccessToken } from "./token.js";

const RECONNECT_BASE_MS = 1_000;
const RECONNECT_MAX_MS = 30_000;
/** Server heartbeats every 30s (backend ws.py); 45s silence = dead link. */
const HEARTBEAT_TIMEOUT_MS = 45_000;

/**
 * Same-origin ws:// URL for the alerts socket.
 * @returns {string} ws(s)://<host>/api/v1/ws/alerts
 */
function alertsUrl() {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/api/v1/ws/alerts`;
}

/**
 * Open the alerts socket; returns a handle whose close() stops everything.
 * @param {{onEvent?: (data: object) => void, onOpen?: () => void,
 *   onClose?: () => void}} hooks frame, connect, and drop callbacks
 * @returns {{close: () => void}} teardown that also cancels the reconnect
 */
export function connectAlerts({ onEvent, onOpen, onClose } = {}) {
  let socket = null;
  let closed = false;
  let attempt = 0;
  let watchdog = null;
  let reconnectTimer = null;

  /** Cancel the idle watchdog if one is armed. */
  const teardownWatchdog = () => {
    if (watchdog !== null) {
      clearTimeout(watchdog);
      watchdog = null;
    }
  };

  /** Re-arm the silence detector: no frame for 45s forces a reconnect. */
  const armWatchdog = () => {
    teardownWatchdog();
    watchdog = setTimeout(() => socket?.close(), HEARTBEAT_TIMEOUT_MS);
  };

  /**
   * Schedule one redial: exponential 1s→30s capped, ±20% jitter so a
   * server restart never sees every client at the same instant.
   * @returns {void}
   */
  const scheduleReconnect = () => {
    if (closed) return;
    const delay =
      Math.min(RECONNECT_BASE_MS * 2 ** attempt, RECONNECT_MAX_MS) *
      (0.8 + Math.random() * 0.4);
    attempt += 1;
    reconnectTimer = setTimeout(dial, delay);
  };

  /** One connection attempt (immediate, or from the backoff timer). */
  const dial = () => {
    const token = getAccessToken();
    if (!token) {
      // Logged out: keep trying cheaply — a later login re-establishes it.
      scheduleReconnect();
      return;
    }
    // Capture this attempt's socket so stale handlers can never close a
    // newer connection (the outer `socket` may already point elsewhere).
    const conn = new WebSocket(alertsUrl(), [`cambrain.jwt.${token}`]);
    socket = conn;
    conn.onopen = () => {
      attempt = 0;
      armWatchdog();
      onOpen?.();
    };
    conn.onmessage = (evt) => {
      armWatchdog();
      let frame;
      try {
        frame = JSON.parse(evt.data);
      } catch {
        return; // a garbled frame must not kill the stream
      }
      if (frame?.type === "event") onEvent?.(frame.data);
    };
    conn.onclose = () => {
      teardownWatchdog();
      onClose?.();
      scheduleReconnect();
    };
    conn.onerror = () => conn.close();
  };

  dial();

  return {
    close() {
      closed = true;
      teardownWatchdog();
      if (reconnectTimer !== null) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      socket?.close();
    },
  };
}
