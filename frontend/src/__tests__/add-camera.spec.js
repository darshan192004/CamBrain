import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import AddCameraDialog from "../camera/AddCameraDialog.vue";
import CameraGrid from "../camera/CameraGrid.vue";
import { clearTokens } from "../api/token.js";
import { useAuthStore } from "../stores/auth.js";
import { useCamerasStore } from "../stores/cameras.js";
import { envelope, jsonRes, openStream } from "./api-mocks.js";

const ME = { user_id: 1, username: "ramesh", role: "admin", site_id: 1 };

const URL_ = "rtsp://10.0.0.5/Streaming/Channels/101";

const CREATED = {
  id: 9,
  name: "Gate",
  rtsp_url: URL_,
  has_password: true,
  password: "*****",
  enabled: true,
  sample_fps: 3,
  motion_threshold: 0.05,
  frame_width: null,
  frame_height: null,
  status: "starting",
  last_error: null,
  created_at: "2026-10-05T14:02:11Z",
};

const OK_RESULT = {
  ok: true,
  message: "Connected. 640×360 @ 10 fps.",
  latency_ms: 42,
  frame_width: 640,
  frame_height: 360,
  fps: 10.2,
  error_code: null,
};

/**
 * Mount the dialog for an admin on a fresh pinia.
 * @returns {object} {wrapper, store}
 */
function mountDialog() {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().user = { ...ME, role: "admin" };
  return {
    wrapper: mount(AddCameraDialog, { global: { plugins: [pinia] } }),
    store: useCamerasStore(),
  };
}

/**
 * Fill the whole form with the fixture values.
 * @param {object} wrapper mounted dialog
 * @returns {Promise<void>} settles after every setValue
 */
async function fillForm(wrapper) {
  await wrapper.find('[data-testid="field-name"]').setValue("Gate");
  await wrapper.find('[data-testid="field-rtsp_url"]').setValue(URL_);
  await wrapper.find('[data-testid="field-username"]').setValue("admin");
  await wrapper.find('[data-testid="field-password"]').setValue("secret123");
  await wrapper.find('[data-testid="field-sample_fps"]').setValue("3");
  await wrapper.find('[data-testid="field-motion_threshold"]').setValue("0.05");
}

/**
 * fetch double for the add flow: list, create, stream, draft probe.
 * @param {object} [createRes] Response for POST /cameras
 * @param {object} [testRes] Response for POST /cameras/test
 * @returns {object} fetch mock
 */
const addFetch = (createRes, testRes) =>
  vi.fn(async (url, init = {}) => {
    const method = init.method ?? "GET";
    if (method === "POST" && String(url).endsWith("/cameras/test")) {
      return testRes ?? jsonRes(200, OK_RESULT);
    }
    if (method === "POST" && String(url).endsWith("/cameras")) {
      return createRes ?? jsonRes(201, CREATED);
    }
    if (String(url).includes("/stream")) {
      return openStream().response;
    }
    if (String(url).endsWith("/cameras")) {
      return jsonRes(200, []);
    }
    return jsonRes(200, {});
  });

beforeEach(() => {
  setActivePinia(createPinia());
  clearTokens();
  URL.createObjectURL = vi.fn(() => "blob:frame-1");
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  delete URL.createObjectURL;
  delete URL.revokeObjectURL;
  vi.unstubAllGlobals();
  clearTokens();
});

describe("AddCameraDialog form (CameraCreate payload)", () => {
  it("submits every CameraCreate field with sample_fps bounded 2–5", async () => {
    const fetchMock = addFetch();
    vi.stubGlobal("fetch", fetchMock);
    const { wrapper, store } = mountDialog();

    const fps = wrapper.find('[data-testid="field-sample_fps"]');
    expect(fps.attributes("min")).toBe("2");
    expect(fps.attributes("max")).toBe("5");
    expect(wrapper.find('[data-testid="field-enabled"]').element.checked).toBe(
      true,
    );

    await fillForm(wrapper);
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    const call = fetchMock.mock.calls.find(
      ([url, init]) =>
        (init?.method ?? "GET") === "POST" && String(url).endsWith("/cameras"),
    );
    expect(call).toBeDefined();
    expect(JSON.parse(call[1].body)).toEqual({
      name: "Gate",
      rtsp_url: URL_,
      username: "admin",
      password: "secret123",
      enabled: true,
      sample_fps: 3,
      motion_threshold: 0.05,
    });
    expect(store.cameras).toHaveLength(1);
    // Acceptance: the created row echoes no secret — only the masked
    // placeholder and the has_password flag survive the round trip.
    expect(store.cameras[0].has_password).toBe(true);
    expect(store.cameras[0].password).toBe("*****");
    expect(JSON.stringify(store.cameras[0])).not.toContain("secret123");
    wrapper.unmount();
  });

  it("surfaces an inline error on the 422 field and keeps the dialog open", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        envelope(
          422,
          "VALIDATION_ERROR",
          "rtsp_url must start with rtsp:// or rtsps://",
          { field: "rtsp_url" },
        ),
      ),
    );
    const { wrapper } = mountDialog();
    await fillForm(wrapper);
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    const fieldError = wrapper.find('[data-testid="field-error-rtsp_url"]');
    expect(fieldError.exists()).toBe(true);
    expect(fieldError.text()).toContain("rtsp://");
    expect(wrapper.find('[data-testid="add-camera-dialog"]').exists()).toBe(
      true,
    );
    wrapper.unmount();
  });

  it("shows an envelope 404 at the dialog level, not on a field", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => envelope(404, "NOT_FOUND", "camera not found")),
    );
    const { wrapper } = mountDialog();
    await fillForm(wrapper);
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    expect(wrapper.find('[data-testid="dialog-error"]').text()).toContain(
      "camera not found",
    );
    expect(wrapper.find('[data-testid="field-error-rtsp_url"]').exists()).toBe(
      false,
    );
    wrapper.unmount();
  });
});

describe("ConnectionTest (six error codes)", () => {
  it("keeps the test button disabled until the URL is present", async () => {
    vi.stubGlobal("fetch", addFetch());
    const { wrapper } = mountDialog();
    const btn = wrapper.find('[data-testid="test-connection"]');

    expect(btn.attributes("disabled")).toBeDefined();
    await wrapper.find('[data-testid="field-name"]').setValue("Gate");
    expect(
      wrapper.find('[data-testid="test-connection"]').attributes("disabled"),
    ).toBeDefined();
    await wrapper.find('[data-testid="field-rtsp_url"]').setValue(URL_);
    expect(
      wrapper.find('[data-testid="test-connection"]').attributes("disabled"),
    ).toBeUndefined();
    wrapper.unmount();
  });

  it("shows a spinner while probing, then the dims/fps/latency line", async () => {
    let settle;
    const probe = new Promise((resolve) => {
      settle = resolve;
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url) => {
        if (String(url).endsWith("/cameras/test")) {
          return probe;
        }
        return jsonRes(200, {});
      }),
    );
    const { wrapper } = mountDialog();
    await wrapper.find('[data-testid="field-name"]').setValue("Gate");
    await wrapper.find('[data-testid="field-rtsp_url"]').setValue(URL_);

    await wrapper.find('[data-testid="test-connection"]').trigger("click");
    expect(wrapper.find('[data-testid="test-spinner"]').exists()).toBe(true);
    expect(
      wrapper.find('[data-testid="test-connection"]').attributes("disabled"),
    ).toBeDefined();

    settle(jsonRes(200, OK_RESULT));
    await flushPromises();
    expect(wrapper.find('[data-testid="test-success"]').text()).toContain(
      "Connected. 640×360 @ 10 fps.",
    );
    expect(wrapper.find('[data-testid="test-success"]').text()).toContain(
      "42 ms",
    );
    expect(wrapper.find('[data-testid="test-spinner"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it.each([
    ["AUTH_FAILED", "Check the username and password."],
    [
      "CONNECT_TIMEOUT",
      "The camera did not respond in time. Check the address and network.",
    ],
    [
      "HOST_UNREACHABLE",
      "Could not reach the camera. Check the IP address and that it is on.",
    ],
    [
      "NO_SUCH_STREAM",
      "That stream path does not exist on the camera. Check the channel.",
    ],
    [
      "DECODE_FAILED",
      "Connected, but the video could not be decoded. It may use an unsupported codec.",
    ],
    ["CANCELLED", "The connection was cancelled before a frame arrived."],
  ])("%s renders its copy and is never an HTTP failure", async (code, copy) => {
    const fetchMock = vi.fn(async () =>
      jsonRes(200, { ok: false, message: "raw detail", error_code: code }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { wrapper } = mountDialog();
    await wrapper.find('[data-testid="field-name"]').setValue("Gate");
    await wrapper.find('[data-testid="field-rtsp_url"]').setValue(URL_);

    await wrapper.find('[data-testid="test-connection"]').trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-testid="test-error"]').text()).toBe(copy);
    expect(wrapper.find('[data-testid="test-http-error"]').exists()).toBe(
      false,
    );
    expect(
      fetchMock.mock.calls.some(
        ([url]) =>
          String(url).endsWith("/cameras") &&
          !String(url).endsWith("/cameras/test"),
      ),
    ).toBe(false);
    wrapper.unmount();
  });
});

describe("add flow through the grid (Checkpoint B)", () => {
  it("opens the dialog from the add tile, closes it, and the tile appears", async () => {
    vi.stubGlobal("fetch", addFetch());
    const pinia = createPinia();
    setActivePinia(pinia);
    useAuthStore().user = { ...ME, role: "admin" };
    const wrapper = mount(CameraGrid, { global: { plugins: [pinia] } });
    const store = useCamerasStore();

    await wrapper.find('[data-testid="add-camera-tile"]').trigger("click");
    expect(wrapper.find('[data-testid="add-camera-dialog"]').exists()).toBe(
      true,
    );

    await wrapper.find('[data-testid="field-name"]').setValue("Gate");
    await wrapper.find('[data-testid="field-rtsp_url"]').setValue(URL_);
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    expect(wrapper.find('[data-testid="add-camera-dialog"]').exists()).toBe(
      false,
    );
    expect(store.cameras).toHaveLength(1);
    expect(wrapper.findAll('[data-testid="camera-tile"]')).toHaveLength(1);
    wrapper.unmount();
  });

  it("gives a viewer no path to the dialog", async () => {
    vi.stubGlobal("fetch", addFetch());
    const pinia = createPinia();
    setActivePinia(pinia);
    useAuthStore().user = { ...ME, role: "viewer" };
    const wrapper = mount(CameraGrid, { global: { plugins: [pinia] } });
    await flushPromises();

    expect(wrapper.find('[data-testid="add-camera-tile"]').exists()).toBe(
      false,
    );
    expect(wrapper.find('[data-testid="add-camera-dialog"]').exists()).toBe(
      false,
    );
    wrapper.unmount();
  });
});
