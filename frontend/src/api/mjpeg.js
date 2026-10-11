/**
 * MJPEG client (plan D3): `fetch` + a byte-stream multipart parser.
 *
 * The access token lives in memory and rides `Authorization: Bearer` — an
 * `<img src>` cannot send it — and `AbortController` tears a tile down.
 * Frames are handed to `onFrame` as object URLs; the previous URL is
 * revoked as soon as a new frame replaces it, and the last one is revoked
 * when the stream stops. The parser buffers chunks and only emits a frame
 * once `Content-Length` bytes have arrived, so a boundary or JPEG split
 * across chunks can never surface a truncated image.
 * @module api/mjpeg
 */

import { BASE, CLIENT_HEADER, CLIENT_VALUE } from "./client.js";
import { getAccessToken } from "./token.js";

const BOUNDARY = bytes("--frame\r\n");
const HEADER_END = Uint8Array.from([13, 10, 13, 10]);

/**
 * ASCII text as bytes (headers and boundaries are ASCII by definition).
 * @param {string} text input characters
 * @returns {Uint8Array} the encoded bytes
 */
function bytes(text) {
  const out = new Uint8Array(text.length);
  for (let i = 0; i < text.length; i += 1) {
    out[i] = text.charCodeAt(i);
  }
  return out;
}

/**
 * Index of `needle` inside `hay` at or after `from`.
 * @param {Uint8Array} hay buffer to search
 * @param {Uint8Array} needle pattern to look for
 * @param {number} from start offset
 * @returns {number} match offset, or -1 when absent
 */
function indexOf(hay, needle, from) {
  const last = hay.length - needle.length;
  for (let i = Math.max(from, 0); i <= last; i += 1) {
    let hit = true;
    for (let j = 0; j < needle.length; j += 1) {
      if (hay[i + j] !== needle[j]) {
        hit = false;
        break;
      }
    }
    if (hit) {
      return i;
    }
  }
  return -1;
}

/**
 * Decode a header slice to text (latin1 is exact for ASCII).
 * @param {Uint8Array} view the header bytes
 * @returns {string} the decoded header block
 */
function decode(view) {
  let text = "";
  for (let i = 0; i < view.length; i += 1) {
    text += String.fromCharCode(view[i]);
  }
  return text;
}

/**
 * Full stream URL for one camera's MJPEG endpoint.
 * @param {number} cameraId camera primary key
 * @returns {string} `/api/v1/cameras/{id}/stream`
 */
export function streamUrl(cameraId) {
  return `${BASE}/cameras/${cameraId}/stream`;
}

/**
 * Open an MJPEG stream and parse it into object-URL frames.
 *
 * Reasons passed to `onError`: `capacity` (503 NO_CAPACITY — plan D1 cap),
 * `http` (any other non-2xx), `network` (fetch/stream failure), `ended`
 * (server closed the stream). An aborted signal is silence by contract —
 * teardown must not surface as an error.
 * @param {string} url full stream URL (see {@link streamUrl})
 * @param {{onFrame: (frameUrl: string) => void, onError:
 *   (reason: string) => void, signal: object}} handlers frame/error
 *   callbacks and the AbortSignal that tears the stream down
 * @returns {void}
 */
export function openMjpeg(url, { onFrame, onError, signal }) {
  if (signal.aborted) {
    return;
  }

  let buffer = new Uint8Array(0);
  let scan = 0;
  let stopped = false;
  let frameUrl = null;

  const stop = () => {
    stopped = true;
    if (frameUrl) {
      URL.revokeObjectURL(frameUrl);
      frameUrl = null;
    }
  };
  signal.addEventListener("abort", stop, { once: true });

  /**
   * Publish one JPEG as an object URL, revoking the previous frame.
   * @param {Uint8Array} jpeg complete frame bytes
   * @returns {void}
   */
  function emit(jpeg) {
    if (frameUrl) {
      URL.revokeObjectURL(frameUrl);
    }
    frameUrl = URL.createObjectURL(new Blob([jpeg], { type: "image/jpeg" }));
    onFrame(frameUrl);
  }

  /**
   * Drain every complete part from the buffer; leave partial data queued.
   * @returns {void}
   */
  function consume() {
    for (;;) {
      const at = indexOf(buffer, BOUNDARY, scan);
      if (at === -1) {
        // No boundary here: keep only the tail, since one may be split
        // across the next chunk ("garbage between parts" resyncs).
        const keep = BOUNDARY.length - 1;
        if (buffer.length > keep) {
          buffer = buffer.slice(buffer.length - keep);
        }
        scan = 0;
        return;
      }
      const headerStart = at + BOUNDARY.length;
      // The header terminator is "\r\n\r\n"; searching from the boundary's
      // own CRLF also matches the zero-length error part ("" headers).
      const term = indexOf(buffer, HEADER_END, at + BOUNDARY.length - 2);
      if (term === -1) {
        return;
      }
      const match = /content-length:\s*(\d+)/i.exec(
        decode(buffer.subarray(headerStart, term)),
      );
      const length = match ? Number(match[1]) : 0;
      const bodyStart = term + HEADER_END.length;
      if (buffer.length < bodyStart + length) {
        return;
      }
      if (length > 0) {
        emit(buffer.subarray(bodyStart, bodyStart + length));
      }
      buffer = buffer.slice(bodyStart + length);
      scan = 0;
    }
  }

  (async () => {
    let response;
    try {
      const headers = { [CLIENT_HEADER]: CLIENT_VALUE };
      const access = getAccessToken();
      if (access) {
        headers.Authorization = `Bearer ${access}`;
      }
      response = await fetch(url, { headers, signal });
    } catch {
      if (!stopped) {
        onError("network");
      }
      return;
    }
    if (stopped) {
      return;
    }
    if (!response.ok) {
      onError(response.status === 503 ? "capacity" : "http");
      return;
    }
    const reader = response.body.getReader();
    try {
      for (;;) {
        if (stopped) {
          return;
        }
        const { done, value } = await reader.read();
        if (stopped) {
          return;
        }
        if (done) {
          break;
        }
        if (value && value.length) {
          const next = new Uint8Array(buffer.length + value.length);
          next.set(buffer, 0);
          next.set(value, buffer.length);
          buffer = next;
          consume();
        }
      }
      if (!stopped) {
        onError("ended");
      }
    } catch {
      if (!stopped) {
        onError("network");
      }
    }
  })();
}
