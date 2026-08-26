import type { Article } from "@/lib/api/types";

export type SelectionResult = {
  selected: string[];
  correctionNeeded: boolean;
  error: "TOO_MANY" | null;
};

export function defaultComparisonSelection(articles: Article[]): string[] {
  const selected: string[] = [];
  const sources = new Set<string>();
  for (const article of articles) {
    if (sources.has(article.sourceId)) continue;
    selected.push(article.id);
    sources.add(article.sourceId);
    if (selected.length === 3) return selected;
  }
  for (const article of articles) {
    if (!selected.includes(article.id)) selected.push(article.id);
    if (selected.length === 3) break;
  }
  return selected;
}

export function parseComparisonSelection(
  raw: string | undefined,
  articles: Article[],
): SelectionResult {
  const fallback = defaultComparisonSelection(articles);
  if (!raw) return { selected: fallback, correctionNeeded: true, error: null };
  const requested = raw.split(",").map((value) => value.trim()).filter(Boolean);
  if (requested.length > 4) {
    return { selected: [], correctionNeeded: false, error: "TOO_MANY" };
  }
  const allowed = new Set(articles.map((article) => article.id));
  const valid =
    requested.length >= 2 &&
    requested.length <= 4 &&
    new Set(requested).size === requested.length &&
    requested.every((articleId) => allowed.has(articleId));
  return valid
    ? { selected: requested, correctionNeeded: false, error: null }
    : { selected: fallback, correctionNeeded: true, error: null };
}
