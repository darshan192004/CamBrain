import { mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import CameraGrid from "../camera/CameraGrid.vue";
import CameraTile from "../camera/CameraTile.vue";
import { clearTokens } from "../api/token.js";
import { useAuthStore } from "../stores/auth.js";
import { JPEG, framePart, jsonRes, openStream } from "./api-mocks.js";

const ME = { user_id: 1, username: "ramesh", role: "admin", site_id: 1 };

/**
 * @param {object} init camera fields (id/name default)
 * @returns {object} CameraOut fixture
 */
const camera = (init) => ({
  id: 1,
  name: "Back door",
  rtsp_url: "rtsp://10.0.0.5/Streaming/Channels/101",
  has_password: true,
  password: "*****",
  enabled: true,
  sample_fps: 2,
  motion_threshold: 0.02,
  frame_width: 640,
  frame_height: 360,
  status: "live",
  last_error: null,
  created_at: "2026-10-05T14:02:11Z",
  ...init,
});

const CAMS = [
  camera({ id: 1, name: "Back door" }),
  camera({ id: 2, name: "Front counter" }),
  camera({
    id: 3,
    name: "Gate",
    enabled: false,
    status: "offline",
    last_error: "auth failed",
  }),
];

/**
 * fetch double: the camera list answers with the fixture, stream requests
 * park on an open stream that never delivers a frame.
 * @param {object[]} [rows] camera list payload
 * @returns {object} fetch mock
 */
const gridFetch = (rows = CAMS) =>
  vi.fn(async (url) => {
    if (String(url).includes("/stream")) {
      return openStream().response;
    }
    if (String(url).endsWith("/cameras")) {
      return jsonRes(200, rows);
    }
    return jsonRes(200, {});
  });

/**
 * Mount the grid for a role on a fresh pinia.
 * @param {string} role "admin" | "viewer"
 * @returns {object} mounted wrapper
 */
function mountGrid(role) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const auth = useAuthStore();
  auth.user = { ...ME, role };
  return mount(CameraGrid, { global: { plugins: [pinia] } });
}

/**
 * Mount a single tile with the given camera fixture.
 * @param {object} cam camera payload
 * @returns {object} mounted wrapper
 */
function mountTile(cam) {
  const pinia = createPinia();
  setActivePinia(pinia);
  return mount(CameraTile, {
    props: { camera: cam },
    global: { plugins: [pinia] },
  });
}

beforeEach(() => {
  setActivePinia(createPinia());
  clearTokens();
  let seq = 0;
  URL.createObjectURL = vi.fn(() => `blob:tile-${(seq += 1)}`);
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  delete URL.createObjectURL;
  delete URL.revokeObjectURL;
  vi.unstubAllGlobals();
  clearTokens();
});

describe("CameraGrid", () => {
  it("renders one tile per camera plus the admin add tile on the design grid", async () => {
    vi.stubGlobal("fetch", gridFetch());
    const wrapper = mountGrid("admin");

    await vi.waitFor(() =>
      expect(wrapper.findAll('[data-testid="camera-tile"]')).toHaveLength(3),
    );
    expect(wrapper.find('[data-testid="add-camera-tile"]').exists()).toBe(true);

    const grid = wrapper.find('[data-testid="camera-grid"]');
    expect(grid.classes()).toContain(
      "grid-cols-[repeat(auto-fill,minmax(320px,1fr))]",
    );
    expect(wrapper.find(".aspect-video").exists()).toBe(true);
    expect(wrapper.find("h1").text()).toBe("Cameras");
    wrapper.unmount();
  });

  it("omits the add tile for a viewer (defence in depth)", async () => {
    vi.stubGlobal("fetch", gridFetch());
    const wrapper = mountGrid("viewer");

    await vi.waitFor(() =>
      expect(wrapper.findAll('[data-testid="camera-tile"]')).toHaveLength(3),
    );
    expect(wrapper.find('[data-testid="add-camera-tile"]').exists()).toBe(
      false,
    );
    wrapper.unmount();
  });
});

describe("CameraTile state machine", () => {
  it("stays starting until the first frame, then goes live with a text status", async () => {
    const stream = openStream();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => stream.response),
    );
    const wrapper = mountTile(camera({ id: 7 }));
    await vi.waitFor(() =>
      expect(wrapper.find('[data-testid="tile-status"]').text()).toBe(
        "Starting…",
      ),
    );
    expect(wrapper.attributes("data-state")).toBe("starting");
    expect(wrapper.find("img").exists()).toBe(false);

    stream.push(framePart(JPEG));
    await vi.waitFor(() =>
      expect(wrapper.find('[data-testid="tile-status"]').text()).toBe("Live"),
    );
    expect(wrapper.attributes("data-state")).toBe("live");
    expect(wrapper.find("img").attributes("src")).toBe("blob:tile-1");
    wrapper.unmount();
  });

  it("shows the error reason with a Retry button that re-opens the stream", async () => {
    const retryStream = openStream();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 503, headers: new Headers() })
      .mockResolvedValueOnce(retryStream.response);
    vi.stubGlobal("fetch", fetchMock);
    const wrapper = mountTile(camera({ id: 7 }));

    await vi.waitFor(() =>
      expect(wrapper.find('[data-testid="tile-status"]').text()).toBe("Error"),
    );
    expect(wrapper.attributes("data-state")).toBe("error");
    expect(wrapper.text()).toContain("live-stream capacity");
    expect(wrapper.find('[data-testid="tile-retry"]').exists()).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await wrapper.find('[data-testid="tile-retry"]').trigger("click");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    retryStream.push(framePart(JPEG));
    await vi.waitFor(() =>
      expect(wrapper.find('[data-testid="tile-status"]').text()).toBe("Live"),
    );
    expect(wrapper.find('[data-testid="tile-retry"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("dims an offline camera with a text status and never opens its stream", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const wrapper = mountTile(
      camera({
        id: 9,
        enabled: false,
        status: "offline",
        last_error: "auth failed",
      }),
    );
    await vi.waitFor(() =>
      expect(wrapper.find('[data-testid="tile-status"]').text()).toBe(
        "Offline",
      ),
    );
    expect(wrapper.attributes("data-state")).toBe("offline");
    expect(wrapper.classes()).toContain("opacity-60");
    expect(wrapper.text()).toContain("auth failed");
    expect(fetchMock).not.toHaveBeenCalled();
    wrapper.unmount();
  });
});
