import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import UsersView from "../settings/UsersView.vue";
import Sidebar from "../layout/Sidebar.vue";
import { clearTokens, setTokens } from "../api/token.js";
import { useAuthStore } from "../stores/auth.js";
import { createAppRouter } from "../router.js";
import { envelope, jsonRes } from "./api-mocks.js";

const pair = { access_token: "at", refresh_token: "rt", expires_in: 43200 };

/**
 * One UserOut row (API.md §Users) with per-row overrides.
 * @param {object} [init] field overrides
 * @returns {object} UserOut fixture
 */
const userOut = (init = {}) => ({
  id: 1,
  username: "ramesh",
  role: "admin",
  is_active: true,
  created_at: "2026-10-01T10:00:00Z",
  last_login_at: "2026-10-14T08:00:00Z",
  ...init,
});

const ROWS = [
  userOut(),
  userOut({ id: 2, username: "meera", role: "viewer", last_login_at: null }),
];

/**
 * Collecting fetch double for /users: list on GET, 201 on POST, 204 on
 * DELETE unless opts.del answers otherwise.
 * @param {object} [opts] per-route response overrides
 * @returns {{calls: object[], impl: (url: string, init?: object) => Promise<object>}} recorder + impl
 */
function usersFetch(opts = {}) {
  const calls = [];
  const impl = vi.fn(async (url, init = {}) => {
    const u = String(url);
    const method = init.method ?? "GET";
    calls.push({ url: u, method, body: init.body });
    if (u.endsWith("/users") && method === "POST") {
      return (
        opts.create ??
        jsonRes(
          201,
          userOut({ id: 3, username: JSON.parse(init.body).username }),
        )
      );
    }
    if (u.endsWith("/users")) {
      return jsonRes(200, opts.list ?? ROWS);
    }
    if (method === "DELETE" && /\/users\/\d+$/.test(u)) {
      return opts.del ?? jsonRes(204, null);
    }
    return envelope(404, "NOT_FOUND", "not found");
  });
  return { calls, impl };
}

/**
 * Mount UsersView with the given fetch impl installed.
 * @param {object} impl fetch double
 * @returns {object} wrapper
 */
function mountUsers(impl) {
  vi.stubGlobal("fetch", impl);
  return mount(UsersView);
}

beforeEach(() => {
  setTokens(pair);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  clearTokens();
});

describe("UsersView", () => {
  it("lists users from GET /users", async () => {
    const { impl, calls } = usersFetch();
    const wrapper = mountUsers(impl);
    await flushPromises();

    expect(wrapper.find('[data-testid="users-view"]').exists()).toBe(true);
    const rows = wrapper.findAll('[data-testid^="user-row-"]');
    expect(rows).toHaveLength(2);
    expect(rows[0].text()).toContain("ramesh");
    expect(rows[0].text()).toContain("admin");
    expect(rows[1].text()).toContain("meera");
    expect(rows[1].text()).toContain("viewer");
    expect(calls[0].url).toBe("/api/v1/users");
    wrapper.unmount();
  });

  it("create posts the documented payload and appends the row", async () => {
    const created = userOut({ id: 3, username: "suresh", role: "viewer" });
    const { impl, calls } = usersFetch({ create: jsonRes(201, created) });
    const wrapper = mountUsers(impl);
    await flushPromises();

    await wrapper.get('[data-testid="user-username"]').setValue("suresh");
    await wrapper.get('[data-testid="user-password"]').setValue("hunter2pass");
    await wrapper.get('[data-testid="user-role"]').setValue("viewer");
    await wrapper.get('[data-testid="create-user"]').trigger("click");
    await flushPromises();

    const post = calls.find((c) => c.method === "POST");
    expect(post.url).toBe("/api/v1/users");
    expect(JSON.parse(post.body)).toEqual({
      username: "suresh",
      password: "hunter2pass",
      role: "viewer",
    });
    const rows = wrapper.findAll('[data-testid^="user-row-"]');
    expect(rows).toHaveLength(3);
    expect(rows[2].text()).toContain("suresh");
    wrapper.unmount();
  });

  it("role select offers admin and viewer only", async () => {
    const { impl } = usersFetch();
    const wrapper = mountUsers(impl);
    await flushPromises();

    const options = wrapper
      .findAll('[data-testid="user-role"] option')
      .map((o) => o.attributes("value"));
    expect(options).toEqual(["admin", "viewer"]);
    wrapper.unmount();
  });

  it("delete asks for confirmation, then DELETEs and drops the row", async () => {
    const { impl, calls } = usersFetch({ del: jsonRes(204, null) });
    const wrapper = mountUsers(impl);
    await flushPromises();

    await wrapper.get('[data-testid="delete-user-2"]').trigger("click");
    await wrapper.vm.$nextTick();
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    expect(wrapper.find('[data-testid="confirm-delete-user-2"]').exists()).toBe(
      true,
    );

    await wrapper.get('[data-testid="confirm-delete-user-2"]').trigger("click");
    await flushPromises();

    const del = calls.find((c) => c.method === "DELETE");
    expect(del.url).toBe("/api/v1/users/2");
    expect(wrapper.findAll('[data-testid^="user-row-"]')).toHaveLength(1);
    wrapper.unmount();
  });

  it("409 last-admin shows an inline conflict message and keeps the row", async () => {
    const { impl } = usersFetch({
      del: envelope(
        409,
        "CONFLICT",
        "cannot demote or delete the last remaining admin",
      ),
      list: [userOut()],
    });
    const wrapper = mountUsers(impl);
    await flushPromises();

    await wrapper.get('[data-testid="delete-user-1"]').trigger("click");
    await wrapper.vm.$nextTick();
    await wrapper.get('[data-testid="confirm-delete-user-1"]').trigger("click");
    await flushPromises();

    const err = wrapper.get('[data-testid="users-error"]');
    expect(err.text()).toContain(
      "cannot demote or delete the last remaining admin",
    );
    expect(wrapper.findAll('[data-testid^="user-row-"]')).toHaveLength(1);
    wrapper.unmount();
  });

  it("the sidebar hides the Settings destinations from a viewer", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.user = { user_id: 2, username: "meera", role: "viewer", site_id: 1 };
    auth.hydrated = true;

    const wrapper = mount(Sidebar, {
      global: { plugins: [pinia, createAppRouter()] },
    });
    const hrefs = wrapper.findAll("a").map((a) => a.attributes("href"));
    expect(hrefs).toEqual(["/cameras", "/events"]);
    wrapper.unmount();
  });
});
