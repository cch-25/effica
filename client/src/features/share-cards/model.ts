type ShareCardStatus = "queued" | "rendering" | "ready" | "failed" | "revoked";

const transitions: Record<ShareCardStatus, ShareCardStatus[]> = {
  queued: ["rendering", "failed", "revoked"],
  rendering: ["ready", "failed", "revoked"],
  ready: ["revoked"],
  failed: ["queued", "revoked"],
  revoked: [],
};

export function canTransitionShareCard(from: ShareCardStatus, to: ShareCardStatus): boolean {
  return transitions[from].includes(to);
}
