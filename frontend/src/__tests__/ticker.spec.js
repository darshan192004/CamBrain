import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import EventTicker from "../camera/EventTicker.vue";
import { clearTokens, setTokens } from "../api/token.js";
import { createAppRouter } from "../router.js";
import { jsonRes } from "./api-mocks.js";

const ME = { user_id: 1, username: "ramesh", role: "admin", site_id: 1 };
const pair = { access_token: "at", refresh_token: "rt", expires_in: 43200 };

const ITEMS = Array.from({ length: 7 }, (_, i) => ({
  id: i + 1,
  summary: `person ${i + 1}`,
  severity: "warning",
  started_at: `2026-10-05T10:0${i}:00Z`,
  acknowledged: false,
  camera: { id: 1, name: "Gate" },
}));

const PAGE = { items: ITEMS, total: 7, limit: 5, offset: 0 };

/**
 * fetch double: the event page answers with the fixture, identity answers
 * from /auth/me.
 * @returns {object} fetch mock
 */
const tickerFetch = () =>
  vi.fn(async (url) => {
    if (String(url).includes("/events?")) {
      return jsonRes(200, PAGE);
    }
    if (String(url).endsWith("/auth/me")) {
      return jsonRes(200, ME);
    }
    if (String(url).endsWith("/auth/refresh")) {
      return jsonRes(200, pair);
    }
    return jsonRes(200, {});
  });

/**
 * Count only ticker polls (hydration may also call /auth/me).
 * @param {object} fetchMock the spy under test
 * @returns {number} poll calls so far
 */
const pollCount = (fetchMock) =>
  fetchMock.mock.calls.filter(([url]) => String(url).includes("/events?"))
    .length;

beforeEach(() => {
  setActivePinia(createPinia());
  clearTokens();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  clearTokens();
});

describe("EventTicker (plan D6 — no websocket)", () => {
  it("polls the newest five every 10s, links each, and stops on unmount", async () => {
    setTokens(pair);
    const fetchMock = tickerFetch();
    vi.stubGlobal("fetch", fetchMock);
    // The ticker owns the timer; the test drives the tick directly so the
    // poll cadence is proven without waiting on wall-clock 10s.
    const intervalSpy = vi.spyOn(globalThis, "setInterval").mockReturnValue(42);
    const clearSpy = vi
      .spyOn(globalThis, "clearInterval")
      .mockImplementation(() => {});

    const router = createAppRouter();
    const pinia = createPinia();
    setActivePinia(pinia);
    const wrapper = mount(EventTicker, {
      global: { plugins: [pinia, router] },
    });
    await router.isReady();
    await flushPromises();

    expect(pollCount(fetchMock)).toBe(1);
    expect(intervalSpy).toHaveBeenCalledWith(expect.any(Function), 10_000);
    const links = wrapper.findAll("a");
    expect(links.map((a) => a.attributes("href"))).toEqual([
      "/events/7",
      "/events/6",
      "/events/5",
      "/events/4",
      "/events/3",
    ]);

    await links[0].trigger("click");
    await vi.waitFor(() =>
      expect(router.currentRoute.value.path).toBe("/events/7"),
    );

    await intervalSpy.mock.calls[0][0]();
    await flushPromises();
    expect(pollCount(fetchMock)).toBe(2);

    wrapper.unmount();
    expect(clearSpy).toHaveBeenCalledWith(42);
  });

  it("renders an empty state before any events exist", async () => {
    setTokens(pair);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonRes(200, { items: [], total: 0, limit: 5, offset: 0 }),
      ),
    );
    vi.spyOn(globalThis, "setInterval").mockReturnValue(7);
    const router = createAppRouter();
    const wrapper = mount(EventTicker, {
      global: { plugins: [createPinia(), router] },
    });
    await router.isReady();
    await flushPromises();

    expect(wrapper.text()).toContain("No recent events.");
    wrapper.unmount();
  });
});
