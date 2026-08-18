import type { ApiErrorBody } from "./types";
import { isMockMode } from "./mode";

const API_PREFIX = "/api/v1";
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

function browserCookie(name: string): string | undefined {
  if (typeof document === "undefined") return undefined;
  const prefix = `${encodeURIComponent(name)}=`;
  const entry = document.cookie.split("; ").find((item) => item.startsWith(prefix));
  return entry ? decodeURIComponent(entry.slice(prefix.length)) : undefined;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: ApiErrorBody,
    public readonly retryAfter: string | null,
  ) {
    super(body.error.message);
  }
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  if (typeof window !== "undefined" && isMockMode()) {
    const { startMockWorker } = await import("@/mocks/browser");
    await startMockWorker();
  }
  const headers = new Headers(init?.headers);
  headers.set("Content-Type", "application/json");
  const method = (init?.method ?? "GET").toUpperCase();
  const csrf = browserCookie("csrf");
  if (!SAFE_METHODS.has(method) && csrf && !headers.has("X-CSRF-Token")) {
    headers.set("X-CSRF-Token", csrf);
  }

  const response = await fetch(`${API_PREFIX}${path}`, {
    ...init,
    credentials: "include",
    headers,
  });

  if (!response.ok) {
    const fallback: ApiErrorBody = {
      error: { code: "UNKNOWN", message: "요청을 처리하지 못했습니다.", request_id: "unknown", retryable: false, details: {} },
    };
    const candidate = await response.json().catch(() => fallback) as Partial<ApiErrorBody>;
    const body = candidate.error?.message ? candidate as ApiErrorBody : fallback;
    if (typeof window !== "undefined") {
      const returnTo = `${window.location.pathname}${window.location.search}`;
      if (response.status === 401) window.dispatchEvent(new CustomEvent("api-auth-redirect", { detail: `/login?returnTo=${encodeURIComponent(returnTo)}` }));
      if (response.status === 403 && body.error.code === "CONSENT_REQUIRED") window.dispatchEvent(new CustomEvent("api-auth-redirect", { detail: `/onboarding/consent?returnTo=${encodeURIComponent(returnTo)}` }));
    }
    throw new ApiError(response.status, body, response.headers.get("Retry-After"));
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function createIdempotencyKey(): string {
  return crypto.randomUUID();
}
