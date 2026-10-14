import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SystemView from "../settings/SystemView.vue";
import { clearTokens, setTokens } from "../api/token.js";
import { envelope, jsonRes } from "./api-mocks.js";

const pair = { access_token: "at", refresh_token: "rt", expires_in: 43200 };

/** Documented GET /system/status shape (API.md §System). */
const STATUS = {
  version: "0.1.0",
  hardware_tier: "medium",
  hardware: {
    cpu_cores: 4,
    avx2: true,
    vnni: true,
    ram_total_mb: 8002,
    ram_used_mb: 1740,
    disk_total_gb: 119,
    disk_used_pct: 31,
  },
  model: { name: "yolox_s.onnx", tier: "medium", input: [640, 640] },
  cameras: [
    {
      id: 4,
      name: "Back door",
      status: "live",
      fps: 10.2,
      frames_processed: 184203,
      last_frame_at: "2026-10-05T21:14:51Z",
    },
    {
      id: 5,
      name: "Front counter",
      status: "offline",
      last_error:
        "Could not connect to rtsp://10.0.0.6:554/… — authentication failed",
    },
  ],
  stats: { events_today: 6, alerts_sent: 6, alerts_failed: 1 },
};

/** Unauthenticated GET /system/health shape. */
const HEALTH = { status: "ok", version: "0.1.0", uptime_s: 1234.5 };

/**
 * Fetch double routing the two system endpoints.
 * @param {object} [opts] per-route response overrides
 * @returns {{calls: string[], impl: (url: string) => Promise<object>}} recorder + impl
 */
function systemFetch(opts = {}) {
  const calls = [];
  const impl = vi.fn(async (url) => {
    const u = String(url);
    calls.push(u);
    if (u.endsWith("/system/status")) {
      return jsonRes(200, opts.status ?? STATUS);
    }
    if (u.endsWith("/system/health")) {
      return jsonRes(200, opts.health ?? HEALTH);
    }
    return envelope(404, "NOT_FOUND", "not found");
  });
  return { calls, impl };
}

/**
 * Mount SystemView with the given fetch impl installed.
 * @param {object} impl fetch double
 * @returns {object} wrapper
 */
function mountSystem(impl) {
  vi.stubGlobal("fetch", impl);
  return mount(SystemView);
}

beforeEach(() => {
  setTokens(pair);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  clearTokens();
});

describe("SystemView", () => {
  it("renders tier, hardware rows, model, and disk from /system/status", async () => {
    const { impl, calls } = systemFetch();
    const wrapper = mountSystem(impl);
    await flushPromises();

    expect(wrapper.find('[data-testid="system-view"]').exists()).toBe(true);
    expect(wrapper.get('[data-testid="hw-tier"]').text()).toContain("medium");
    expect(wrapper.get('[data-testid="model-name"]').text()).toContain(
      "yolox_s.onnx",
    );
    expect(wrapper.get('[data-testid="disk-pct"]').text()).toContain("31");

    const hw = wrapper.get('[data-testid="hardware-rows"]').text();
    expect(hw).toContain("AVX2");
    expect(hw).toContain("8002");
    expect(hw).toContain("119");
    expect(wrapper.get('[data-testid="hw-cpu-cores"]').text()).toBe("4");
    expect(calls).toContain("/api/v1/system/status");
    wrapper.unmount();
  });

  it("renders per-camera stats rows", async () => {
    const { impl } = systemFetch();
    const wrapper = mountSystem(impl);
    await flushPromises();

    const rows = wrapper.findAll('[data-testid^="camera-row-"]');
    expect(rows).toHaveLength(2);
    expect(rows[0].text()).toContain("Back door");
    expect(rows[0].text()).toContain("live");
    expect(rows[0].text()).toContain("10.2");
    expect(rows[0].text()).toContain("184203");
    expect(rows[1].text()).toContain("Front counter");
    expect(rows[1].text()).toContain("offline");
    expect(rows[1].text()).toContain("authentication failed");
    wrapper.unmount();
  });

  it("shows the health ping as service status", async () => {
    const { impl, calls } = systemFetch();
    const wrapper = mountSystem(impl);
    await flushPromises();

    const status = wrapper.get('[data-testid="service-status"]').text();
    expect(status).toContain("ok");
    expect(status).toContain("1234.5");
    expect(calls).toContain("/api/v1/system/health");
    wrapper.unmount();
  });

  it("tolerates the live stub shape (empty hardware and model)", async () => {
    const { impl } = systemFetch({
      status: {
        version: "0.1.0",
        hardware_tier: "unknown",
        hardware: {},
        model: {},
        cameras: [{ id: 1, name: "Front counter", status: "error" }],
        stats: { cameras_total: 1, retention_days: 7 },
      },
    });
    const wrapper = mountSystem(impl);
    await flushPromises();

    expect(wrapper.find('[data-testid="system-view"]').exists()).toBe(true);
    expect(wrapper.get('[data-testid="hw-tier"]').text()).toContain("unknown");
    const rows = wrapper.findAll('[data-testid^="camera-row-"]');
    expect(rows).toHaveLength(1);
    expect(rows[0].text()).toContain("error");
    wrapper.unmount();
  });
});
