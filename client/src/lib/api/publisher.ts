import type { Article } from "./types";

// Keep domain grouping consistent with the API editorial_policy.publisher_identity.
export function publisherIdentity(article: Article): string {
  try {
    const url = new URL(article.originalUrl);
    const host = url.hostname.toLowerCase().replace(/\.$/, "");
    const parts = host.split(".");
    if (["http:", "https:"].includes(url.protocol) && parts.length >= 2) {
      const countrySuffix = parts.at(-1)!.length === 2;
      const secondLevels = new Set(["co", "com", "org", "net", "ac", "go", "gov", "or", "ne"]);
      const count = parts.length >= 3 && countrySuffix && secondLevels.has(parts.at(-2)!) ? 3 : 2;
      return parts.slice(-count).join(".");
    }
  } catch {
    // Feed summaries do not include a canonical URL. Detail responses do.
  }
  return article.sourceId || article.source;
}
