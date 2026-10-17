import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  get,
  post,
  raw,
  request,
  setOnAuthError,
} from "../api/client.js";
import { clearTokens, getAccessToken, setTokens } from "../api/token.js";
import { envelope, jsonRes } from "./api-mocks.js";

beforeEach(() => {
  clearTokens();
  setOnAuthError(() => {});
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("request headers", () => {
  it("sends the CSRF client header, bearer token, and JSON bodies", async () => {
    setTokens({ access_token: "access-1", refresh_token: "refresh-1" });
    const fetchMock = vi.fn(async () => jsonRes(200, { id: 1 }));
    vi.stubGlobal("fetch", fetchMock);

    await get("/cameras");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/cameras");
    expect(init.headers["X-CamBrain-Client"]).toBe("cambrain-dashboard");
    expect(init.headers.Authorization).toBe("Bearer access-1");
    expect(init.body).toBeUndefined();

    await post("/cameras", { name: "dock" });
    const [, postInit] = fetchMock.mock.calls[1];
    expect(postInit.headers["Content-Type"]).toBe("application/json");
    expect(postInit.body).toBe(JSON.stringify({ name: "dock" }));
  });

  it("omits Authorization when no token is held or auth is false", async () => {
    const fetchMock = vi.fn(async () => jsonRes(200, {}));
    vi.stubGlobal("fetch", fetchMock);

    await post(
      "/auth/login",
      { username: "a", password: "b" },
      { auth: false },
    );
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBeUndefined();
    expect(fetchMock.mock.calls[0][1].headers["X-CamBrain-Client"]).toBe(
      "cambrain-dashboard",
    );
  });
});

describe("error envelope", () => {
  it("decodes {error:{...}} into ApiError with every field", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        envelope(422, "VALIDATION", "name is required", { field: "name" }),
      ),
    );

    const err = await get("/cameras").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe("VALIDATION");
    expect(err.message).toBe("name is required");
    expect(err.field).toBe("name");
    expect(err.status).toBe(422);
    expect(err.correlationId).toBe("cid-1");
  });

  it("bad credentials reject without attempting a refresh", async () => {
    const onAuthError = vi.fn();
    setOnAuthError(onAuthError);
    const fetchMock = vi.fn(async () =>
      envelope(401, "UNAUTHENTICATED", "Check your username and password."),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      post(
        "/auth/login",
        { username: "a", password: "wrong" },
        { auth: false },
      ),
    ).rejects.toMatchObject({ status: 401, code: "UNAUTHENTICATED" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(onAuthError).not.toHaveBeenCalled();
  });
});

describe("401 refresh", () => {
  it("two parallel 401s share one refresh and both retry successfully", async () => {
    setTokens({ access_token: "old", refresh_token: "refresh-1" });
    const calls = [];
    const fetchMock = vi.fn(async (url, init) => {
      calls.push({ url, init });
      if (url.endsWith("/auth/refresh")) {
        return jsonRes(200, {
          access_token: "new",
          refresh_token: "refresh-2",
          token_type: "bearer",
          expires_in: 43200,
        });
      }
      if (init.headers.Authorization === "Bearer old") {
        return envelope(401, "UNAUTHENTICATED", "access token expired");
      }
      return jsonRes(200, { ok: true });
    });
    vi.stubGlobal("fetch", fetchMock);

    const [cameras, events] = await Promise.all([
      get("/cameras"),
      get("/events"),
    ]);
    expect(cameras).toEqual({ ok: true });
    expect(events).toEqual({ ok: true });
    expect(calls.filter((c) => c.url.endsWith("/auth/refresh"))).toHaveLength(
      1,
    );
    expect(
      calls.filter((c) => c.init.headers.Authorization === "Bearer new"),
    ).toHaveLength(2);
  });

  it("rejected refresh clears tokens and fires onAuthError exactly once", async () => {
    setTokens({ access_token: "old", refresh_token: "refresh-1" });
    const onAuthError = vi.fn();
    setOnAuthError(onAuthError);
    const fetchMock = vi.fn(async (url) => {
      if (url.endsWith("/auth/refresh")) {
        return envelope(401, "UNAUTHENTICATED", "refresh token revoked");
      }
      return envelope(401, "UNAUTHENTICATED", "access token expired");
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(get("/cameras")).rejects.toBeInstanceOf(ApiError);
    expect(onAuthError).toHaveBeenCalledTimes(1);
    expect(getAccessToken()).toBeNull();
  });
});

describe("raw()", () => {
  it("returns response bytes without JSON-parsing", async () => {
    setTokens({ access_token: "access-1", refresh_token: "refresh-1" });
    const bytes = new Uint8Array([0xff, 0xd8, 0xff, 0xd9]);
    let jsonCalled = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        status: 200,
        headers: new Headers(),
        json: async () => {
          jsonCalled = true;
          return {};
        },
        arrayBuffer: async () => bytes.buffer,
      })),
    );

    const buffer = await raw("/cameras/1/snapshot");
    expect(new Uint8Array(buffer)).toEqual(bytes);
    expect(jsonCalled).toBe(false);
    expect(buffer).toBeInstanceOf(ArrayBuffer);
  });
});

describe("request()", () => {
  it("returns null on 204 instead of parsing an empty body", async () => {
    setTokens({ access_token: "access-1", refresh_token: "refresh-1" });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        status: 204,
        headers: new Headers(),
        json: async () => {
          throw new Error("204 has no body");
        },
        arrayBuffer: async () => new ArrayBuffer(0),
      })),
    );

    await expect(request("/cameras/1")).resolves.toBeNull();
  });
});
