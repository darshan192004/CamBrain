import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import RoiCanvas from "../roi/RoiCanvas.vue";
import RoiEditor from "../roi/RoiEditor.vue";
import ZoneList from "../roi/ZoneList.vue";
import ClassFilter from "../roi/ClassFilter.vue";
import { COCO_CLASSES } from "../data/coco.js";
import { clearTokens, setTokens } from "../api/token.js";
import { useAuthStore } from "../stores/auth.js";
import { jsonRes } from "./api-mocks.js";

const ME_ADMIN = { user_id: 1, username: "ramesh", role: "admin", site_id: 1 };

const RECT_640x360 = {
  x: 0,
  y: 0,
  left: 0,
  top: 0,
  width: 640,
  height: 360,
  right: 640,
  bottom: 360,
  toJSON: () => ({}),
};

const zone = (init) => ({
  id: 3,
  camera_id: 1,
  name: "Loading dock",
  points: [
    [0.1, 0.1],
    [0.5, 0.1],
    [0.5, 0.4],
  ],
  coverage_pct: 99.9,
  vertex_count: 3,
  class_filter: ["person"],
  active: true,
  created_at: "2026-10-05T14:02:11Z",
  ...init,
});

const ROIS = [zone()];

/**
 * Collecting fetch double: every call recorded, snapshot and CRUD stubbed.
 * @param {object} [opts] per-URL response overrides
 * @returns {{calls: object[], impl: (url: string, init?: object) => Promise<object>}} recorder + fetch impl
 */
function fetchDouble(opts = {}) {
  const calls = [];
  const impl = async (url, init = {}) => {
    if (String(url).endsWith("/snapshot")) return jsonRes(200, {});
    calls.push({
      url: String(url),
      method: init.method ?? "GET",
      body: init.body,
    });
    if (opts.post) return jsonRes(201, opts.post);
    if (opts.patch) return jsonRes(200, opts.patch);
    if (init.method === "DELETE") return jsonRes(204, null);
    return jsonRes(200, {});
  };
  return { calls, impl };
}

/**
 * Mount RoiEditor with a stubbed fetch and pinned surface rect.
 * @param {object} [opts] rois/frame/rect/fetch overrides
 * @returns {object} wrapper + fetch recorder
 */
function mountEditor(opts = {}) {
  const rec = opts.rec ?? fetchDouble();
  global.fetch = vi.fn(rec.impl ?? rec);
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:snapshot");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  setTokens({ access_token: "a", refresh_token: "r", expires_in: 3600 });
  const pinia = createPinia();
  setActivePinia(pinia);
  const auth = useAuthStore(pinia);
  auth.user = opts.user ?? ME_ADMIN;
  auth.hydrated = true;
  const wrapper = mount(RoiEditor, {
    props: {
      cameraId: 1,
      rois: opts.rois ?? ROIS,
      frameWidth: opts.frameWidth ?? 640,
      frameHeight: opts.frameHeight ?? 360,
      ...opts.props,
    },
    global: { plugins: [pinia] },
  });
  const surface = wrapper.get('[data-testid="roi-surface"]');
  surface.element.getBoundingClientRect = () => opts.rect ?? RECT_640x360;
  return { wrapper, calls: rec.calls ?? [] };
}

/**
 * Click the editor surface at display coordinates.
 * @param {object} wrapper mounted editor
 * @param {number} x display x
 * @param {number} y display y
 * @returns {Promise<void>} settles after DOM updates
 */
async function clickAt(wrapper, x, y) {
  await wrapper.get('[data-testid="roi-surface"]').trigger("click", {
    clientX: x,
    clientY: y,
  });
  await flushPromises();
}

/**
 * Draw a ~200px² triangle and close it with Enter.
 * @param {object} wrapper mounted editor
 * @returns {Promise<void>} settles after the polygon closes
 */
async function drawTriangle(wrapper) {
  await clickAt(wrapper, 100, 100);
  await clickAt(wrapper, 300, 100);
  await clickAt(wrapper, 200, 300);
  await wrapper.get('[data-testid="roi-surface"]').trigger("keydown", {
    key: "Enter",
  });
  await flushPromises();
}

beforeEach(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  clearTokens();
});

describe("ZoneList", () => {
  it("is always visible (no edit mode) and shows coverage computed from points, not the server field", () => {
    const { wrapper } = mountEditor();
    expect(wrapper.find('[data-testid="zone-list"]').exists()).toBe(true);
    // Server says 99.9%; the actual triangle is 6% of the frame.
    expect(wrapper.get('[data-testid="zone-coverage-3"]').text()).toContain(
      "6%",
    );
    expect(wrapper.get('[data-testid="zone-coverage-3"]').text()).not.toContain(
      "99.9",
    );
  });

  it("warns when a zone covers more than 80% of the frame", () => {
    const big = zone({
      id: 8,
      name: "Whole frame",
      points: [
        [0, 0],
        [1, 0],
        [1, 1],
        [0, 1],
      ],
    });
    const { wrapper } = mountEditor({ rois: [big] });
    expect(wrapper.get('[data-testid="zone-warning-8"]').text()).toMatch(
      /most of the frame/i,
    );
    const { wrapper: clean } = mountEditor();
    expect(clean.find('[data-testid="zone-warning-3"]').exists()).toBe(false);
  });

  it("select loads the zone's name and classes into the editor", async () => {
    const { wrapper } = mountEditor();
    await wrapper.get('[data-testid="zone-row-3"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[data-testid="zone-name"]').element.value).toBe(
      "Loading dock",
    );
    expect(
      wrapper.get('[data-testid="filter-class-person"]').element.checked,
    ).toBe(true);
  });

  it("duplicate creates an unsaved copy — dirty, not yet POSTed", async () => {
    const { wrapper, calls } = mountEditor();
    await wrapper.get('[data-testid="zone-duplicate-3"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[data-testid="dirty-marker"]').exists()).toBe(true);
    expect(wrapper.get('[data-testid="zone-name"]').element.value).toBe(
      "Copy of Loading dock",
    );
    const posts = calls.filter((c) => c.method === "POST");
    expect(posts).toHaveLength(0);
  });

  it("delete persists via DELETE /rois/3 and drops the row", async () => {
    const { wrapper, calls } = mountEditor();
    await wrapper.get('[data-testid="zone-delete-3"]').trigger("click");
    await flushPromises();
    const dels = calls.filter((c) => c.method === "DELETE");
    expect(dels).toHaveLength(1);
    expect(dels[0].url).toContain("/rois/3");
    expect(wrapper.find('[data-testid="zone-row-3"]').exists()).toBe(false);
  });
});

describe("ClassFilter", () => {
  it("lists every COCO class, defaults to person, and emits toggles", async () => {
    const { wrapper } = mountEditor();
    expect(COCO_CLASSES.length).toBe(80);
    const person = wrapper.get('[data-testid="filter-class-person"]');
    expect(person.element.checked).toBe(true);
    await wrapper.get('[data-testid="filter-class-car"]').setValue(true);
    await flushPromises();
    expect(
      wrapper.get('[data-testid="filter-class-car"]').element.checked,
    ).toBe(true);
    expect(
      wrapper.get('[data-testid="filter-class-person"]').element.checked,
    ).toBe(true);
  });

  it("a disabled zone still saves its class filter", async () => {
    const off = zone({ id: 5, name: "Night", active: false });
    const rec = fetchDouble({
      patch: { ...off, class_filter: ["person", "car"] },
    });
    const { wrapper, calls } = mountEditor({ rois: [off], rec });
    await wrapper.get('[data-testid="zone-row-5"]').trigger("click");
    await wrapper.get('[data-testid="filter-class-car"]').setValue(true);
    await drawTriangle(wrapper);
    await wrapper.get('[data-testid="roi-save"]').trigger("click");
    await flushPromises();
    const patch = calls.find((c) => c.method === "PATCH");
    expect(patch).toBeTruthy();
    expect(JSON.parse(patch.body).class_filter).toEqual(["person", "car"]);
  });
});

describe("RoiEditor save/cancel", () => {
  it("saving a new zone POSTs the full normalised point list", async () => {
    const rec = fetchDouble({
      post: zone({ id: 9, name: "Dock west" }),
    });
    const { wrapper, calls } = mountEditor({ rois: [], rec });
    await drawTriangle(wrapper);
    await wrapper.get('[data-testid="zone-name"]').setValue("Dock west");
    await wrapper.get('[data-testid="roi-save"]').trigger("click");
    await flushPromises();
    const post = calls.find((c) => c.method === "POST");
    expect(post.url).toContain("/cameras/1/rois");
    const body = JSON.parse(post.body);
    expect(body.name).toBe("Dock west");
    expect(body.points).toHaveLength(3);
    expect(body.class_filter).toEqual(["person"]);
    for (const [x, y] of body.points) {
      expect(x).toBeGreaterThanOrEqual(0);
      expect(x).toBeLessThanOrEqual(1);
      expect(y).toBeGreaterThanOrEqual(0);
      expect(y).toBeLessThanOrEqual(1);
    }
    expect(wrapper.find('[data-testid="dirty-marker"]').exists()).toBe(false);
  });

  it("saving an edited zone PATCHes with the full point list (destructive-edit rule)", async () => {
    const rec = fetchDouble({ patch: zone({ coverage_pct: 6.0 }) });
    const { wrapper, calls } = mountEditor({ rec });
    await wrapper.get('[data-testid="zone-row-3"]').trigger("click");
    await wrapper
      .get('[data-testid="zone-name"]')
      .setValue("Dock west evening");
    await wrapper.get('[data-testid="roi-save"]').trigger("click");
    await flushPromises();
    const patch = calls.find((c) => c.method === "PATCH");
    expect(patch.url).toContain("/rois/3");
    const body = JSON.parse(patch.body);
    expect(body.name).toBe("Dock west evening");
    expect(body.points).toEqual(ROIS[0].points);
    expect(wrapper.find('[data-testid="dirty-marker"]').exists()).toBe(false);
  });

  it("cancel restores the last-saved name and clears the dirty marker without any request", async () => {
    const { wrapper, calls } = mountEditor();
    await wrapper.get('[data-testid="zone-row-3"]').trigger("click");
    await wrapper.get('[data-testid="zone-name"]').setValue("Renamed");
    await flushPromises();
    expect(wrapper.find('[data-testid="dirty-marker"]').exists()).toBe(true);
    await wrapper.get('[data-testid="roi-cancel"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[data-testid="zone-name"]').element.value).toBe(
      "Loading dock",
    );
    expect(wrapper.find('[data-testid="dirty-marker"]').exists()).toBe(false);
    const mutations = calls.filter((c) =>
      ["POST", "PATCH", "DELETE"].includes(c.method),
    );
    expect(mutations).toHaveLength(0);
  });

  it("blur commits nothing (no destructive-on-blur)", async () => {
    const { wrapper, calls } = mountEditor();
    await wrapper.get('[data-testid="zone-name"]').setValue("Half typed");
    await wrapper.get('[data-testid="zone-name"]').trigger("blur");
    await flushPromises();
    const mutations = calls.filter((c) =>
      ["POST", "PATCH", "DELETE"].includes(c.method),
    );
    expect(mutations).toHaveLength(0);
  });

  it("resolution-change sanity: identical clicks at 640×360 and 1920×1080 emit identical normalised points", async () => {
    const { wrapper: low } = mountEditor({ frameWidth: 640, frameHeight: 360 });
    await clickAt(low, 160, 90);
    await clickAt(low, 480, 90);
    await clickAt(low, 320, 300);
    await low.get('[data-testid="roi-surface"]').trigger("keydown", {
      key: "Enter",
    });
    await flushPromises();

    const { wrapper: high } = mountEditor({
      frameWidth: 1920,
      frameHeight: 1080,
    });
    await clickAt(high, 160, 90);
    await clickAt(high, 480, 90);
    await clickAt(high, 320, 300);
    await high.get('[data-testid="roi-surface"]').trigger("keydown", {
      key: "Enter",
    });
    await flushPromises();

    const lowPoints = low.findComponent(RoiCanvas).emitted("closed")[0][0];
    const highPoints = high.findComponent(RoiCanvas).emitted("closed")[0][0];
    expect(highPoints).toEqual(lowPoints);
  });
});

describe("component contracts", () => {
  it("ZoneList renders standalone with its own props", () => {
    const list = mount(ZoneList, {
      props: { zones: ROIS, selectedId: null },
    });
    expect(list.find('[data-testid="zone-list"]').exists()).toBe(true);
  });

  it("ClassFilter standalone defaults to person", () => {
    const filter = mount(ClassFilter);
    expect(
      filter.get('[data-testid="filter-class-person"]').element.checked,
    ).toBe(true);
  });
});
