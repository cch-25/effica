export function safeReturnTo(candidate: string | null | undefined): string {
  return candidate?.startsWith("/") && !candidate.startsWith("//") ? candidate : "/";
}

export function withReturnTo(path: string, returnTo: string): string {
  if (!returnTo || returnTo === "/") return path;
  return `${path}?returnTo=${encodeURIComponent(returnTo)}`;
}
