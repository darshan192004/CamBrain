import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import NotifiersPanel from "../settings/NotifiersPanel.vue";
import SystemView from "../settings/SystemView.vue";
import { clearTokens, setTokens } from "../api/token.js";
import { useAuthStore } from "../stores/auth.js";
import { envelope, jsonRes } from "./api-mocks.js";

const pair = { access_token: "at", refresh_token: "rt", expires_in: 43200 };

/**
 * Documented NotifierOut row (API §settings); `config` may carry a
 * deliberately leaky field to prove the panel never renders it.
 * @param {object} [init] field overrides
 * @returns {object} NotifierOut fixture
 */
const notifierOut = (init = {}) => ({
  id: 0,
  kind: "telegram",
  enabled: true,
  config: { chat_id: "gate" },
  has_token: true,
  ...init,
});

const ROWS = [
  notifierOut({
    config: { chat_id: "gate", bot_token_enc: "SEALED-NEVER-RENDERED" },
  }),
  notifierOut({
    id: 1,
    enabled: false,
    has_token: false,
    config: { chat_id: "ops" },
  }),
];

/**
 * Fetch double for the notifiers CRUD + test, plus the two system
 * endpoints SystemView fetches when the panel is asserted in page context.
 * @param {object} [opts] per-route response overrides
 * @returns {{calls: object[], impl: (url: string, init?: object) => Promise<object>}} recorder + impl
 */
function notifiersFetch(opts = {}) {
  const calls = [];
  const impl = vi.fn(async (url, init = {}) => {
    const u = String(url);
    const method = init.method ?? "GET";
    calls.push({ url: u, method, body: init.body });
    if (u.endsWith("/notifiers/test")) {
      return (
        opts.test ?? jsonRes(200, { ok: true, response: { message_id: 7 } })
      );
    }
    if (u.endsWith("/notifiers") && method === "POST") {
      const body = JSON.parse(init.body);
      // The 201 carries the public shape: config without the token,
      // has_token as the only credential signal (A7.4).
      return (
        opts.create ??
        jsonRes(201, {
          id: 2,
          kind: "telegram",
          enabled: true,
          config: { chat_id: body.config.chat_id },
          has_token: true,
        })
      );
    }
    if (u.endsWith("/notifiers") && method === "GET") {
      return jsonRes(200, opts.list ?? ROWS);
    }
    if (u.includes("/notifiers/") && method === "PATCH") {
      const body = JSON.parse(init.body);
      return (
        opts.patch ??
        jsonRes(200, { ...ROWS[1], enabled: Boolean(body.enabled) })
      );
    }
    if (u.includes("/notifiers/") && method === "DELETE") {
      return jsonRes(204, null);
    }
    if (u.endsWith("/system/status")) {
      return jsonRes(200, {
        version: "0.1.0",
        hardware_tier: "cpu",
        hardware: {},
        model: {},
        cameras: [],
      });
    }
    if (u.endsWith("/system/health")) {
      return jsonRes(200, { status: "ok", version: "0.1.0", uptime_s: 1 });
    }
    return envelope(404, "NOT_FOUND", "not found");
  });
  return { calls, impl };
}

/**
 * Mount NotifiersPanel with the fetch double installed.
 * @param {object} impl fetch double
 * @returns {object} wrapper
 */
function mountPanel(impl) {
  vi.stubGlobal("fetch", impl);
  return mount(NotifiersPanel);
}

beforeEach(() => {
  setTokens(pair);
  setActivePinia(createPinia());
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  clearTokens();
});

describe("NotifiersPanel (API §settings, spec A7.4)", () => {
  it("lists notifiers with token state and never renders sealed material", async () => {
    const { impl } = notifiersFetch();
    const wrapper = mountPanel(impl);
    await flushPromises();

    expect(wrapper.find('[data-testid="notifiers-panel"]').exists()).toBe(true);
    const rows = wrapper.findAll('[data-testid^="notifier-row-"]');
    expect(rows).toHaveLength(2);
    expect(rows[0].text()).toContain("gate");
    expect(rows[0].text()).toContain("Token set");
    expect(rows[1].text()).toContain("No token");
    expect(rows[1].text()).toContain("disabled");
    // Defence in depth: even a leaked ciphertext field never renders.
    expect(wrapper.html()).not.toContain("SEALED-NEVER-RENDERED");
    expect(wrapper.html()).not.toContain("bot_token_enc");
    wrapper.unmount();
  });

  it("adds a telegram notifier: POST with chat_id and write-only token", async () => {
    const { impl, calls } = notifiersFetch();
    const wrapper = mountPanel(impl);
    await flushPromises();

    const save = wrapper.get('[data-testid="notifier-save"]');
    expect(save.attributes("disabled")).toBeDefined(); // nothing to save yet

    await wrapper.get('[data-testid="field-chat_id"]').setValue("gate");
    await wrapper
      .get('[data-testid="field-bot_token"]')
      .setValue("SECRET-GATE-TOKEN");
    expect(save.attributes("disabled")).toBeUndefined(); // now submittable
    // jsdom never derives a submit from clicking a submit button; the repo
    // drives the form event itself (add-camera.spec precedent).
    await wrapper.get('[data-testid="notifier-add"]').trigger("submit");
    await flushPromises();

    const post = calls.find(
      (c) => c.method === "POST" && c.url.endsWith("/notifiers"),
    );
    expect(post).toBeDefined();
    expect(JSON.parse(post.body)).toEqual({
      kind: "telegram",
      enabled: true,
      config: { chat_id: "gate", bot_token: "SECRET-GATE-TOKEN" },
    });
    expect(wrapper.findAll('[data-testid^="notifier-row-"]')).toHaveLength(3);
    // Neither the entered token nor any echo survives into rendered state.
    expect(wrapper.html()).not.toContain("SECRET-GATE-TOKEN");
    expect(wrapper.get('[data-testid="field-chat_id"]').element.value).toBe("");
    expect(wrapper.get('[data-testid="field-bot_token"]').element.value).toBe(
      "",
    );
    wrapper.unmount();
  });

  it("runs a test send and lands the result in the aria-live region", async () => {
    const { impl, calls } = notifiersFetch({
      test: jsonRes(200, { ok: true, response: { message_id: 7 } }),
    });
    const wrapper = mountPanel(impl);
    await flushPromises();

    await wrapper.get('[data-testid="notifier-test"]').trigger("click");
    await flushPromises();

    const test = calls.find((c) => c.url.endsWith("/notifiers/test"));
    expect(test).toBeDefined();
    expect(test.method).toBe("POST");
    const region = wrapper.get('[data-testid="notifier-test-result"]');
    expect(region.attributes("aria-live")).toBe("polite");
    expect(region.text()).toContain("message sent");
    wrapper.unmount();
  });

  it("surfaces a failed test send verbatim in the same region", async () => {
    const { impl } = notifiersFetch({
      test: jsonRes(200, { ok: false, error: "telegram unreachable" }),
    });
    const wrapper = mountPanel(impl);
    await flushPromises();

    await wrapper.get('[data-testid="notifier-test"]').trigger("click");
    await flushPromises();

    const region = wrapper.get('[data-testid="notifier-test-result"]');
    expect(region.text()).toContain("telegram unreachable");
    expect(region.classes()).toContain("text-alert-critical");
    wrapper.unmount();
  });

  it("toggling enabled PATCHes the notifier in place", async () => {
    const { impl, calls } = notifiersFetch();
    const wrapper = mountPanel(impl);
    await flushPromises();

    const toggle = wrapper.get('[data-testid="notifier-enabled-1"]');
    expect(toggle.element.checked).toBe(false);
    await toggle.setChecked(true);
    await flushPromises();

    const patch = calls.find((c) => c.method === "PATCH");
    expect(patch).toBeDefined();
    expect(patch.url).toBe("/api/v1/notifiers/1");
    expect(JSON.parse(patch.body)).toEqual({ enabled: true });
    expect(
      wrapper.get('[data-testid="notifier-enabled-1"]').element.checked,
    ).toBe(true);
    wrapper.unmount();
  });

  it("deletes a notifier and re-reads the list (ids are indexes)", async () => {
    const { impl, calls } = notifiersFetch();
    const wrapper = mountPanel(impl);
    await flushPromises();

    await wrapper.get('[data-testid="notifier-delete-1"]').trigger("click");
    await flushPromises();

    const del = calls.find((c) => c.method === "DELETE");
    expect(del).toBeDefined();
    expect(del.url).toBe("/api/v1/notifiers/1");
    const gets = calls.filter(
      (c) => c.method === "GET" && c.url.endsWith("/notifiers"),
    );
    expect(gets).toHaveLength(2); // initial load + reindex after delete
    wrapper.unmount();
  });

  it("the System page renders the panel only for an admin", async () => {
    const { impl } = notifiersFetch();
    vi.stubGlobal("fetch", impl);

    const viewerPinia = createPinia();
    setActivePinia(viewerPinia);
    const viewer = useAuthStore();
    viewer.user = { user_id: 2, username: "meera", role: "viewer", site_id: 1 };
    const asViewer = mount(SystemView, {
      global: { plugins: [viewerPinia] },
    });
    await flushPromises();
    expect(asViewer.find('[data-testid="notifiers-panel"]').exists()).toBe(
      false,
    );
    asViewer.unmount();

    const adminPinia = createPinia();
    setActivePinia(adminPinia);
    const admin = useAuthStore();
    admin.user = { user_id: 1, username: "ramesh", role: "admin", site_id: 1 };
    const asAdmin = mount(SystemView, {
      global: { plugins: [adminPinia] },
    });
    await flushPromises();
    expect(asAdmin.find('[data-testid="notifiers-panel"]').exists()).toBe(true);
    asAdmin.unmount();
  });
});
