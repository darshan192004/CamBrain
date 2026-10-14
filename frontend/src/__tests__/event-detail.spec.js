import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import EventDetailView from "../views/EventDetailView.vue";
import { clearTokens, setTokens } from "../api/token.js";
import { createAppRouter } from "../router.js";
import { jsonRes } from "./api-mocks.js";

const pair = { access_token: "at", refresh_token: "rt", expires_in: 43200 };

/**
 * One EventOut row with one person detection at a known pixel box.
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
  thumbnail_url: "/api/v1/events/812/thumbnail",
  clip_url: "/api/v1/events/812/clip",
  detections: [
    {
      class_name: "person",
      confidence: 0.71,
      bbox: [160, 90, 320, 180],
      zone_name: "Loading dock",
    },
  ],
  ...init,
});

/**
 * Collecting fetch double: event, camera frame size, acknowledge, and the
 * (always-200) still all answer from opts.
 * @param {object} [opts] `{event, camera}` overrides
 * @returns {{calls: object[], impl: (url: string, init?: object) => Promise<object>}} recorder + fetch impl
 */
function detailFetch(opts = {}) {
  const calls = [];
  const impl = vi.fn(async (url, init = {}) => {
    const u = String(url);
    calls.push({ url: u, method: init.method ?? "GET", body: init.body });
    if (u.endsWith("/thumbnail")) {
      return jsonRes(200, {});
    }
    if (u.includes("/acknowledge")) {
      return jsonRes(200, {
        ...(opts.event ?? eventOut()),
        acknowledged: true,
      });
    }
    if (u.includes("/events/")) {
      return jsonRes(200, opts.event ?? eventOut());
    }
    if (u.includes("/cameras/")) {
      return jsonRes(
        200,
        opts.camera ?? { frame_width: 640, frame_height: 360 },
      );
    }
    return jsonRes(200, {});
  });
  return { calls, impl };
}

/**
 * Mount EventDetailView over a fresh router/pinia and a stubbed fetch.
 * @param {object} [opts] passed to detailFetch
 * @returns {Promise<{wrapper: object, calls: object[]}>} mounted view + call log
 */
async function mountDetail(opts = {}) {
  setTokens(pair);
  const { calls, impl } = detailFetch(opts);
  vi.stubGlobal("fetch", impl);
  const router = createAppRouter();
  const pinia = createPinia();
  setActivePinia(pinia);
  const wrapper = mount(EventDetailView, {
    props: { id: "812" },
    global: { plugins: [pinia, router] },
  });
  await router.isReady();
  await flushPromises();
  return { wrapper, calls };
}

/**
 * The computed inline style of a detection box, parsed per property.
 * @param {object} wrapper mounted detail view
 * @returns {CSSStyleDeclaration} the box element's style
 */
const boxStyle = (wrapper) =>
  wrapper.find('[data-testid="detect-box-0"]').element.style;

beforeEach(() => {
  setActivePinia(createPinia());
  clearTokens();
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:still-812");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  clearTokens();
});

describe("detection overlay (plan 4.16)", () => {
  it("draws detection boxes in frame-percent space at 640x360", async () => {
    const { wrapper } = await mountDetail();

    const style = boxStyle(wrapper);
    expect(style.left).toBe("25%");
    expect(style.top).toBe("25%");
    expect(style.width).toBe("25%");
    expect(style.height).toBe("25%");
  });

  it("rescales the same detections for a 1920x1080 camera", async () => {
    const { wrapper } = await mountDetail({
      camera: { frame_width: 1920, frame_height: 1080 },
    });

    const style = boxStyle(wrapper);
    expect(parseFloat(style.left)).toBeCloseTo(8.3333, 3);
    expect(parseFloat(style.top)).toBeCloseTo(8.3333, 3);
    expect(parseFloat(style.width)).toBeCloseTo(8.3333, 3);
    expect(parseFloat(style.height)).toBeCloseTo(8.3333, 3);
  });
});

describe("event detail", () => {
  it("lists each detection with class, confidence, and zone", async () => {
    const { wrapper } = await mountDetail();

    const row = wrapper.find('[data-testid="detection-row-0"]');
    expect(row.text()).toContain("person");
    expect(row.text()).toContain("71%");
    expect(row.text()).toContain("Loading dock");
  });

  it("acknowledges the event via POST and shows the acknowledged state", async () => {
    const { wrapper, calls } = await mountDetail();

    await wrapper.find('[data-testid="event-ack"]').trigger("click");
    await flushPromises();

    const post = calls.find(
      (c) => c.method === "POST" && c.url.endsWith("/events/812/acknowledge"),
    );
    expect(post).toBeTruthy();
    expect(wrapper.find('[data-testid="event-ack"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="ack-state"]').text()).toContain(
      "Acknowledged",
    );
  });

  it("hides the clip behind the Phase 5 note when has_clip is false", async () => {
    const { wrapper } = await mountDetail({
      event: eventOut({ has_clip: false }),
    });

    expect(wrapper.find('[data-testid="event-clip"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="clip-note"]').text()).toContain(
      "Clip available after recording (Phase 5)",
    );
  });

  it("renders a video bound to the opaque clip_url when has_clip is true", async () => {
    const { wrapper } = await mountDetail({
      event: eventOut({ has_clip: true }),
    });

    const video = wrapper.find('[data-testid="event-clip"]');
    expect(video.exists()).toBe(true);
    expect(video.attributes("src")).toBe("/api/v1/events/812/clip");
    expect(wrapper.find('[data-testid="clip-note"]').exists()).toBe(false);
  });

  it("loads the still from the opaque thumbnail_url", async () => {
    const { wrapper, calls } = await mountDetail();

    expect(calls.map((c) => c.url)).toContain("/api/v1/events/812/thumbnail");
    const still = wrapper.find('[data-testid="detail-still"]');
    expect(still.exists()).toBe(true);
    expect(still.attributes("src")).toBe("blob:still-812");
  });
});
