import { apiRequest } from "@/lib/api/client";
import { mapArticlePage, mapIssuePage, type ArticlePageDto, type IssuePageDto } from "@/lib/api/mappers";
import type { Article, Issue } from "@/lib/api/types";

type CursorPage<T> = { items: T[]; next_cursor: string | null };

// Both public endpoints paginate. Following every cursor keeps the directory
// from silently losing articles after the first page of an issue.
export async function collectPages<T>(load: (cursor: string | null) => Promise<CursorPage<T>>) {
  const items: T[] = [];
  const seen = new Set<string>();
  let cursor: string | null = null;
  do {
    const page = await load(cursor);
    items.push(...page.items);
    cursor = page.next_cursor;
    if (cursor && seen.has(cursor)) throw new Error("기사 목록의 페이지 정보를 확인할 수 없습니다.");
    if (cursor) seen.add(cursor);
  } while (cursor);
  return items;
}

export async function loadDirectoryIssues(signal: AbortSignal): Promise<Issue[]> {
  return collectPages(async (cursor) => {
    const params = new URLSearchParams({ limit: "250" });
    if (cursor) params.set("cursor", cursor);
    return mapIssuePage(await apiRequest<IssuePageDto>(`/issues?${params}`, { signal }));
  });
}

export async function loadDirectoryArticles(signal: AbortSignal) {
  const articles: Article[] = await collectPages(async (cursor) => {
    const params = new URLSearchParams({ limit: "250" });
    if (cursor) params.set("cursor", cursor);
    return mapArticlePage(await apiRequest<ArticlePageDto>(`/articles?${params}`, { signal }));
  });
  return { articles, failedIssueIds: [] as string[] };
}

export function directoryEntries(articles: Article[], issues: Issue[]) {
  const memberships = new Map<string, Issue[]>();
  for (const issue of issues) {
    for (const id of new Set(issue.articleIds)) {
      const group = memberships.get(id) ?? [];
      group.push(issue);
      memberships.set(id, group);
    }
  }
  const time = (value: string) => new Date(value).getTime() || 0;
  return [...new Map(articles.map((article) => [article.id, article])).values()]
    .sort((a, b) => time(b.publishedAt) - time(a.publishedAt) || a.id.localeCompare(b.id))
    .map((article) => ({ article, issues: memberships.get(article.id) ?? [] }));
}
