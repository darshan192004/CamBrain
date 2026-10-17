import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { connectAlerts } from "../api/alertsSocket.js";
import { clearTokens, setTokens } from "../api/token.js";

const pair = { access_token: "at", refresh_token: "rt", expires_in: 43200 };

/** Minimal WebSocket double: records dials, replays handlers synchronously. */
class FakeSocket {
  static instances = [];
  constructor(url, protocols) {
    this.url = url;
    this.protocols = protocols;
    this.sent = [];
    FakeSocket.instances.push(this);
  }
  send(data) {
    this.sent.push(data);
  }
  close() {
    this.closed = true;
  }
  // test helpers
  emit(data) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
}

beforeEach(() => {
  FakeSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeSocket);
  setTokens(pair);
  vi.useFakeTimers();
  // Pin the reconnect jitter (0.8–1.2×) so backoff assertions are exact.
  vi.spyOn(Math, "random").mockReturnValue(0.5);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  clearTokens();
  vi.restoreAllMocks();
});

describe("connectAlerts (API A3)", () => {
  it("dials with the jwt subprotocol", () => {
    const handle = connectAlerts({ onEvent: () => {} });
    const sock = FakeSocket.instances[0];
    expect(sock.protocols).toEqual(["cambrain.jwt.at"]);
    expect(sock.url).toContain("/api/v1/ws/alerts");
    handle.close();
  });

  it("invokes onEvent for event frames only", () => {
    const onEvent = vi.fn();
    const handle = connectAlerts({ onEvent });
    const sock = FakeSocket.instances[0];
    sock.emit({ type: "heartbeat", data: { ts: "x" } });
    expect(onEvent).not.toHaveBeenCalled();
    sock.onmessage?.({ data: "{ malformed" }); // a garbled frame is ignored
    expect(onEvent).not.toHaveBeenCalled();
    const event = { type: "event", data: { id: 9, summary: "p" } };
    sock.emit(event);
    expect(onEvent).toHaveBeenCalledWith(event.data);
    handle.close();
  });

  it("reconnects with backoff after a drop", () => {
    const handle = connectAlerts({ onEvent: () => {} });
    const sock = FakeSocket.instances[0];
    sock.onerror?.();
    sock.onclose?.();
    expect(FakeSocket.instances).toHaveLength(1);
    vi.advanceTimersByTime(1_100);
    expect(FakeSocket.instances.length).toBeGreaterThanOrEqual(2);
    handle.close();
  });

  it("fires onOpen on connect and onClose on drop", () => {
    const onOpen = vi.fn();
    const onClose = vi.fn();
    const handle = connectAlerts({ onOpen, onClose });
    const sock = FakeSocket.instances[0];
    sock.onopen?.();
    expect(onOpen).toHaveBeenCalledTimes(1);
    sock.onerror?.();
    sock.onclose?.();
    expect(onClose).toHaveBeenCalledTimes(1);
    handle.close();
  });

  it("force-closes a socket silent for 45s; a heartbeat re-arms it", () => {
    const handle = connectAlerts({ onEvent: () => {} });
    const sock = FakeSocket.instances[0];
    sock.onopen?.(); // arms the watchdog (server heartbeats every 30s)
    vi.advanceTimersByTime(40_000);
    sock.emit({ type: "heartbeat", data: { ts: "x" } }); // frame at t=40s
    vi.advanceTimersByTime(40_000); // t=80s — only 40s of silence
    expect(sock.closed).toBeUndefined();
    vi.advanceTimersByTime(10_000); // t=90s — 50s of silence
    expect(sock.closed).toBe(true);
    handle.close();
  });

  it("does not redial after the handle is closed", () => {
    const handle = connectAlerts({ onEvent: () => {} });
    handle.close();
    // A close event arriving after teardown must not schedule a redial.
    FakeSocket.instances[0].onclose?.();
    vi.advanceTimersByTime(60_000);
    expect(FakeSocket.instances).toHaveLength(1);
  });
});
