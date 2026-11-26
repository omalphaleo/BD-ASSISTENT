/**
 * Unit tests for the CSRF token handling (task B12).
 *
 * Needed so the rule the backend enforces (A8: every state-changing call except login carries
 * `X-CSRF-Token`; one refresh and one retry on a CSRF failure; never a loop) cannot regress
 * unnoticed. The real fetch is replaced by a recording fake, so no request is ever sent, and
 * every token and URL below is synthetic.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearCsrfToken,
  createCsrfFetch,
  CSRF_FAILED_DETAIL,
  CSRF_HEADER_NAME,
  getCsrfToken,
  setCsrfToken,
} from "@/lib/csrf";

const BASE = "http://api.example.test";

/** The two 403 bodies the backend can send: the CSRF failure and the permission failure. */
const csrfFailure = () => Response.json({ detail: CSRF_FAILED_DETAIL }, { status: 403 });
const permissionFailure = () => Response.json({ detail: "Not permitted" }, { status: 403 });
const ok = () => Response.json({ ok: true }, { status: 200 });

/** Builds a fake fetch that records every request it receives and answers from `answers`. */
function fakeFetch(...answers: Array<() => Response>) {
  const received: Request[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL) => {
    received.push(input as Request);
    const next = answers[Math.min(received.length - 1, answers.length - 1)];
    return next();
  });
  return { fn: fn as unknown as typeof fetch, received };
}

beforeEach(() => {
  clearCsrfToken();
});

describe("token store", () => {
  it("starts empty, remembers a token and forgets it again", () => {
    expect(getCsrfToken()).toBeNull();

    setCsrfToken("abc");
    expect(getCsrfToken()).toBe("abc");

    clearCsrfToken();
    expect(getCsrfToken()).toBeNull();
  });

  it("keeps the token in memory only: not in localStorage, sessionStorage or cookies", () => {
    setCsrfToken("secret-token-value");

    expect(JSON.stringify({ ...window.localStorage })).not.toContain("secret-token-value");
    expect(JSON.stringify({ ...window.sessionStorage })).not.toContain("secret-token-value");
    expect(document.cookie).not.toContain("secret-token-value");
  });
});

describe("header on state-changing calls", () => {
  it.each(["POST", "PUT", "PATCH", "DELETE"])("%s: sends X-CSRF-Token", async (method) => {
    setCsrfToken("tok-1");
    const { fn, received } = fakeFetch(ok);
    const csrfFetch = createCsrfFetch(fn, async () => null);

    await csrfFetch(new Request(`${BASE}/users`, { method, body: method === "DELETE" ? null : "{}" }));

    expect(received).toHaveLength(1);
    expect(received[0].headers.get(CSRF_HEADER_NAME)).toBe("tok-1");
  });

  it.each(["GET", "HEAD"])("%s: sends no token", async (method) => {
    setCsrfToken("tok-1");
    const { fn, received } = fakeFetch(ok);
    const csrfFetch = createCsrfFetch(fn, async () => null);

    await csrfFetch(new Request(`${BASE}/users`, { method }));

    expect(received[0].headers.has(CSRF_HEADER_NAME)).toBe(false);
  });

  it("login: sends no token even when one is known (nobody is signed in yet)", async () => {
    setCsrfToken("tok-1");
    const { fn, received } = fakeFetch(ok);
    const csrfFetch = createCsrfFetch(fn, async () => null);

    await csrfFetch(new Request(`${BASE}/auth/login`, { method: "POST", body: "{}" }));

    expect(received[0].headers.has(CSRF_HEADER_NAME)).toBe(false);
  });

  it("logout: sends the token (it is state-changing)", async () => {
    setCsrfToken("tok-1");
    const { fn, received } = fakeFetch(ok);
    const csrfFetch = createCsrfFetch(fn, async () => null);

    await csrfFetch(new Request(`${BASE}/auth/logout`, { method: "POST" }));

    expect(received[0].headers.get(CSRF_HEADER_NAME)).toBe("tok-1");
  });

  it("keeps the other headers and the body intact", async () => {
    setCsrfToken("tok-1");
    const { fn, received } = fakeFetch(ok);
    const csrfFetch = createCsrfFetch(fn, async () => null);

    await csrfFetch(
      new Request(`${BASE}/users`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: "a@example.test" }),
      }),
    );

    expect(received[0].headers.get("Content-Type")).toBe("application/json");
    expect(await received[0].json()).toEqual({ email: "a@example.test" });
  });

  it("no token known yet: sends the request without the header (the server will refuse it)", async () => {
    const { fn, received } = fakeFetch(ok);
    const csrfFetch = createCsrfFetch(fn, async () => null);

    await csrfFetch(new Request(`${BASE}/users`, { method: "POST", body: "{}" }));

    expect(received[0].headers.has(CSRF_HEADER_NAME)).toBe(false);
  });
});

describe("CSRF failure: refresh once and retry once", () => {
  it("refreshes the token, then repeats the call with the new token and the same body", async () => {
    setCsrfToken("stale");
    const refresh = vi.fn(async () => "fresh");
    const { fn, received } = fakeFetch(csrfFailure, ok);
    const csrfFetch = createCsrfFetch(fn, refresh);

    const response = await csrfFetch(
      new Request(`${BASE}/users`, { method: "POST", body: JSON.stringify({ n: 1 }) }),
    );

    expect(response.status).toBe(200);
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(received).toHaveLength(2);
    expect(received[0].headers.get(CSRF_HEADER_NAME)).toBe("stale");
    expect(received[1].headers.get(CSRF_HEADER_NAME)).toBe("fresh");
    expect(await received[1].json()).toEqual({ n: 1 });
    expect(getCsrfToken()).toBe("fresh");
  });

  it("never loops: a second CSRF failure is returned after exactly one refresh and one retry", async () => {
    setCsrfToken("stale");
    const refresh = vi.fn(async () => "fresh");
    const { fn, received } = fakeFetch(csrfFailure);
    const csrfFetch = createCsrfFetch(fn, refresh);

    const response = await csrfFetch(new Request(`${BASE}/users`, { method: "POST", body: "{}" }));

    expect(response.status).toBe(403);
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(received).toHaveLength(2);
  });

  it("the permission 403 is not a CSRF failure: no refresh, no retry, body still readable", async () => {
    setCsrfToken("tok-1");
    const refresh = vi.fn(async () => "fresh");
    const { fn, received } = fakeFetch(permissionFailure);
    const csrfFetch = createCsrfFetch(fn, refresh);

    const response = await csrfFetch(new Request(`${BASE}/users`, { method: "POST", body: "{}" }));

    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ detail: "Not permitted" });
    expect(refresh).not.toHaveBeenCalled();
    expect(received).toHaveLength(1);
  });

  it("a 403 that is not JSON is left alone", async () => {
    setCsrfToken("tok-1");
    const refresh = vi.fn(async () => "fresh");
    const { fn, received } = fakeFetch(() => new Response("Forbidden", { status: 403 }));
    const csrfFetch = createCsrfFetch(fn, refresh);

    const response = await csrfFetch(new Request(`${BASE}/users`, { method: "POST", body: "{}" }));

    expect(response.status).toBe(403);
    expect(refresh).not.toHaveBeenCalled();
    expect(received).toHaveLength(1);
  });

  it("cannot refresh (session gone or backend down): returns the original 403 without a retry", async () => {
    setCsrfToken("stale");
    const refresh = vi.fn(async () => null);
    const { fn, received } = fakeFetch(csrfFailure);
    const csrfFetch = createCsrfFetch(fn, refresh);

    const response = await csrfFetch(new Request(`${BASE}/users`, { method: "POST", body: "{}" }));

    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ detail: CSRF_FAILED_DETAIL });
    expect(received).toHaveLength(1);
    expect(getCsrfToken()).toBe("stale");
  });

  it("other statuses (401, 500) are returned as they are", async () => {
    setCsrfToken("tok-1");
    const refresh = vi.fn(async () => "fresh");
    const { fn, received } = fakeFetch(() => new Response(null, { status: 401 }));
    const csrfFetch = createCsrfFetch(fn, refresh);

    const response = await csrfFetch(new Request(`${BASE}/users`, { method: "DELETE" }));

    expect(response.status).toBe(401);
    expect(refresh).not.toHaveBeenCalled();
    expect(received).toHaveLength(1);
  });

  it("a GET that gets a 403 is never retried", async () => {
    setCsrfToken("tok-1");
    const refresh = vi.fn(async () => "fresh");
    const { fn, received } = fakeFetch(csrfFailure);
    const csrfFetch = createCsrfFetch(fn, refresh);

    const response = await csrfFetch(new Request(`${BASE}/users`, { method: "GET" }));

    expect(response.status).toBe(403);
    expect(refresh).not.toHaveBeenCalled();
    expect(received).toHaveLength(1);
  });
});
