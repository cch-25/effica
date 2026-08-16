import type { ApiErrorBody } from "./types";

const API_PREFIX = "/api/v1";

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
  if (typeof window !== "undefined" && process.env.NEXT_PUBLIC_API_MODE !== "real") {
    const { startMockWorker } = await import("@/mocks/browser");
    await startMockWorker();
  }
  const response = await fetch(`${API_PREFIX}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    const fallback: ApiErrorBody = {
      error: { code: "UNKNOWN", message: "요청을 처리하지 못했습니다.", request_id: "unknown", retryable: false, details: {} },
    };
    const body = await response.json().catch(() => fallback) as ApiErrorBody;
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
