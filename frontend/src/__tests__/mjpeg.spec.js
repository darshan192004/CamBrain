import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

import { openMjpeg, streamUrl } from "../api/mjpeg.js";
import { clearTokens, setTokens } from "../api/token.js";
import {
  JPEG,
  enc,
  emptyPart,
  framePart,
  joinBytes,
  openStream,
} from "./api-mocks.js";

/**
 * Flush pending microtasks (and a macrotask hop) without fake timers.
 * @returns {Promise<void>} resolves after one event-loop turn
 */
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("openMjpeg (plan D3 byte vectors)", () => {
  beforeEach(() => {
    clearTokens();
    let seq = 0;
    URL.createObjectURL = vi.fn(() => `blob:frame-${(seq += 1)}`);
    URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    delete URL.createObjectURL;
    delete URL.revokeObjectURL;
    vi.unstubAllGlobals();
    clearTokens();
  });

  it("emits one frame for a single-chunk part, carrying the in-memory bearer", async () => {
    setTokens({ access_token: "tok-1", refresh_token: "r", expires_in: 43200 });
    const fetchMock = vi.fn(
      async () => closingStream([framePart(JPEG)]).response,
    );
    vi.stubGlobal("fetch", fetchMock);
    const onFrame = vi.fn();
    const onError = vi.fn();

    openMjpeg(streamUrl(4), {
      onFrame,
      onError,
      signal: new AbortController().signal,
    });

    await vi.waitFor(() => expect(onFrame).toHaveBeenCalledTimes(1));
    expect(onFrame).toHaveBeenCalledWith("blob:frame-1");
    expect(URL.createObjectURL.mock.calls[0][0].size).toBe(JPEG.length);
    const [, init] = fetchMock.mock.calls[0];
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/cameras/4/stream");
    expect(init.headers.Authorization).toBe("Bearer tok-1");
    expect(init.headers["X-CambBrain-Client"]).toBe("cambrain-dashboard");
    expect(init.signal).toBeDefined();
    await vi.waitFor(() => expect(onError).toHaveBeenCalledWith("ended"));
  });

  it("reassembles a boundary split across chunk boundaries", async () => {
    const bytes = framePart(JPEG);
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () => closingStream([bytes.slice(0, 4), bytes.slice(4)]).response,
      ),
    );
    const onFrame = vi.fn();

    openMjpeg("u", {
      onFrame,
      onError: vi.fn(),
      signal: new AbortController().signal,
    });

    await vi.waitFor(() => expect(onFrame).toHaveBeenCalledTimes(1));
    expect(URL.createObjectURL.mock.calls[0][0].size).toBe(JPEG.length);
  });

  it("buffers a JPEG split across chunks and never emits it truncated", async () => {
    const headers = enc(
      `--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ${JPEG.length}\r\n\r\n`,
    );
    const stream = openStream();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => stream.response),
    );
    const onFrame = vi.fn();

    openMjpeg("u", {
      onFrame,
      onError: vi.fn(),
      signal: new AbortController().signal,
    });

    stream.push(joinBytes(headers, JPEG.slice(0, 4)));
    await tick();
    expect(onFrame).not.toHaveBeenCalled();

    stream.push(joinBytes(JPEG.slice(4), enc("\r\n")));
    await vi.waitFor(() => expect(onFrame).toHaveBeenCalledTimes(1));
    expect(URL.createObjectURL.mock.calls[0][0].size).toBe(JPEG.length);
  });

  it("skips garbage and empty parts, then resyncs on the next frame", async () => {
    const JPEG_B = Uint8Array.from([0xff, 0xd8, 0x0a, 0x0b, 0xff, 0xd9]);
    const garbage = enc("junk-junk-junk-junk");
    const stream = openStream();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => stream.response),
    );
    const onFrame = vi.fn();

    openMjpeg("u", {
      onFrame,
      onError: vi.fn(),
      signal: new AbortController().signal,
    });

    stream.push(
      joinBytes(
        framePart(JPEG),
        garbage,
        emptyPart(),
        garbage,
        framePart(JPEG_B),
      ),
    );

    await vi.waitFor(() => expect(onFrame).toHaveBeenCalledTimes(2));
    expect(URL.createObjectURL.mock.calls[0][0].size).toBe(JPEG.length);
    expect(URL.createObjectURL.mock.calls[1][0].size).toBe(JPEG_B.length);
  });

  it("reports 503 NO_CAPACITY as onError('capacity')", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: false, status: 503, headers: new Headers() })),
    );
    const onFrame = vi.fn();
    const onError = vi.fn();

    openMjpeg("u", {
      onFrame,
      onError,
      signal: new AbortController().signal,
    });

    await vi.waitFor(() => expect(onError).toHaveBeenCalledWith("capacity"));
    expect(onFrame).not.toHaveBeenCalled();
  });

  it("keeps a replaced frame URL alive until the grace period passes", async () => {
    vi.useFakeTimers();
    try {
      const stream = openStream();
      vi.stubGlobal(
        "fetch",
        vi.fn(async () => stream.response),
      );
      const onFrame = vi.fn();

      openMjpeg("u", {
        onFrame,
        onError: vi.fn(),
        signal: new AbortController().signal,
      });

      stream.push(framePart(JPEG));
      await vi.advanceTimersByTimeAsync(0);
      expect(onFrame).toHaveBeenCalledTimes(1);

      stream.push(framePart(JPEG));
      await vi.advanceTimersByTimeAsync(0);
      expect(onFrame).toHaveBeenCalledTimes(2);
      // Frame 1 was replaced by frame 2: its URL must stay fetchable for
      // the <img>, otherwise the load dies with ERR_BLOB_OUT_OF_MEMORY.
      expect(URL.revokeObjectURL).not.toHaveBeenCalled();

      await vi.advanceTimersByTimeAsync(1500);
      expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1);
      expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:frame-1");
    } finally {
      vi.useRealTimers();
    }
  });

  it("stops emitting after AbortController aborts", async () => {
    const stream = openStream();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => stream.response),
    );
    const onFrame = vi.fn();
    const onError = vi.fn();
    const controller = new AbortController();

    openMjpeg("u", { onFrame, onError, signal: controller.signal });
    stream.push(framePart(JPEG));
    await vi.waitFor(() => expect(onFrame).toHaveBeenCalledTimes(1));

    controller.abort();
    stream.push(framePart(JPEG));
    await tick();

    expect(onFrame).toHaveBeenCalledTimes(1);
    expect(onError).not.toHaveBeenCalled();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:frame-1");
  });
});

/**
 * A stream that yields the given chunks, then closes cleanly.
 * @param {Uint8Array[]} chunks ordered body chunks
 * @returns {object} Response-like stream
 */
function closingStream(chunks) {
  const stream = openStream();
  for (const chunk of chunks) {
    stream.push(chunk);
  }
  stream.end();
  return stream;
}
