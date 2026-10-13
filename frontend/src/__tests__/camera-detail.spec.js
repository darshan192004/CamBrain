import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { createMemoryHistory, createRouter } from "vue-router";

import CameraCard from "../camera/CameraCard.vue";
import CameraDetail from "../camera/CameraDetail.vue";
import CameraTile from "../camera/CameraTile.vue";
import RuleForm from "../rules/RuleForm.vue";
import RulesList from "../rules/RulesList.vue";
import { COCO_CLASSES } from "../data/coco.js";
import { clearTokens, setTokens } from "../api/token.js";
import { useAuthStore } from "../stores/auth.js";
import { envelope, jsonRes } from "./api-mocks.js";

const ME_ADMIN = { user_id: 1, username: "ramesh", role: "admin", site_id: 1 };
const ME_VIEWER = { user_id: 2, username: "meera", role: "viewer", site_id: 1 };

const cameraOut = (init) => ({
  id: 1,
  name: "Shop Front",
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

const ruleOut = (init) => ({
  id: 7,
  camera_id: 1,
  roi_id: null,
  name: "Back door after hours",
  enabled: true,
  classes: ["person"],
  confidence_threshold: 0.55,
  cooldown_seconds: 60,
  active_hours: {
    timezone: "Asia/Kolkata",
    windows: [{ start: "22:00", end: "06:00" }],
  },
  severity: "critical",
  notify: true,
  created_at: "2026-10-05T14:02:11Z",
  ...init,
});

const roiOut = (init) => ({
  id: 3,
  camera_id: 1,
  name: "Loading dock",
  points: [
    [0.1, 0.1],
    [0.5, 0.1],
    [0.5, 0.4],
  ],
  coverage_pct: 12.5,
  vertex_count: 3,
  class_filter: null,
  active: true,
  created_at: "2026-10-05T14:02:11Z",
  ...init,
});

/**
 * A pinia with an established session (tokens + user projection).
 * @param {object} user /auth/me projection to install
 * @returns {object} the pinia instance
 */
function authPinia(user = ME_ADMIN) {
  setTokens({ access_token: "a", refresh_token: "r", expires_in: 3600 });
  const pinia = createPinia();
  setActivePinia(pinia);
  const auth = useAuthStore(pinia);
  auth.user = user;
  auth.hydrated = true;
  return pinia;
}

/**
 * Routes stub good enough for CameraDetail navigation assertions.
 * @returns {object} a memory-history router with cameras routes
 */
function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/cameras", name: "cameras", component: { template: "<div />" } },
      {
        path: "/cameras/:id",
        name: "camera-detail",
        component: { template: "<div />" },
      },
    ],
  });
}

async function mountDetail(fetchImpl, { user = ME_ADMIN } = {}) {
  const pinia = authPinia(user);
  global.fetch = vi.fn(fetchImpl);
  const router = makeRouter();
  const wrapper = mount(CameraDetail, {
    props: { id: "1" },
    global: { plugins: [pinia, router] },
  });
  await router.isReady();
  await flushPromises();
  return { wrapper, router, pinia };
}

/**
 * Fill RuleForm fields the way an operator would.
 * @param {object} form mounted RuleForm wrapper
 * @param {object} overrides field values to steer away from the defaults
 * @returns {Promise<object>} the values the form should emit
 */
async function fillForm(form, overrides = {}) {
  const values = {
    name: "Back door after hours",
    classes: ["person"],
    confidence_threshold: 0.55,
    cooldown_seconds: 60,
    severity: "critical",
    notify: true,
    enabled: true,
    roi_id: 3,
    active_hours: {
      timezone: "Asia/Kolkata",
      windows: [{ start: "22:00", end: "06:00" }],
    },
    ...overrides,
  };
  await form.get('[data-testid="rule-name"]').setValue(values.name);
  for (const cls of COCO_CLASSES) {
    const box = form.find(`[data-testid="class-option-${cls}"]`);
    if (!box.exists()) continue;
    const want = values.classes.includes(cls);
    if (box.element.checked !== want) await box.setValue(want);
  }
  await form
    .get('[data-testid="confidence"]')
    .setValue(values.confidence_threshold);
  await form.get('[data-testid="cooldown"]').setValue(values.cooldown_seconds);
  await form.get('[data-testid="severity"]').setValue(values.severity);
  const notify = form.find('[data-testid="notify"]');
  if (notify.element.checked !== values.notify) {
    await notify.setValue(values.notify);
  }
  const enabled = form.find('[data-testid="enabled"]');
  if (enabled.exists() && enabled.element.checked !== values.enabled) {
    await enabled.setValue(values.enabled);
  }
  if (values.roi_id != null) {
    await form
      .get('[data-testid="roi-select"]')
      .setValue(String(values.roi_id));
  }
  // windows editor starts with one row; clear to match the payload shape
  while (
    form.findAll('[data-testid="window-row"]').length >
    values.active_hours.windows.length
  ) {
    await form.findAll('[data-testid="remove-window"]').at(-1).trigger("click");
  }
  while (
    form.findAll('[data-testid="window-row"]').length <
    values.active_hours.windows.length
  ) {
    await form.get('[data-testid="add-window"]').trigger("click");
  }
  await form
    .get('[data-testid="timezone"]')
    .setValue(values.active_hours.timezone);
  const rows = form.findAll('[data-testid="window-row"]');
  values.active_hours.windows.forEach((w, i) => {
    rows[i].find('[data-testid="window-start"]').element.value = w.start;
    rows[i].find('[data-testid="window-end"]').element.value = w.end;
  });
  await rows[0].find('[data-testid="window-start"]').trigger("change");
  return values;
}

beforeEach(() => {
  setActivePinia(createPinia());
  clearTokens();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("data/coco", () => {
  it("exports the 80 COCO class names in canonical order", () => {
    expect(COCO_CLASSES).toHaveLength(80);
    expect(COCO_CLASSES[0]).toBe("person");
    expect(COCO_CLASSES[79]).toBe("toothbrush");
    expect(COCO_CLASSES).toContain("tv");
    expect(new Set(COCO_CLASSES).size).toBe(80);
  });
});

describe("RuleForm", () => {
  const rois = [roiOut(), roiOut({ id: 9, name: "Aisle 2" })];

  const mountForm = (initial = null) =>
    mount(RuleForm, { props: { rois, initial } });

  it("blocks submit when classes are empty", async () => {
    const form = mountForm();
    await fillForm(form, { classes: ["person"] });
    await form.find('[data-testid="class-option-person"]').setValue(false);
    await form.get('[data-testid="rule-form"]').trigger("submit");
    expect(form.emitted("save")).toBeUndefined();
    expect(form.find('[data-testid="field-error-classes"]').text()).toMatch(
      /at least one/i,
    );
  });

  it.each([
    ["confidence above 1", { confidence_threshold: 1.5 }, "confidence"],
    ["confidence below 0", { confidence_threshold: -0.1 }, "confidence"],
    ["cooldown below 5", { cooldown_seconds: 3 }, "cooldown"],
    ["cooldown above 86400", { cooldown_seconds: 86401 }, "cooldown"],
  ])("rejects %s", async (_label, bad, field) => {
    const form = mountForm();
    await fillForm(form, bad);
    await form.get('[data-testid="rule-form"]').trigger("submit");
    expect(form.emitted("save")).toBeUndefined();
    expect(form.find(`[data-testid="field-error-${field}"]`).exists()).toBe(
      true,
    );
  });

  it("rejects more than four active-hours windows", async () => {
    const form = mountForm();
    await fillForm(form);
    for (let i = 0; i < 3; i += 1) {
      await form.get('[data-testid="add-window"]').trigger("click");
    }
    expect(form.findAll('[data-testid="window-row"]')).toHaveLength(4);
    const add = form.find('[data-testid="add-window"]');
    expect(add.attributes("disabled")).toBeDefined();
  });

  it("accepts a midnight-wrap window and round-trips it unchanged", async () => {
    const form = mountForm();
    const values = await fillForm(form); // 22:00 -> 06:00 wrap by default
    await form.get('[data-testid="rule-form"]').trigger("submit");
    const [payload] = form.emitted("save")[0];
    expect(payload.active_hours).toEqual(values.active_hours);
    expect(payload.active_hours.windows[0]).toEqual({
      start: "22:00",
      end: "06:00",
    });
  });

  it("rejects a window whose start equals end", async () => {
    const form = mountForm();
    await fillForm(form);
    const row = form.find('[data-testid="window-row"]');
    await row.find('[data-testid="window-end"]').setValue("22:00");
    await form.get('[data-testid="rule-form"]').trigger("submit");
    expect(form.emitted("save")).toBeUndefined();
    expect(form.find('[data-testid="field-error-windows"]').exists()).toBe(
      true,
    );
  });

  it("rejects a roi_id that is not one of the camera's ROIs", async () => {
    const form = mountForm();
    await fillForm(form, { roi_id: 3 });
    await form.get('[data-testid="roi-select"]').setValue("999");
    await form.get('[data-testid="rule-form"]').trigger("submit");
    expect(form.emitted("save")).toBeUndefined();
    expect(form.find('[data-testid="field-error-roi"]').exists()).toBe(true);
  });

  it("emits the API.md request example on a valid submit", async () => {
    const form = mountForm();
    await fillForm(form);
    await form.get('[data-testid="rule-form"]').trigger("submit");
    expect(form.emitted("save")).toHaveLength(1);
    expect(form.emitted("save")[0][0]).toEqual({
      name: "Back door after hours",
      roi_id: 3,
      enabled: true,
      classes: ["person"],
      confidence_threshold: 0.55,
      cooldown_seconds: 60,
      active_hours: {
        timezone: "Asia/Kolkata",
        windows: [{ start: "22:00", end: "06:00" }],
      },
      severity: "critical",
      notify: true,
    });
  });

  it("defaults classes to person on an empty form (design §5.7)", () => {
    const form = mountForm();
    expect(
      form.find('[data-testid="class-option-person"]').element.checked,
    ).toBe(true);
  });

  it("prefills every field from an existing rule for editing", async () => {
    const existing = ruleOut({ roi_id: 9 });
    const form = mountForm(existing);
    await flushPromises();
    expect(form.get('[data-testid="rule-name"]').element.value).toBe(
      existing.name,
    );
    expect(
      form.find('[data-testid="class-option-person"]').element.checked,
    ).toBe(true);
    expect(form.get('[data-testid="roi-select"]').element.value).toBe("9");
  });

  it("windows editor adds and removes rows", async () => {
    const form = mountForm();
    expect(form.findAll('[data-testid="window-row"]')).toHaveLength(1);
    await form.get('[data-testid="add-window"]').trigger("click");
    expect(form.findAll('[data-testid="window-row"]')).toHaveLength(2);
    await form.findAll('[data-testid="remove-window"]').at(-1).trigger("click");
    expect(form.findAll('[data-testid="window-row"]')).toHaveLength(1);
  });
});

describe("RulesList", () => {
  const rules = [
    ruleOut(),
    ruleOut({ id: 8, name: "Quiet hours info", severity: "info" }),
  ];
  const rois = [roiOut()];

  const mountList = (user = ME_ADMIN) => {
    const pinia = authPinia(user);
    return mount(RulesList, {
      props: { cameraId: 1, rules, rois },
      global: {
        plugins: [pinia],
        stubs: { RouterLink: true },
      },
    });
  };

  it("lists each rule with a severity badge and summary", () => {
    const list = mountList();
    expect(list.text()).toContain("Back door after hours");
    expect(list.text()).toContain("Quiet hours info");
    expect(list.findAll('[data-testid="rule-severity"]')).toHaveLength(2);
    expect(list.findAll('[data-testid="rule-severity"]').at(0).text()).toBe(
      "critical",
    );
  });

  it("creates a rule via POST /cameras/1/rules with the form payload", async () => {
    const created = ruleOut({ id: 21, name: "New rule" });
    const list = mountList();
    global.fetch = vi.fn(async (url, init) => {
      expect(String(url)).toBe("/api/v1/cameras/1/rules");
      expect(init.method).toBe("POST");
      expect(JSON.parse(init.body)).toMatchObject({
        name: "New rule",
        classes: ["person"],
      });
      return jsonRes(201, created);
    });
    await list.get('[data-testid="new-rule"]').trigger("click");
    await fillForm(list.findComponent(RuleForm), { name: "New rule" });
    await list
      .findComponent(RuleForm)
      .get('[data-testid="rule-form"]')
      .trigger("submit");
    await flushPromises();
    expect(list.emitted("changed")).toHaveLength(1);
  });

  it("patches a rule via PATCH /rules/7", async () => {
    const list = mountList();
    global.fetch = vi.fn(async (url, init) => {
      expect(String(url)).toBe("/api/v1/rules/7");
      expect(init.method).toBe("PATCH");
      expect(JSON.parse(init.body)).toMatchObject({ name: "Renamed" });
      return jsonRes(200, ruleOut({ name: "Renamed" }));
    });
    await list.get('[data-testid="rule-edit-7"]').trigger("click");
    const form = list.findComponent(RuleForm);
    await form.get('[data-testid="rule-name"]').setValue("Renamed");
    await form.get('[data-testid="rule-form"]').trigger("submit");
    await flushPromises();
    expect(list.emitted("changed")).toHaveLength(1);
  });

  it("soft-delete warns the rule is kept for history, then DELETEs", async () => {
    const calls = [];
    const list = mountList();
    global.fetch = vi.fn(async (url, init) => {
      calls.push({ url: String(url), method: init?.method ?? "GET" });
      return jsonRes(200, rules);
    });
    await list.get('[data-testid="rule-delete-7"]').trigger("click");
    expect(list.text()).toMatch(/kept for history/i);
    await list.get('[data-testid="confirm-yes"]').trigger("click");
    await flushPromises();
    expect(calls).toContainEqual({
      url: "/api/v1/rules/7",
      method: "DELETE",
    });
    expect(list.emitted("changed")).toHaveLength(1);
  });

  it("hides every mutating control from a viewer", () => {
    const list = mountList(ME_VIEWER);
    expect(list.find('[data-testid="new-rule"]').exists()).toBe(false);
    expect(list.find('[data-testid="rule-edit-7"]').exists()).toBe(false);
    expect(list.find('[data-testid="rule-delete-7"]').exists()).toBe(false);
  });
});

describe("CameraCard", () => {
  const mountCard = (user = ME_ADMIN, cam = cameraOut()) => {
    const pinia = authPinia(user);
    return mount(CameraCard, {
      props: { camera: cam },
      global: { plugins: [pinia] },
    });
  };

  it("flips the enabled switch into PATCH {enabled}", async () => {
    global.fetch = vi.fn(async (url, init) => {
      expect(String(url)).toBe("/api/v1/cameras/1");
      expect(init.method).toBe("PATCH");
      expect(JSON.parse(init.body)).toEqual({ enabled: false });
      return jsonRes(200, cameraOut({ enabled: false }));
    });
    const card = mountCard();
    await card.get('[data-testid="card-enabled"]').setValue(false);
    await flushPromises();
  });

  it("saves name and sample_fps through PATCH", async () => {
    global.fetch = vi.fn(async (url, init) => {
      expect(String(url)).toBe("/api/v1/cameras/1");
      expect(init.method).toBe("PATCH");
      expect(JSON.parse(init.body)).toEqual({
        name: "Front door",
        sample_fps: 5,
      });
      return jsonRes(200, cameraOut({ name: "Front door", sample_fps: 5 }));
    });
    const card = mountCard();
    await card.get('[data-testid="card-name"]').setValue("Front door");
    await card.get('[data-testid="card-fps"]').setValue(5);
    await card.get('[data-testid="card-save"]').trigger("click");
    await flushPromises();
    expect(card.emitted("saved")).toHaveLength(1);
    expect(card.emitted("saved")[0][0].name).toBe("Front door");
  });

  it("deletes after confirm and emits deleted", async () => {
    global.fetch = vi.fn(async (url, init) => {
      expect(String(url)).toBe("/api/v1/cameras/1");
      expect(init.method).toBe("DELETE");
      return jsonRes(204, null);
    });
    const card = mountCard();
    await card.get('[data-testid="card-delete"]').trigger("click");
    expect(card.text()).toMatch(/delete this camera/i);
    await card.get('[data-testid="card-confirm"]').trigger("click");
    await flushPromises();
    expect(card.emitted("deleted")).toHaveLength(1);
  });

  it("shows no mutating controls to a viewer", () => {
    const card = mountCard(ME_VIEWER);
    expect(card.find('[data-testid="card-enabled"]').exists()).toBe(false);
    expect(card.find('[data-testid="card-save"]').exists()).toBe(false);
    expect(card.find('[data-testid="card-delete"]').exists()).toBe(false);
  });
});

describe("CameraDetail", () => {
  const api = (overrides = {}) => {
    const base = {
      "/api/v1/cameras/1": cameraOut(),
      "/api/v1/cameras/1/rois": [roiOut()],
      "/api/v1/cameras/1/rules": [ruleOut()],
      "/api/v1/auth/me": ME_ADMIN,
      ...overrides,
    };
    return async (url) => {
      const key = String(url);
      if (key in base) {
        const value = base[key];
        return value && typeof value === "object" && "ok" in value
          ? value
          : jsonRes(200, value);
      }
      return envelope(404, "NOT_FOUND", "No such camera");
    };
  };

  it("loads the camera, its ROIs and its rules on mount", async () => {
    const { wrapper } = await mountDetail(api());
    expect(wrapper.text()).toContain("Shop Front");
    expect(wrapper.text()).toContain("Back door after hours");
    expect(wrapper.findComponent(CameraCard).exists()).toBe(true);
    expect(wrapper.findComponent(RulesList).exists()).toBe(true);
  });

  it("navigates back to the grid after a delete", async () => {
    const { wrapper, router } = await mountDetail(api());
    const pushed = vi.spyOn(router, "push");
    await wrapper.findComponent(CameraCard).vm.$emit("deleted");
    expect(pushed).toHaveBeenCalledWith({ name: "cameras" });
  });

  it("surfaces a 404 as an inline message, not a crash", async () => {
    const { wrapper } = await mountDetail(
      api({
        "/api/v1/cameras/1": envelope(404, "NOT_FOUND", "No such camera"),
      }),
    );
    expect(wrapper.text()).toMatch(/no such camera/i);
  });
});

describe("CameraTile footer (friend's look)", () => {
  const cam = cameraOut({ id: 4, frame_width: 1280, frame_height: 720 });

  const mountTile = async (camera = cam) => {
    const router = makeRouter();
    const wrapper = mount(CameraTile, {
      props: { camera },
      global: { plugins: [createPinia(), router] },
    });
    await router.isReady();
    return { wrapper, router };
  };

  it("links to the camera detail with a resolution readout", async () => {
    const { wrapper } = await mountTile();
    const link = wrapper.get('[data-testid="tile-open"]');
    expect(link.text()).toMatch(/open/i);
    expect(link.attributes("href")).toBe("/cameras/4");
    expect(wrapper.get('[data-testid="tile-resolution"]').text()).toBe(
      "1280×720",
    );
  });

  it("falls back to —×— when the camera has no measured frame size", async () => {
    const { wrapper } = await mountTile(
      cameraOut({ frame_width: null, frame_height: null }),
    );
    expect(wrapper.get('[data-testid="tile-resolution"]').text()).toBe("—×—");
  });
});
