/**
 * In-memory token pair (design §7: tokens are never persisted to any
 * browser storage — a stolen refresh token is a revoked family, so it does
 * not sit in persistent storage waiting for an XSS to read it). Module scope
 * survives SPA navigation; a page reload re-hydrates through `POST /auth/me`.
 * @module api/token
 */

let accessToken = null;
let refreshToken = null;

/**
 * Store a fresh token pair (login or refresh response).
 * @param {{access_token: string, refresh_token: string}} pair snake_case
 *   TokenResponse shape from the API
 * @returns {void}
 */
export function setTokens(pair) {
  accessToken = pair.access_token;
  refreshToken = pair.refresh_token;
}

/**
 * Current access token, or null when logged out.
 * @returns {string|null} the bearer token
 */
export function getAccessToken() {
  return accessToken;
}

/**
 * Current refresh token, or null when logged out.
 * @returns {string|null} the opaque refresh token
 */
export function getRefreshToken() {
  return refreshToken;
}

/**
 * Drop both tokens (logout, refresh rejection, hydration failure).
 * @returns {void}
 */
export function clearTokens() {
  accessToken = null;
  refreshToken = null;
}
