export type ApiMode = "mock" | "real";

export function apiMode(): ApiMode {
  return process.env.NEXT_PUBLIC_API_MODE === "mock" ? "mock" : "real";
}

export function isMockMode(): boolean {
  return apiMode() === "mock";
}
