import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import EventsView from "../views/EventsView.vue";
import { clearTokens, setTokens } from "../api/token.js";
import { createAppRouter } from "../router.js";
import { envelope, jsonRes } from "./api-mocks.js";

const pair = { access_token: "at", refresh_token: "rt", expires_in: 43200 };

/**
 * One EventOut row; thumbnails/clips derive from the id unless overridden.
 * @param {object} [init] field overrides
 * @returns {object} EventOut fixture
 */
const eventOut = (init = {}) => ({
  id: 812,
  camera: { id: 4, name: "Back door" },
  rule: { id: 3, name: "Back door after hours" },
  severity: "critical",
  summary: "1 person in Loading dock",
  started_at: "2026-10-05T21:14:33Z",
  ended_at: null,
  duration_ms: 18400,
  acknowledged: false,
  has_clip: false,
  detections: [
    {
      class_name: "person",
      confidence: 0.71,
      bbox: [412, 188, 468, 366],
      zone_name: "Loading dock",
    },
  ],
  ...init,
  thumbnail_url:
    init.thumbnail_url ?? `/api/v1/events/${init.id ?? 812}/thumbnail`,
  clip_url: init.clip_url ?? `/api/v1/events/${init.id ?? 812}/clip`,
});

const TWO = {
  items: [eventOut(), eventOut({ id: 813, acknowledged: true })],
  total: 2,
  limit: 20,
  offset: 0,
};

const FORTY_FIVE = {
  items: Array.from({ length: 20 }, (_, i) =>
    eventOut({ id: 812 + i, acknowledged: false }),
  ),
  total: 45,
  limit: 20,
  offset: 0,
};

/**
 * Collecting fetch double: every call recorded; thumbnails 404 unless
 * opts.thumb === "ok"; bulk-ack answers with a count; the event page
 * answers from opts.page.
 * @param {object} [opts] per-URL response overrides
 * @returns {{calls: object[], impl: (url: string, init?: object) => Promise<object>}} recorder + fetch impl
 */
function logFetch(opts = {}) {
  const calls = [];
  const impl = vi.fn(async (url, init = {}) => {
    const u = String(url);
    calls.push({ url: u, method: init.method ?? "GET", body: init.body });
    if (u.endsWith("/thumbnail")) {
      return opts.thumb === "ok"
        ? jsonRes(200, {})
        : envelope(404, "NOT_FOUND", "thumbnail not found");
    }
    if (u.includes("/events/acknowledge-bulk")) {
      return jsonRes(200, { acknowledged: 2 });
    }
    if (u.includes("/events?")) {
      return jsonRes(200, opts.page ?? TWO);
    }
    return jsonRes(200, {});
  });
  return { calls, impl };
}

/**
 * Mount EventsView over a fresh router/pinia and a stubbed fetch.
 * @param {object} [opts] passed to logFetch
 * @returns {Promise<{wrapper: object, calls: object[]}>} mounted view + call log
 */
async function mountLog(opts = {}) {
  setTokens(pair);
  const { calls, impl } = logFetch(opts);
  vi.stubGlobal("fetch", impl);
  const router = createAppRouter();
  const pinia = createPinia();
  setActivePinia(pinia);
  const wrapper = mount(EventsView, { global: { plugins: [pinia, router] } });
  await router.isReady();
  await flushPromises();
  return { wrapper, calls };
}

/**
 * Only the list-page requests (thumbnails are `/events/{id}/thumbnail`).
 * @param {object[]} calls recorded fetch calls
 * @returns {object[]} list calls in order
 */
const listCalls = (calls) => calls.filter((c) => c.url.includes("/events?"));

beforeEach(() => {
  setActivePinia(createPinia());
  clearTokens();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  clearTokens();
});

describe("event log filters (API.md §Events)", () => {
  it("builds the exact documented query from every filter", async () => {
    const { wrapper, calls } = await mountLog();

    await wrapper.find('[data-testid="filter-camera"]').setValue("4");
    await wrapper.find('[data-testid="filter-severity"]').setValue("critical");
    await wrapper
      .find('[data-testid="filter-from"]')
      .setValue("2026-10-01T00:00");
    await wrapper
      .find('[data-testid="filter-to"]')
      .setValue("2026-10-08T00:00");
    await wrapper.find('[data-testid="filter-acknowledged"]').setValue("false");
    await wrapper.find('[data-testid="filter-q"]').setValue("loading");
    await wrapper.find('[data-testid="filter-apply"]').trigger("click");
    await flushPromises();

    expect(listCalls(calls).at(-1).url).toBe(
      "/api/v1/events?camera_id=4&severity=critical&from=2026-10-01T00%3A00&to=2026-10-08T00%3A00&acknowledged=false&q=loading&limit=20&offset=0&sort=-started_at",
    );
  });

  it("reset clears every filter and reloads the unfiltered query", async () => {
    const { wrapper, calls } = await mountLog();

    await wrapper.find('[data-testid="filter-camera"]').setValue("4");
    await wrapper.find('[data-testid="filter-q"]').setValue("loading");
    await wrapper.find('[data-testid="filter-reset"]').trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-testid="filter-camera"]').element.value).toBe(
      "",
    );
    expect(wrapper.find('[data-testid="filter-q"]').element.value).toBe("");
    expect(listCalls(calls).at(-1).url).toBe(
      "/api/v1/events?limit=20&offset=0&sort=-started_at",
    );
  });
});

describe("event table", () => {
  it("shows each severity as a coloured badge that always carries its text", async () => {
    const { wrapper } = await mountLog({
      page: {
        items: [
          eventOut({ severity: "critical" }),
          eventOut({ id: 813, severity: "warning" }),
          eventOut({ id: 814, severity: "info" }),
        ],
        total: 3,
        limit: 20,
        offset: 0,
      },
    });

    const critical = wrapper.find('[data-testid="severity-812"]');
    expect(critical.text()).toBe("critical");
    expect(critical.attributes("class")).toContain("text-alert-critical");
    const warning = wrapper.find('[data-testid="severity-813"]');
    expect(warning.text()).toBe("warning");
    expect(warning.attributes("class")).toContain("text-alert-warning");
    expect(wrapper.find('[data-testid="severity-814"]').text()).toBe("info");
  });

  it("fetches a row still from the opaque thumbnail_url and renders it", async () => {
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:thumb-812");
    const { wrapper, calls } = await mountLog({ thumb: "ok" });

    expect(calls.map((c) => c.url)).toContain("/api/v1/events/812/thumbnail");
    const img = wrapper.find('[data-testid="row-thumb-812"]');
    expect(img.exists()).toBe(true);
    expect(img.attributes("src")).toBe("blob:thumb-812");
  });

  it("falls back to a placeholder when the thumbnail 404s", async () => {
    const { wrapper } = await mountLog();

    expect(wrapper.find('[data-testid="row-thumb-812"]').exists()).toBe(false);
    expect(
      wrapper.find('[data-testid="row-thumb-placeholder-812"]').exists(),
    ).toBe(true);
  });

  it("bulk-acknowledges the selected rows in one POST and reflects it", async () => {
    const { wrapper, calls } = await mountLog();

    await wrapper.find('[data-testid="row-select-812"]').setValue(true);
    await wrapper.find('[data-testid="row-select-813"]').setValue(true);
    await wrapper.find('[data-testid="bulk-ack"]').trigger("click");
    await flushPromises();

    const post = calls.find(
      (c) => c.method === "POST" && c.url.includes("acknowledge-bulk"),
    );
    expect(post).toBeTruthy();
    expect(JSON.parse(post.body)).toEqual({ event_ids: [812, 813] });
    expect(wrapper.find('[data-testid="ack-state-812"]').text()).toContain(
      "Acknowledged",
    );
    expect(wrapper.find('[data-testid="ack-state-813"]').text()).toContain(
      "Acknowledged",
    );
    expect(
      wrapper.find('[data-testid="bulk-ack"]').attributes("disabled"),
    ).toBeDefined();
  });

  it("steps offset pagination against total and bounds the buttons", async () => {
    const { wrapper, calls } = await mountLog({ page: FORTY_FIVE });

    expect(wrapper.find('[data-testid="page-info"]').text()).toBe(
      "Showing 1–20 of 45",
    );
    expect(
      wrapper.find('[data-testid="page-prev"]').attributes("disabled"),
    ).toBeDefined();
    expect(
      wrapper.find('[data-testid="page-next"]').attributes("disabled"),
    ).toBeUndefined();

    await wrapper.find('[data-testid="page-next"]').trigger("click");
    await flushPromises();
    expect(listCalls(calls).at(-1).url).toContain("offset=20");
    expect(wrapper.find('[data-testid="page-info"]').text()).toBe(
      "Showing 21–40 of 45",
    );

    await wrapper.find('[data-testid="page-next"]').trigger("click");
    await flushPromises();
    expect(listCalls(calls).at(-1).url).toContain("offset=40");
    expect(wrapper.find('[data-testid="page-info"]').text()).toBe(
      "Showing 41–45 of 45",
    );
    expect(
      wrapper.find('[data-testid="page-next"]').attributes("disabled"),
    ).toBeDefined();

    await wrapper.find('[data-testid="page-prev"]').trigger("click");
    await flushPromises();
    expect(listCalls(calls).at(-1).url).toContain("offset=20");
  });

  it("renders the no-events copy when the log is empty", async () => {
    const { wrapper } = await mountLog({
      page: { items: [], total: 0, limit: 20, offset: 0 },
    });

    expect(wrapper.text()).toContain("No events yet");
    expect(wrapper.findAll("tbody tr")).toHaveLength(0);
    expect(wrapper.find('[data-testid="page-info"]').exists()).toBe(false);
  });
});
