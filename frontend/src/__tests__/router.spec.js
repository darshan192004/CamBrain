import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import { clearTokens, setTokens } from "../api/token.js";
import { createAppRouter } from "../router.js";
import { envelope, jsonRes } from "./api-mocks.js";

const ME = { user_id: 1, username: "ramesh", role: "admin", site_id: 1 };

const pair = { access_token: "at", refresh_token: "rt", expires_in: 43200 };

/**
 * fetch double: /auth/me and /auth/refresh answer from a mutable identity,
 * everything else 200s.
 * @param {object} identity current /auth/me payload
 * @returns {object} fetch mock
 */
const authFetch = (identity) =>
  vi.fn(async (url) => {
    if (url.endsWith("/auth/me")) {
      return jsonRes(200, identity);
    }
    if (url.endsWith("/auth/refresh")) {
      return jsonRes(200, pair);
    }
    return jsonRes(200, { ok: true });
  });

let router;

beforeEach(() => {
  setActivePinia(createPinia());
  clearTokens();
  router = createAppRouter();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("route table", () => {
  it("registers every design §3 path", () => {
    const paths = new Set(
      Object.values(router.getRoutes()).map((route) => route.path),
    );
    for (const path of [
      "/login",
      "/",
      "/cameras",
      "/cameras/:id",
      "/events",
      "/events/:id",
      "/settings/users",
      "/settings/system",
    ]) {
      expect(paths, `missing ${path}`).toContain(path);
    }
  });
});

describe("guards", () => {
  it("unauthenticated navigation lands on /login without a network call", async () => {
    const fetchMock = vi.fn(async () => {
      throw new Error("no request expected");
    });
    vi.stubGlobal("fetch", fetchMock);

    await router.push("/cameras");
    expect(router.currentRoute.value.path).toBe("/login");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("authenticated visitor to /login is sent to /cameras", async () => {
    setTokens(pair);
    vi.stubGlobal("fetch", authFetch(ME));

    await router.push("/login");
    expect(router.currentRoute.value.name).toBe("cameras");
  });

  it("viewer is redirected away from /settings/users", async () => {
    setTokens(pair);
    vi.stubGlobal("fetch", authFetch({ ...ME, role: "viewer" }));

    await router.push("/settings/users");
    expect(router.currentRoute.value.name).toBe("cameras");
  });

  it("admin passes the settings/users guard", async () => {
    setTokens(pair);
    vi.stubGlobal("fetch", authFetch(ME));

    await router.push("/settings/users");
    expect(router.currentRoute.value.name).toBe("users");
  });

  it("hydration failure clears the session and lands on /login", async () => {
    setTokens(pair);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url) => {
        if (url.endsWith("/auth/refresh")) {
          return envelope(401, "UNAUTHENTICATED", "refresh token revoked");
        }
        return envelope(401, "UNAUTHENTICATED", "invalid token");
      }),
    );

    await router.push("/events");
    expect(router.currentRoute.value.path).toBe("/login");
  });
});
