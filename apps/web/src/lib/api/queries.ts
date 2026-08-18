"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "./client";
import {
  mapArticle,
  mapArticlePage,
  mapFeedPage,
  mapIssue,
  mapIssuePage,
  mapVisualizationPointPage,
  type ArticleDto,
  type ArticlePageDto,
  type FeedPageDto,
  type IssueDetailDto,
  type IssuePageDto,
  type ScoreDto,
  type VisualizationPointPageDto,
} from "./mappers";

function flattenPages<T>(pages: Array<{ items: T[]; next_cursor: string | null }> | undefined) {
  if (!pages) return undefined;
  return {
    items: pages.flatMap((page) => page.items),
    next_cursor: pages.at(-1)?.next_cursor ?? null,
  };
}

async function loadAllVisualizationPages(
  type: "article" | "user" | "source",
): Promise<VisualizationPointPageDto["items"]> {
  const items: VisualizationPointPageDto["items"] = [];
  const seenCursors = new Set<string>();
  let cursor: string | null = null;
  do {
    const params = new URLSearchParams({ type });
    if (cursor) params.set("cursor", cursor);
    const page = await apiRequest<VisualizationPointPageDto>(`/visualization/points?${params}`);
    items.push(...page.items);
    if (!page.next_cursor) break;
    if (seenCursors.has(page.next_cursor)) throw new Error("Visualization cursor cycle detected");
    seenCursors.add(page.next_cursor);
    cursor = page.next_cursor;
  } while (cursor);
  return items;
}

export function useFeedQuery() {
  const query = useInfiniteQuery({
    queryKey: ["feed", "personalized"],
    queryFn: async ({ pageParam }) => {
      const params = new URLSearchParams({ mode: "personalized" });
      if (pageParam) params.set("cursor", pageParam);
      return mapFeedPage(await apiRequest<FeedPageDto>(`/feed?${params}`));
    },
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
  });
  return { ...query, data: flattenPages(query.data?.pages) };
}

export function useIssuesQuery() {
  const query = useInfiniteQuery({
    queryKey: ["issues"],
    queryFn: async ({ pageParam }) => {
      const suffix = pageParam ? `?cursor=${encodeURIComponent(pageParam)}` : "";
      return mapIssuePage(await apiRequest<IssuePageDto>(`/issues${suffix}`));
    },
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
  });
  return { ...query, data: flattenPages(query.data?.pages) };
}

export function useIssueQuery(issueId: string) {
  return useQuery({
    queryKey: ["issue", issueId],
    queryFn: async () => mapIssue(await apiRequest<IssueDetailDto>(`/issues/${encodeURIComponent(issueId)}`)),
  });
}

export function useIssueArticlesQuery(issueId: string) {
  return useQuery({
    queryKey: ["issue", issueId, "articles"],
    queryFn: async () => mapArticlePage(await apiRequest<ArticlePageDto>(`/issues/${encodeURIComponent(issueId)}/articles`)),
  });
}

export function useArticleQuery(articleId: string) {
  return useQuery({
    queryKey: ["article", articleId],
    queryFn: async () => {
      const id = encodeURIComponent(articleId);
      const [article, score] = await Promise.all([
        apiRequest<ArticleDto>(`/articles/${id}`),
        apiRequest<ScoreDto>(`/articles/${id}/score`),
      ]);
      return mapArticle(article, score);
    },
  });
}

export function useArticleAnalysisQuery(articleId: string) {
  return useQuery({
    queryKey: ["article", articleId, "analysis"],
    queryFn: async () => {
      const id = encodeURIComponent(articleId);
      const [assessments, history] = await Promise.all([
        apiRequest<{ article_version_id: string; assessments: Array<Record<string, unknown>> }>(`/articles/${id}/assessments`),
        apiRequest<{ items: Array<Record<string, unknown>>; next_cursor?: string | null }>(`/articles/${id}/score-history`),
      ]);
      return { assessments, history };
    },
  });
}

export function useVisualizationPointsQuery() {
  return useQuery({
    queryKey: ["visualization", "points"],
    queryFn: async () => {
      const types = ["article", "user", "source"] as const;
      const pages = await Promise.all(types.map(loadAllVisualizationPages));
      return mapVisualizationPointPage({
        items: pages.flat(),
        next_cursor: null,
      });
    },
  });
}

export function useVoteMutation(articleId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: { x: number; y: number; z: number; sensationalism: number }) => apiRequest(`/articles/${articleId}/vote`, { method: "PUT", body: JSON.stringify(payload) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["article", articleId, "votes"] }),
  });
}
