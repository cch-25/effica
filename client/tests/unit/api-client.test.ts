import { afterEach, expect, it, vi } from "vitest";
import { ApiError, apiRequest } from "@/lib/api/client";

afterEach(() => {
  vi.unstubAllGlobals();
  delete process.env.NEXT_PUBLIC_API_MODE;
  document.cookie = "csrf=; Max-Age=0; path=/";
});

it("can return an optional GET 401 without dispatching a global auth redirect", async () => {
  process.env.NEXT_PUBLIC_API_MODE = "real";
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
    error: { code: "AUTH_REQUIRED", message: "login", request_id: "test", retryable: false, details: {} },
  }), { status: 401, headers: { "Content-Type": "application/json" } })));
  const redirect = vi.fn();
  window.addEventListener("api-auth-redirect", redirect);

  await expect(apiRequest("/articles/a1/vote", { authFailureMode: "return-error" })).rejects.toBeInstanceOf(ApiError);
  expect(redirect).not.toHaveBeenCalled();

  window.removeEventListener("api-auth-redirect", redirect);
});

it("keeps requests same-origin and mirrors the CSRF cookie on mutations", async () => {
  process.env.NEXT_PUBLIC_API_MODE = "real";
  document.cookie = "csrf=token%20value; path=/";
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  }));
  vi.stubGlobal("fetch", fetchMock);

  await apiRequest("/articles/a1/vote", { method: "PUT", body: "{}" });

  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  expect(url).toBe("/api/v1/articles/a1/vote");
  expect(init.credentials).toBe("include");
  expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("token value");
});
