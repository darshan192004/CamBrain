import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import { ApiError } from "../api/client.js";
import LoginForm from "../auth/LoginForm.vue";
import { clearTokens, getAccessToken } from "../api/token.js";
import { createAppRouter } from "../router.js";
import { useAuthStore } from "../stores/auth.js";
import { envelope, jsonRes } from "./api-mocks.js";

const ME = { user_id: 1, username: "ramesh", role: "admin", site_id: 1 };

const pair = { access_token: "at-1", refresh_token: "rt-1", expires_in: 43200 };

let router;

/**
 * Mount the login card against a fresh pinia and router.
 * @returns {object} {wrapper, auth} for assertions
 */
function mountLogin() {
  router = createAppRouter();
  const wrapper = mount(LoginForm, { global: { plugins: [router] } });
  return { wrapper, auth: useAuthStore() };
}

/**
 * Fill both fields and submit the form.
 * @param {object} wrapper mounted LoginForm
 * @returns {Promise<void>} settles after submit handlers run
 */
async function signIn(wrapper) {
  await wrapper.find('input[name="username"]').setValue("ramesh");
  await wrapper.find('input[name="password"]').setValue("hunter2");
  await wrapper.find("form").trigger("submit");
  await flushPromises();
}

beforeEach(() => {
  setActivePinia(createPinia());
  clearTokens();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("login success", () => {
  it("stores user and tokens and lands on /cameras", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url) => {
        if (url.endsWith("/auth/login")) {
          return jsonRes(200, pair);
        }
        if (url.endsWith("/auth/me")) {
          return jsonRes(200, ME);
        }
        throw new Error(`unexpected ${url}`);
      }),
    );

    const { wrapper, auth } = mountLogin();
    await signIn(wrapper);

    expect(getAccessToken()).toBe("at-1");
    expect(auth.user).toEqual(ME);
    // The post-login navigation loads an async screen; wait for it rather
    // than assuming one promise flush covers the module import.
    await vi.waitFor(() =>
      expect(router.currentRoute.value.name).toBe("cameras"),
    );
  });
});

describe("login failure copy (design §7: never which field)", () => {
  it.each([
    [401, "Check your username and password."],
    [423, "Too many failed attempts. Try again in 5 minutes."],
    [429, "Too many attempts. Please wait a moment and try again."],
  ])("status %s shows exactly the fixed message", async (status, copy) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        envelope(
          status,
          status === 423 ? "ACCOUNT_LOCKED" : "UNAUTHENTICATED",
          "raw detail",
        ),
      ),
    );

    const { wrapper } = mountLogin();
    await signIn(wrapper);

    const alert = wrapper.find('[data-testid="login-error"]');
    expect(alert.exists()).toBe(true);
    expect(alert.text()).toBe(copy);
    expect(getAccessToken()).toBeNull();
  });

  it("unknown failures show a generic message, not the envelope", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        envelope(
          500,
          "INTERNAL",
          "traceback: /srv/app/api/routers/auth.py line 44",
        ),
      ),
    );

    const { wrapper } = mountLogin();
    await signIn(wrapper);

    expect(wrapper.find('[data-testid="login-error"]').text()).toBe(
      "Something went wrong. Please try again.",
    );
    expect(wrapper.text()).not.toContain("auth.py");
  });
});

describe("client error typing", () => {
  it("ApiError keeps the status the guard copy switches on", () => {
    const err = new ApiError({ code: "X", message: "m", status: 423 });
    expect(err.status).toBe(423);
    expect(err).toBeInstanceOf(Error);
  });
});
