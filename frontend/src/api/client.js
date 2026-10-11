/**
 * Thin fetch wrapper for the CamBrain API (design §9: fetch, no axios).
 *
 * Responsibilities: the `X-CambBrain-Client` CSRF header on every call, JSON
 * bodies with `Content-Type: application/json`, `Authorization: Bearer` when
 * a token is held, error-envelope decoding into {@link ApiError}, and one
 * single-flight refresh-and-retry on 401. Bytes endpoints (snapshot,
 * thumbnail) go through {@link raw} so nothing JSON-parses a JPEG.
 * @module api/client
 */

import {
  clearTokens,
  getAccessToken,
  getRefreshToken,
  setTokens,
} from "./token.js";

const BASE = "/api/v1";
const CLIENT_HEADER = "X-CambBrain-Client";
const CLIENT_VALUE = "cambrain-dashboard";

/**
 * A non-2xx response decoded from the API's `{error: {...}}` envelope.
 * @property {string} code machine-readable code (API.md §A3)
 * @property {string} message human message, safe to show to the operator
 * @property {string|null} field offending field for 422 validation, else null
 * @property {number} status HTTP status
 * @property {string|null} correlationId `correlation_id` from the envelope
 */
export class ApiError extends Error {
  /**
   * @param {{code: string, message: string, field?: string|null,
   *   status: number, correlationId?: string|null}} init decoded envelope
   * @returns {void}
   */
  constructor({ code, message, field = null, status, correlationId = null }) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.field = field;
    this.status = status;
    this.correlationId = correlationId;
  }
}

/**
 * Called once when a refresh attempt fails (session is gone). The token pair
 * has already been cleared before this runs.
 * @type {(err: Error) => void}
 */
let onAuthError = () => {};

/**
 * Register the handler invoked when refresh fails and the session is dropped.
 * @param {(err: Error) => void} handler replacement handler
 * @returns {void}
 */
export function setOnAuthError(handler) {
  onAuthError = handler;
}

/**
 * Decode a failed Response into an ApiError, tolerating a non-envelope body.
 * @param {Response} res failed fetch response
 * @returns {Promise<ApiError>} the decoded error
 */
async function toApiError(res) {
  let payload;
  try {
    payload = await res.json();
  } catch {
    payload = null;
  }
  const envelope =
    payload && typeof payload === "object" ? payload.error : null;
  return new ApiError({
    code: envelope?.code ?? "UNKNOWN",
    message: envelope?.message ?? `Request failed with status ${res.status}`,
    field: envelope?.field ?? null,
    status: res.status,
    correlationId:
      envelope?.correlation_id ?? res.headers.get("x-correlation-id"),
  });
}

let refreshInFlight = null;

/**
 * Rotate the refresh token. Single-flight: concurrent 401s share one
 * `POST /auth/refresh`. On failure the pair is cleared and onAuthError fires
 * exactly once for the shared attempt.
 * @returns {Promise<object>} the new TokenResponse
 */
function refreshSession() {
  if (refreshInFlight) {
    return refreshInFlight;
  }
  const pending = (async () => {
    const current = getRefreshToken();
    if (!current) {
      const err = new ApiError({
        code: "UNAUTHENTICATED",
        message: "Your session has expired.",
        status: 401,
      });
      clearTokens();
      onAuthError(err);
      throw err;
    }
    try {
      const res = await fetch(`${BASE}/auth/refresh`, {
        method: "POST",
        headers: {
          [CLIENT_HEADER]: CLIENT_VALUE,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ refresh_token: current }),
      });
      if (!res.ok) {
        throw await toApiError(res);
      }
      const pair = await res.json();
      setTokens(pair);
      return pair;
    } catch (err) {
      clearTokens();
      onAuthError(err instanceof Error ? err : new Error(String(err)));
      throw err;
    }
  })().finally(() => {
    refreshInFlight = null;
  });
  refreshInFlight = pending;
  return pending;
}

/**
 * Core request. On a 401 (with a refresh token held) it refreshes once,
 * single-flight, and retries the original request exactly one time.
 * @param {string} path path under `/api/v1`, e.g. `/cameras`
 * @param {{method?: string, body?: object, raw?: boolean, auth?: boolean}}
 *   [options] method/body and raw (bytes response) or auth=false for login
 * @returns {Promise<object|ArrayBuffer|null>} parsed JSON, bytes for raw,
 *   or null for 204
 */
export async function request(path, options = {}) {
  const method = options.method ?? "GET";
  const hasBody = options.body !== undefined;
  const wantsAuth = options.auth !== false;

  const headers = { [CLIENT_HEADER]: CLIENT_VALUE };
  if (hasBody) {
    headers["Content-Type"] = "application/json";
  }
  const send = () => {
    const h = { ...headers };
    const access = getAccessToken();
    if (wantsAuth && access) {
      h.Authorization = `Bearer ${access}`;
    }
    return fetch(BASE + path, {
      method,
      headers: h,
      body: hasBody ? JSON.stringify(options.body) : undefined,
    });
  };

  let res = await send();
  if (res.status === 401 && wantsAuth && getRefreshToken()) {
    await refreshSession();
    res = await send();
  }
  if (!res.ok) {
    throw await toApiError(res);
  }
  if (options.raw) {
    return res.arrayBuffer();
  }
  if (res.status === 204) {
    return null;
  }
  return res.json();
}

/**
 * GET helper.
 * @param {string} path path under `/api/v1`
 * @param {{auth?: boolean}} [options] auth=false to skip the bearer header
 * @returns {Promise<object>} parsed JSON body
 */
export function get(path, options) {
  return request(path, { ...options, method: "GET" });
}

/**
 * POST helper with a JSON body.
 * @param {string} path path under `/api/v1`
 * @param {object} body JSON-serialisable request body
 * @param {{auth?: boolean}} [options] request options
 * @returns {Promise<object>} parsed JSON body
 */
export function post(path, body, options) {
  return request(path, { ...options, method: "POST", body });
}

/**
 * PATCH helper with a JSON body.
 * @param {string} path path under `/api/v1`
 * @param {object} body JSON-serialisable request body
 * @param {{auth?: boolean}} [options] request options
 * @returns {Promise<object>} parsed JSON body
 */
export function patch(path, body, options) {
  return request(path, { ...options, method: "PATCH", body });
}

/**
 * DELETE helper.
 * @param {string} path path under `/api/v1`
 * @param {{auth?: boolean}} [options] request options
 * @returns {Promise<object>} parsed JSON body (null on 204)
 */
export function del(path, options) {
  return request(path, { ...options, method: "DELETE" });
}

/**
 * Bytes endpoint (snapshot, thumbnail): response is returned as an
 * ArrayBuffer without JSON parsing.
 * @param {string} path path under `/api/v1`
 * @param {{auth?: boolean}} [options] request options
 * @returns {Promise<ArrayBuffer>} raw response bytes
 */
export function raw(path, options) {
  return request(path, { ...options, raw: true });
}
