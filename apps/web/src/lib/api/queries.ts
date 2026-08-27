"use client";

import { useInfiniteQuery, useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "./client";
import { ApiError } from "./client";
import {
  mapArticle,
  mapArticlePage,
  mapFeedPage,
  mapIssueComparison,
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
import type { Article, IssueComparison, Vote, VoteAggregate } from "./types";

function flattenPages<T>(pages: Array<{ items: T[]; next_cursor: string | null }> | undefined) {
  if (!pages) return undefined;
  return {
    items: pages.flatMap((page) => page.items),
    next_cursor: pages.at(-1)?.next_cursor ?? null,
  };
}

async function loadVisualizationSample(
  type: "article" | "user" | "source",
): Promise<VisualizationPointPageDto["items"]> {
  const params = new URLSearchParams({ type });
  const page = await apiRequest<VisualizationPointPageDto>(`/visualization/points?${params}`);
  return page.items;
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

export function useIssuesQuery(limit = 20) {
  const query = useInfiniteQuery({
    queryKey: ["issues", limit],
    queryFn: async ({ pageParam }) => {
      const params = new URLSearchParams({ limit: String(limit) });
      if (pageParam) params.set("cursor", pageParam);
      return mapIssuePage(await apiRequest<IssuePageDto>(`/issues?${params}`));
    },
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
  });
  return { ...query, data: flattenPages(query.data?.pages) };
}

export function useViewerQuery() {
  return useQuery({
    queryKey: ["me"],
    queryFn: () => apiRequest<{ id: string }>("/me", { authFailureMode: "return-error" }),
    retry: false,
  });
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

export function useIssueArticleCollectionsQuery(issueIds: string[]) {
  const normalizedIds = [...new Set(issueIds)].sort();
  const queries = useQueries({
    queries: normalizedIds.map((issueId) => ({
      queryKey: ["issue", issueId, "articles"],
      queryFn: async () => mapArticlePage(await apiRequest<ArticlePageDto>(`/issues/${encodeURIComponent(issueId)}/articles`)),
      staleTime: 60_000,
    })),
  });
  const byId = new Map<string, Article>();
  for (const query of queries) {
    for (const article of query.data?.items ?? []) byId.set(article.id, article);
  }
  const items = [...byId.values()].sort((left, right) => (
    new Date(right.publishedAt).getTime() - new Date(left.publishedAt).getTime()
      || left.id.localeCompare(right.id)
  ));
  return {
    items,
    isPending: queries.some((query) => query.isPending),
    isError: queries.length > 0 && queries.every((query) => query.isError),
  };
}

export function useIssueComparisonQuery(issueId: string, articleIds: string[]) {
  const normalizedIds = [...articleIds].sort();
  return useQuery({
    queryKey: ["issue", issueId, "comparison", normalizedIds],
    queryFn: async () => {
      const params = new URLSearchParams();
      for (const articleId of normalizedIds) params.append("article_ids", articleId);
      return mapIssueComparison(await apiRequest<IssueComparison>(
        `/issues/${encodeURIComponent(issueId)}/comparison?${params}`,
      ));
    },
    enabled: normalizedIds.length >= 2 && normalizedIds.length <= 4,
  });
}

export function useArticleQuery(articleId: string) {
  return useQuery({
    queryKey: ["article", articleId],
    queryFn: async () => {
      const id = encodeURIComponent(articleId);
      const article = await apiRequest<ArticleDto>(`/articles/${id}`);
      const score = await apiRequest<ScoreDto>(`/articles/${id}/score`).catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      });
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
      const pages = await Promise.all(types.map(loadVisualizationSample));
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
    mutationFn: (payload: { x: number; y: number; z: number; sensationalism: number }) => apiRequest<Vote>(`/articles/${articleId}/vote`, { method: "PUT", body: JSON.stringify(payload) }),
    onSuccess: (vote) => {
      queryClient.setQueryData(["article", articleId, "my-vote"], vote);
      void queryClient.invalidateQueries({ queryKey: ["article", articleId, "vote-aggregate"] });
      void queryClient.invalidateQueries({ queryKey: ["issue"] });
      void queryClient.invalidateQueries({ queryKey: ["me", "progress"] });
      void queryClient.invalidateQueries({ queryKey: ["visualization", "points"] });
    },
  });
}

export function useMyVoteQuery(articleId: string) {
  return useQuery({
    queryKey: ["article", articleId, "my-vote"],
    queryFn: async (): Promise<Vote | null> => {
      try {
        return await apiRequest<Vote>(`/articles/${encodeURIComponent(articleId)}/vote`, {
          authFailureMode: "return-error",
        });
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
    retry: false,
  });
}

export function useVoteAggregateQuery(articleId: string) {
  return useQuery({
    queryKey: ["article", articleId, "vote-aggregate"],
    queryFn: () => apiRequest<VoteAggregate>(
      `/articles/${encodeURIComponent(articleId)}/votes/aggregate`,
    ),
  });
}

export function useDeleteVoteMutation(articleId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiRequest<void>(`/articles/${encodeURIComponent(articleId)}/vote`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: ["article", articleId, "my-vote"] });
      void queryClient.invalidateQueries({ queryKey: ["article", articleId, "vote-aggregate"] });
      void queryClient.invalidateQueries({ queryKey: ["issue"] });
      void queryClient.invalidateQueries({ queryKey: ["me", "progress"] });
      void queryClient.invalidateQueries({ queryKey: ["visualization", "points"] });
    },
  });
}
