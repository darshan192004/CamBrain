/**
 * Turn the opaque `clip_url` into an object URL a `<video>` can play.
 *
 * `<video src>` cannot carry the `Authorization` header (the same constraint
 * `thumbnail.js` documents for stills), so the clip is fetched through the
 * authenticated client. The URL is consumed verbatim apart from stripping
 * the client's own `/api/v1` base — the path is never built by hand
 * (SECURITY §6.2, API.md §Events).
 * @module events/clip
 */

import { BASE, raw } from "../api/client.js";

/**
 * Fetch the recorded clip and hand back an object URL for a `<video>`.
 * @param {string} url opaque `clip_url` from an EventOut
 * @returns {Promise<string>} blob: object URL (caller revokes on unmount)
 */
export async function fetchClip(url) {
  const path = url.startsWith(BASE) ? url.slice(BASE.length) : url;
  const bytes = await raw(path);
  return URL.createObjectURL(new Blob([bytes], { type: "video/mp4" }));
}
