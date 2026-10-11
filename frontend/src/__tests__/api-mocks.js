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
