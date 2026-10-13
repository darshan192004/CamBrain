import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import RulesList from "../rules/RulesList.vue";
import RuleDiagnostics from "../rules/RuleDiagnostics.vue";
import { setTokens, clearTokens } from "../api/token.js";
import { useAuthStore } from "../stores/auth.js";
import { envelope, jsonRes } from "./api-mocks.js";

const ME_ADMIN = { user_id: 1, username: "ramesh", role: "admin", site_id: 1 };
const ME_VIEWER = { user_id: 2, username: "meera", role: "viewer", site_id: 1 };

const ruleOut = (init) => ({
  id: 7,
  camera_id: 1,
  roi_id: null,
  name: "Back door after hours",
  enabled: true,
  classes: ["person"],
  confidence_threshold: 0.55,
  cooldown_seconds: 60,
  active_hours: null,
  severity: "critical",
  notify: true,
  created_at: "2026-10-05T14:02:11Z",
  ...init,
});

const DIAG_OK = {
  rule_id: 7,
  fired: false,
  checks: [
    {
      condition: "class_in_allowlist",
      passed: true,
      detail: "'car' not in ['person']",
    },
    { condition: "confidence", passed: true, detail: "0.71 >= 0.55" },
    {
      condition: "in_roi",
      passed: false,
      detail: "centroid (0.41,0.62) outside Loading dock",
    },
  ],
};

/**
 * A pinia with an established session so RoleGate lets admins act.
 * @param {object} user /auth/me projection
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
 * Mount RuleDiagnostics against a stubbed fetch.
 * @param {(...args: unknown[]) => Promise<Response>} fetchImpl fetch double
 * @returns {object} the wrapper
 */
function mountDiag(fetchImpl) {
  global.fetch = vi.fn(fetchImpl);
  return mount(RuleDiagnostics, {
    props: { ruleId: 7, cameraId: 1 },
    global: { plugins: [authPinia()] },
  });
}

beforeEach(() => {
  setActivePinia(createPinia());
  clearTokens();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("RuleDiagnostics", () => {
  it("POSTs /rules/7/test with an empty body for the most recent event", async () => {
    const calls = [];
    const diag = mountDiag(async (url, init) => {
      calls.push({ url: String(url), method: init?.method, body: init?.body });
      if (String(url).endsWith("/test")) return jsonRes(200, DIAG_OK);
      return jsonRes(200, { items: [], total: 0, limit: 20, offset: 0 });
    });
    await flushPromises();
    await diag.get('[data-testid="run-test"]').trigger("click");
    await flushPromises();
    const testCall = calls.find((c) => c.url.endsWith("/test"));
    expect(testCall.method).toBe("POST");
    expect(JSON.parse(testCall.body)).toEqual({});
  });

  it("renders the fired banner and every check with icon+text and the detail verbatim", async () => {
    const diag = mountDiag(async (url) => {
      if (String(url).endsWith("/test")) return jsonRes(200, DIAG_OK);
      return jsonRes(200, { items: [], total: 0, limit: 20, offset: 0 });
    });
    await flushPromises();
    await diag.get('[data-testid="run-test"]').trigger("click");
    await flushPromises();
    const banner = diag.get('[data-testid="fired-banner"]');
    expect(banner.text()).toMatch(/did not fire/i);
    const rows = diag.findAll('[data-testid="check-row"]');
    expect(rows).toHaveLength(3);
    expect(rows[2].text()).toContain("in_roi");
    expect(rows[2].text()).toContain("fail");
    expect(rows[2].text()).toContain(
      "centroid (0.41,0.62) outside Loading dock",
    );
    expect(rows[0].text()).toContain("pass");
  });

  it("shows the empty-state copy on 404 (nothing to replay yet)", async () => {
    const diag = mountDiag(async (url) => {
      if (String(url).endsWith("/test")) {
        return envelope(404, "NOT_FOUND", "No events for this camera");
      }
      return jsonRes(200, { items: [], total: 0, limit: 20, offset: 0 });
    });
    await flushPromises();
    await diag.get('[data-testid="run-test"]').trigger("click");
    await flushPromises();
    expect(diag.get('[data-testid="empty-state"]').text()).toBe(
      "No detections recorded yet — run the camera and try again.",
    );
  });

  it("shows a 422 frame-size message as-is", async () => {
    const diag = mountDiag(async (url) => {
      if (String(url).endsWith("/test")) {
        return envelope(
          422,
          "VALIDATION_ERROR",
          "Camera has never produced a frame (need 1280x720)",
        );
      }
      return jsonRes(200, { items: [], total: 0, limit: 20, offset: 0 });
    });
    await flushPromises();
    await diag.get('[data-testid="run-test"]').trigger("click");
    await flushPromises();
    expect(diag.get('[data-testid="diag-error"]').text()).toContain(
      "never produced a frame",
    );
  });

  it("optionally replays a chosen event from GET /events?camera_id=", async () => {
    const calls = [];
    const events = {
      items: [
        { id: 812, started_at: "2026-10-05T14:02:11Z" },
        { id: 813, started_at: "2026-10-05T15:00:00Z" },
      ],
      total: 2,
      limit: 20,
      offset: 0,
    };
    const diag = mountDiag(async (url, init) => {
      calls.push({
        url: String(url),
        method: init?.method ?? "GET",
        body: init?.body,
      });
      if (String(url).includes("/events")) return jsonRes(200, events);
      if (String(url).endsWith("/test")) return jsonRes(200, DIAG_OK);
      return jsonRes(200, {});
    });
    await flushPromises();
    await diag.get('[data-testid="event-select"]').setValue("812");
    await diag.get('[data-testid="run-test"]').trigger("click");
    await flushPromises();
    const testCall = calls.find((c) => c.url.endsWith("/test"));
    expect(JSON.parse(testCall.body)).toEqual({ event_id: 812 });
  });
});

describe("RulesList diagnostics wiring", () => {
  it("opens the diagnostics panel from a per-rule Test button (admin)", async () => {
    const pinia = authPinia(ME_ADMIN);
    global.fetch = vi.fn(async (url) => {
      if (String(url).includes("/events")) {
        return jsonRes(200, { items: [], total: 0, limit: 20, offset: 0 });
      }
      if (String(url).endsWith("/test")) return jsonRes(200, DIAG_OK);
      return jsonRes(200, {});
    });
    const list = mount(RulesList, {
      props: { cameraId: 1, rules: [ruleOut()], rois: [] },
      global: { plugins: [pinia], stubs: { RouterLink: true } },
    });
    await list.get('[data-testid="rule-test-7"]').trigger("click");
    await flushPromises();
    expect(list.findComponent(RuleDiagnostics).exists()).toBe(true);
  });

  it("hides the Test button from viewers", () => {
    const pinia = authPinia(ME_VIEWER);
    const list = mount(RulesList, {
      props: { cameraId: 1, rules: [ruleOut()], rois: [] },
      global: { plugins: [pinia], stubs: { RouterLink: true } },
    });
    expect(list.find('[data-testid="rule-test-7"]').exists()).toBe(false);
  });
});
