/**
 * Turn an opaque `thumbnail_url` into an object URL an `<img>` can show.
 *
 * `<img src>` cannot carry the `Authorization` header (the same constraint
 * documented in `api/mjpeg.js`), so the still is fetched through the
 * authenticated client. The URL is consumed verbatim apart from stripping
 * the client's own `/api/v1` base — the path is never built by hand
 * (SECURITY §6.2, API.md §Events).
 * @module events/thumbnail
 */

import { BASE, raw } from "../api/client.js";

/**
 * Fetch a thumbnail and hand back an object URL for an `<img>`.
 * @param {string} url opaque `thumbnail_url` from an EventOut
 * @returns {Promise<string>} blob: object URL (caller revokes on unmount)
 */
export async function fetchThumbnail(url) {
  const path = url.startsWith(BASE) ? url.slice(BASE.length) : url;
  const bytes = await raw(path);
  return URL.createObjectURL(new Blob([bytes], { type: "image/jpeg" }));
}
