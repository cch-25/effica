import { afterEach, expect, it, vi } from "vitest";
import { apiRequest } from "@/lib/api/client";

afterEach(() => {
  vi.unstubAllGlobals();
  delete process.env.NEXT_PUBLIC_API_MODE;
  document.cookie = "csrf=; Max-Age=0; path=/";
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
