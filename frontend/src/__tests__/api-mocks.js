/**
 * Shared fetch-response doubles for API-boundary tests (not a spec file —
 * vitest only collects `*.spec.js`).
 * @module __tests__/api-mocks
 */

/**
 * A minimal Response stand-in for the fetch mock.
 * @param {number} status HTTP status
 * @param {object} payload JSON body
 * @returns {object} Response-like object
 */
export const jsonRes = (status, payload) => ({
  ok: status >= 200 && status < 300,
  status,
  headers: new Headers(),
  json: async () => payload,
  arrayBuffer: async () => new ArrayBuffer(0),
});

/**
 * The API's standard error envelope.
 * @param {number} status HTTP status
 * @param {string} code machine code
 * @param {string} message human message
 * @param {object} [extra] extra envelope fields (field, correlation_id)
 * @returns {object} Response-like error
 */
export const envelope = (status, code, message, extra = {}) =>
  jsonRes(status, {
    error: { code, message, field: null, correlation_id: "cid-1", ...extra },
  });

/**
 * ASCII bytes (test vectors avoid TextEncoder for portability).
 * @param {string} text ASCII input
 * @returns {Uint8Array} the encoded bytes
 */
export const enc = (text) =>
  Uint8Array.from([...text].map((c) => c.charCodeAt(0)));

/**
 * Concatenate byte arrays.
 * @param {...Uint8Array} parts pieces to join
 * @returns {Uint8Array} one buffer containing every part in order
 */
export const joinBytes = (...parts) => {
  const total = parts.reduce((n, p) => n + p.length, 0);
  const out = new Uint8Array(total);
  let at = 0;
  for (const part of parts) {
    out.set(part, at);
    at += part.length;
  }
  return out;
};

/** A JPEG-shaped payload: magic prefix, body, EOI marker. */
export const JPEG = Uint8Array.from([
  0xff, 0xd8, 0xff, 0xe0, 1, 2, 3, 0xff, 0xd9,
]);

/**
 * One `multipart/x-mixed-replace` frame part exactly as the backend emits
 * it (`stream/mjpeg.py`).
 * @param {Uint8Array} jpeg the frame bytes
 * @returns {Uint8Array} boundary + headers + body + CRLF
 */
export const framePart = (jpeg) =>
  joinBytes(
    enc("--frame\r\n"),
    enc(`Content-Type: image/jpeg\r\nContent-Length: ${jpeg.length}\r\n\r\n`),
    jpeg,
    enc("\r\n"),
  );

/**
 * The zero-length part the backend emits on a source error.
 * @returns {Uint8Array} the bare boundary line
 */
export const emptyPart = () => enc("--frame\r\n\r\n");

/**
 * A hand-driven MJPEG response: push() feeds the next chunk, end() closes
 * the stream once the queue drains, and reads park (never resolve) while
 * the queue is empty — an open stream that has gone quiet.
 * @returns {{response: object, push: (chunk: Uint8Array) => void,
 *   end: () => void}} the Response double, its chunk feeder, and close
 */
export const openStream = () => {
  const queue = [];
  let notify = null;
  let ended = false;
  const wake = () => {
    if (notify) {
      const resume = notify;
      notify = null;
      resume();
    }
  };
  const push = (chunk) => {
    queue.push(chunk);
    wake();
  };
  const end = () => {
    ended = true;
    wake();
  };
  const read = async () => {
    for (;;) {
      if (queue.length) {
        return { done: false, value: queue.shift() };
      }
      if (ended) {
        return { done: true, value: undefined };
      }
      await new Promise((resolve) => {
        notify = resolve;
      });
    }
  };
  return {
    response: {
      ok: true,
      status: 200,
      headers: new Headers(),
      body: {
        getReader: () => ({ read, releaseLock: () => {} }),
      },
    },
    push,
    end,
  };
};
