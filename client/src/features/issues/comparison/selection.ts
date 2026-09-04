import type { Article } from "@/lib/api/types";

type SelectionResult = {
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
  return selected;
}

export function isComparisonReadyArticle(article: Article): boolean {
  return article.analysisStatus === "READY"
    && article.analysisProvider === "openai"
    && article.sensationalism !== null;
}

export function parseComparisonSelection(
  raw: string | undefined,
  articles: Article[],
): SelectionResult {
  const fallback = defaultComparisonSelection(articles);
  if (!raw) return { selected: fallback, correctionNeeded: true, error: null };
  const requested = raw.split(",").map((value) => value.trim()).filter(Boolean);
  if (requested.length > 4) {
    return { selected: fallback, correctionNeeded: true, error: "TOO_MANY" };
  }
  const articleById = new Map(articles.map((article) => [article.id, article]));
  const requestedSources = requested
    .map((articleId) => articleById.get(articleId)?.sourceId)
    .filter((sourceId): sourceId is string => sourceId !== undefined);
  const valid =
    requested.length >= 2 &&
    requested.length <= 4 &&
    new Set(requested).size === requested.length &&
    requested.every((articleId) => articleById.has(articleId)) &&
    new Set(requestedSources).size === requested.length;
  return valid
    ? { selected: requested, correctionNeeded: false, error: null }
    : { selected: fallback, correctionNeeded: true, error: null };
}
