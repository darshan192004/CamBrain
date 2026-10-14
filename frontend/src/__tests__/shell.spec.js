import { mount } from "@vue/test-utils";
import { readFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import App from "../App.vue";
import Sidebar from "../layout/Sidebar.vue";
import StatusBar from "../layout/StatusBar.vue";
import TopBar from "../layout/TopBar.vue";
import { clearTokens, setTokens } from "../api/token.js";
import { createAppRouter } from "../router.js";
import { useAuthStore } from "../stores/auth.js";
import { jsonRes } from "./api-mocks.js";

const ME = {
  user_id: 1,
  username: "ramesh",
  role: "admin",
  site_id: 1,
  site_name: "Dhanraj Complex",
};

const pair = { access_token: "at", refresh_token: "rt", expires_in: 43200 };

const STATUS = {
  cameras: [
    { id: 1, name: "Back door", status: "live", fps: 10.0 },
    { id: 2, name: "Front counter", status: "live", fps: 14.4 },
    { id: 3, name: "Gate", status: "offline", last_error: "auth failed" },
  ],
  stats: { cameras_total: 3 },
};

/**
 * fetch double: identity and status answer from fixtures, everything
 * else 200s.
 * @param {object} [identity] /auth/me payload
 * @returns {object} fetch mock
 */
const shellFetch = (identity = ME) =>
  vi.fn(async (url) => {
    if (url.endsWith("/auth/me")) {
      return jsonRes(200, identity);
    }
    if (url.endsWith("/system/status")) {
      return jsonRes(200, STATUS);
    }
    if (url.endsWith("/auth/refresh")) {
      return jsonRes(200, pair);
    }
    return jsonRes(200, { ok: true });
  });

/**
 * Mount the sidebar for a given role on a fresh pinia + router.
 * @param {string} role "admin" | "viewer"
 * @returns {object} mounted wrapper
 */
function mountSidebar(role) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const auth = useAuthStore();
  auth.user = { ...ME, role };
  return mount(Sidebar, { global: { plugins: [pinia, createAppRouter()] } });
}

beforeEach(() => {
  setActivePinia(createPinia());
  clearTokens();
});

afterEach(() => {
  delete window.matchMedia;
  vi.unstubAllGlobals();
  vi.useRealTimers();
  clearTokens();
});

describe("Sidebar", () => {
  it("renders all four destinations for an admin", () => {
    const wrapper = mountSidebar("admin");
    const hrefs = wrapper.findAll("a").map((a) => a.attributes("href"));
    expect(hrefs).toEqual([
      "/cameras",
      "/events",
      "/settings/users",
      "/settings/system",
    ]);
    wrapper.unmount();
  });

  it("omits Users and System for a viewer (defence in depth)", () => {
    const wrapper = mountSidebar("viewer");
    const hrefs = wrapper.findAll("a").map((a) => a.attributes("href"));
    expect(hrefs).toEqual(["/cameras", "/events"]);
    wrapper.unmount();
  });

  it("collapses below 1024px and expands without matchMedia", async () => {
    window.matchMedia = vi.fn((query) => ({
      matches: true,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
    const collapsed = mountSidebar("admin");
    await collapsed.vm.$nextTick();
    expect(collapsed.find('[data-testid="sidebar"]').classes()).toContain(
      "sidebar--collapsed",
    );
    collapsed.unmount();

    delete window.matchMedia;
    const expanded = mountSidebar("admin");
    await expanded.vm.$nextTick();
    expect(expanded.find('[data-testid="sidebar"]').classes()).not.toContain(
      "sidebar--collapsed",
    );
    expanded.unmount();
  });
});

describe("StatusBar", () => {
  it("polls /system/status, renders counts, clears its interval", async () => {
    vi.useFakeTimers();
    const fetchMock = shellFetch();
    vi.stubGlobal("fetch", fetchMock);

    const wrapper = mount(StatusBar);
    await vi.advanceTimersByTimeAsync(0);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).toContain("2 online");
    expect(wrapper.text()).toContain("1 offline");
    expect(wrapper.text()).toContain("12.2 FPS avg");

    await vi.advanceTimersByTimeAsync(10_000);
    expect(fetchMock).toHaveBeenCalledTimes(2);

    wrapper.unmount();
    await vi.advanceTimersByTimeAsync(30_000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe("TopBar", () => {
  it("shows the site name from the auth store", () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.user = { ...ME };

    const wrapper = mount(TopBar, { global: { plugins: [pinia] } });
    expect(wrapper.find('[data-testid="site-name"]').text()).toBe(
      "Dhanraj Complex",
    );
    wrapper.unmount();
  });
});

describe("AppShell", () => {
  it("wraps the routed screen with one persistent aria-live region", async () => {
    const router = createAppRouter();
    const pinia = createPinia();
    setActivePinia(pinia);
    setTokens(pair);
    vi.stubGlobal("fetch", shellFetch());

    const wrapper = mount(App, { global: { plugins: [pinia, router] } });

    await router.push("/cameras");
    await vi.waitFor(() =>
      expect(wrapper.find('[data-testid="sidebar"]').exists()).toBe(true),
    );
    expect(
      wrapper.find('[data-testid="live-region"]').attributes("aria-live"),
    ).toBe("polite");
    expect(wrapper.find('[data-testid="site-name"]').text()).toBe(
      "Dhanraj Complex",
    );
    expect(wrapper.find("h1").text()).toBe("Cameras");

    await router.push("/events");
    await vi.waitFor(() => expect(wrapper.find("h1").text()).toBe("Events"));
    expect(wrapper.findAll('[data-testid="live-region"]')).toHaveLength(1);
    wrapper.unmount();
  });

  it("renders the event ticker inside the live region (4.18)", async () => {
    const router = createAppRouter();
    const pinia = createPinia();
    setActivePinia(pinia);
    setTokens(pair);
    vi.stubGlobal("fetch", shellFetch());

    const wrapper = mount(App, { global: { plugins: [pinia, router] } });
    await router.push("/cameras");
    await vi.waitFor(() =>
      expect(
        wrapper
          .find('[data-testid="live-region"] [data-testid="event-ticker"]')
          .exists(),
      ).toBe(true),
    );
    wrapper.unmount();
  });
});

describe("acceptance", () => {
  it("reduced-motion media query disables transitions (style.css)", () => {
    const css = readFileSync("src/style.css", "utf8");
    expect(css).toContain("@media (prefers-reduced-motion: reduce)");
    expect(css).toContain("transition-duration: 0.01ms !important");
  });
});
