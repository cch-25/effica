"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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

export function useFeedQuery() {
  return useQuery({ queryKey: ["feed"], queryFn: async () => mapFeedPage(await apiRequest<FeedPageDto>("/feed")) });
}

export function useIssuesQuery() {
  return useQuery({ queryKey: ["issues"], queryFn: async () => mapIssuePage(await apiRequest<IssuePageDto>("/issues")) });
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
  return useQuery({ queryKey: ["visualization", "points"], queryFn: async () => mapVisualizationPointPage(await apiRequest<VisualizationPointPageDto>("/visualization/points")) });
}

export function useVoteMutation(articleId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: { x: number; y: number; z: number; sensationalism: number }) => apiRequest(`/articles/${articleId}/vote`, { method: "PUT", body: JSON.stringify(payload) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["article", articleId, "votes"] }),
  });
}
