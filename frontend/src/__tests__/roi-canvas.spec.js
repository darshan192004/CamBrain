import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import RoiCanvas from "../roi/RoiCanvas.vue";
import { JPEG } from "./api-mocks.js";

// jsdom has no layout: pin a display rect so click→pixel maths is deterministic.
// Container 640×360 = frame aspect → no letterbox in the default suite.
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

// Container 800×360 with a 640×360 frame: letterboxed left/right pads of 80px.
const RECT_800x360 = {
  x: 0,
  y: 0,
  left: 0,
  top: 0,
  width: 800,
  height: 360,
  right: 800,
  bottom: 360,
  toJSON: () => ({}),
};

/**
 * Mount RoiCanvas against a stubbed snapshot fetch and object-URL factory.
 * @param {object} [opts] rect to pin on the surface, extra props
 * @returns {object} the wrapper
 */
function mountCanvas(opts = {}) {
  const rect = opts.rect ?? RECT_640x360;
  global.fetch = vi.fn(async () => ({
    ok: true,
    status: 200,
    headers: new Headers(),
    arrayBuffer: async () =>
      JPEG.buffer.slice(JPEG.byteOffset, JPEG.byteOffset + JPEG.byteLength),
    json: async () => ({}),
  }));
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:snapshot");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  const wrapper = mount(RoiCanvas, {
    props: { cameraId: 1, frameWidth: 640, frameHeight: 360, ...opts.props },
  });
  const surface = wrapper.get('[data-testid="roi-surface"]');
  surface.element.getBoundingClientRect = () => rect;
  return wrapper;
}

/**
 * Fire a click on the surface at display coordinates.
 * @param {object} wrapper mounted RoiCanvas
 * @param {number} x display x
 * @param {number} y display y
 * @returns {Promise<void>} settles after the DOM updates
 */
async function clickAt(wrapper, x, y) {
  await wrapper.get('[data-testid="roi-surface"]').trigger("click", {
    clientX: x,
    clientY: y,
  });
  await flushPromises();
}

/**
 * Dispatch a real PointerEvent (VTU cannot assign clientX on MouseEvent).
 * @param {Element} el target element
 * @param {string} type event type
 * @param {number} x client x
 * @param {number} y client y
 * @returns {void} fires synchronously
 */
function firePointer(el, type, x, y) {
  const ev = new PointerEvent(type, {
    bubbles: true,
    cancelable: true,
    clientX: x,
    clientY: y,
    pointerId: 1,
  });
  el.dispatchEvent(ev);
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
});

describe("RoiCanvas — snapshot + letterbox", () => {
  it("fetches a frozen snapshot via POST /cameras/1/snapshot and shows it as a blob image", async () => {
    const canvas = mountCanvas();
    await flushPromises();
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/cameras/1/snapshot"),
      expect.objectContaining({ method: "POST" }),
    );
    const img = canvas.get('[data-testid="roi-snapshot"]');
    expect(img.attributes("src")).toBe("blob:snapshot");
  });

  it("letterboxes a 640×360 frame inside an 800×360 display: clicks in the pad map to the frame edge", async () => {
    const canvas = mountCanvas({ rect: RECT_800x360 });
    await flushPromises();
    // Click at display x=10 (inside the 80px left pad) → clamps to normalised x=0.
    await clickAt(canvas, 10, 180);
    await clickAt(canvas, 400, 20);
    await clickAt(canvas, 790, 340);
    await canvas.get('[data-testid="roi-surface"]').trigger("keydown", {
      key: "Enter",
    });
    await flushPromises();
    const [closed] = canvas.emitted("closed") ?? [];
    expect(closed).toBeTruthy();
    expect(closed[0][0][0]).toBeCloseTo(0, 5);
  });
});

describe("RoiCanvas — draw", () => {
  it("click adds a vertex; Enter with <3 vertices does nothing", async () => {
    const canvas = mountCanvas();
    await flushPromises();
    await clickAt(canvas, 100, 100);
    await clickAt(canvas, 200, 100);
    expect(canvas.findAll('[data-testid^="vertex-"]')).toHaveLength(2);
    await canvas.get('[data-testid="roi-surface"]').trigger("keydown", {
      key: "Enter",
    });
    await flushPromises();
    expect(canvas.emitted("closed")).toBeUndefined();
  });

  it("Enter with 3 vertices closes and emits normalised points in [0,1]", async () => {
    const canvas = mountCanvas();
    await flushPromises();
    await clickAt(canvas, 0, 0);
    await clickAt(canvas, 640, 0);
    await clickAt(canvas, 320, 360);
    await canvas.get('[data-testid="roi-surface"]').trigger("keydown", {
      key: "Enter",
    });
    await flushPromises();
    const [closed] = canvas.emitted("closed");
    expect(closed[0]).toHaveLength(3);
    for (const [x, y] of closed[0]) {
      expect(x).toBeGreaterThanOrEqual(0);
      expect(x).toBeLessThanOrEqual(1);
      expect(y).toBeGreaterThanOrEqual(0);
      expect(y).toBeLessThanOrEqual(1);
    }
    expect(closed[0][0]).toEqual([0, 0]);
    expect(closed[0][1][0]).toBeCloseTo(1, 5);
    expect(closed[0][2][1]).toBeCloseTo(1, 5);
  });

  it("a 4th click on the first vertex closes the polygon", async () => {
    const canvas = mountCanvas();
    await flushPromises();
    await clickAt(canvas, 100, 100);
    await clickAt(canvas, 300, 100);
    await clickAt(canvas, 200, 300);
    await clickAt(canvas, 100, 100);
    await flushPromises();
    const [closed] = canvas.emitted("closed");
    expect(closed[0]).toHaveLength(3);
  });

  it("Esc cancels the whole draft", async () => {
    const canvas = mountCanvas();
    await flushPromises();
    await clickAt(canvas, 100, 100);
    await clickAt(canvas, 200, 100);
    await canvas.get('[data-testid="roi-surface"]').trigger("keydown", {
      key: "Escape",
    });
    await flushPromises();
    expect(canvas.emitted("cancelled")).toBeTruthy();
    expect(canvas.findAll('[data-testid^="vertex-"]')).toHaveLength(0);
  });

  it("blocks closing under 500px² at source resolution with an explanation; draft stays open", async () => {
    const canvas = mountCanvas();
    await flushPromises();
    // 3 points within a 10×10px box → ~50px² < 500.
    await clickAt(canvas, 300, 180);
    await clickAt(canvas, 310, 180);
    await clickAt(canvas, 305, 190);
    await canvas.get('[data-testid="roi-surface"]').trigger("keydown", {
      key: "Enter",
    });
    await flushPromises();
    expect(canvas.emitted("closed")).toBeUndefined();
    const err = canvas.get('[data-testid="min-area-error"]');
    expect(err.text()).toMatch(/500/);
    expect(canvas.findAll('[data-testid^="vertex-"]')).toHaveLength(3);
  });
});

describe("RoiCanvas — drag", () => {
  it("pointerdown on a vertex moves it; emitted polygon is normalised through fromPixels", async () => {
    const canvas = mountCanvas();
    await flushPromises();
    await clickAt(canvas, 100, 100);
    await clickAt(canvas, 300, 100);
    await clickAt(canvas, 200, 300);
    const v0 = canvas.get('[data-testid="vertex-0"]').element;
    firePointer(v0, "pointerdown", 100, 100);
    firePointer(
      canvas.get('[data-testid="roi-surface"]').element,
      "pointermove",
      320,
      180,
    );
    firePointer(
      canvas.get('[data-testid="roi-surface"]').element,
      "pointerup",
      320,
      180,
    );
    await canvas.get('[data-testid="roi-surface"]').trigger("keydown", {
      key: "Enter",
    });
    await flushPromises();
    const [closed] = canvas.emitted("closed");
    expect(closed[0][0][0]).toBeCloseTo(320 / 640, 5);
    expect(closed[0][0][1]).toBeCloseTo(180 / 360, 5);
  });
});

describe("RoiCanvas — keyboard", () => {
  it("arrows nudge the focused vertex 1px; Shift+arrows 10px; Enter closes", async () => {
    const canvas = mountCanvas();
    await flushPromises();
    await clickAt(canvas, 100, 100);
    await clickAt(canvas, 300, 100);
    await clickAt(canvas, 200, 300);
    const v0 = canvas.get('[data-testid="vertex-0"]');
    await v0.trigger("keydown", { key: "ArrowRight" });
    await v0.trigger("keydown", { key: "ArrowDown", shiftKey: true });
    await canvas.get('[data-testid="roi-surface"]').trigger("keydown", {
      key: "Enter",
    });
    await flushPromises();
    const [closed] = canvas.emitted("closed");
    expect(closed[0][0][0]).toBeCloseTo(101 / 640, 5);
    expect(closed[0][0][1]).toBeCloseTo(110 / 360, 5);
  });
});
