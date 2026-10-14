/**
 * Event list store (Pinia): holds the ticker's window — the five newest
 * events. Plan D6 has no websocket; the ticker re-runs `load` on an
 * interval and a failed poll keeps the last list rather than flashing the
 * strip empty.
 * @module stores/events
 */

import { defineStore } from "pinia";

import { get } from "../api/client.js";

/**
 * @returns {object} Pinia store options for the recent-events window
 */
export const useEventsStore = defineStore("events", {
  state: () => ({
    /** @type {object[]} EventOut rows, newest first, capped at 5 */
    events: [],
  }),

  actions: {
    /**
     * Fetch `GET /events?limit=5&sort=-started_at` and keep the five
     * newest (the sort is re-applied client-side so an unsorted page can
     * never render oldest-first).
     * @returns {Promise<void>} resolves after the poll settles
     */
    async load() {
      try {
        const page = await get("/events?limit=5&sort=-started_at");
        const items = Array.isArray(page?.items) ? page.items : [];
        this.events = [...items]
          .sort((a, b) =>
            String(b.started_at).localeCompare(String(a.started_at)),
          )
          .slice(0, 5);
      } catch {
        // Keep the previous window — a blip must not blank the ticker.
      }
    },
  },
});
