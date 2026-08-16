"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Article, Issue, VisualizationPoint } from "./types";
import { apiRequest } from "./client";

type CursorPage<T> = { items: T[]; next_cursor: string | null };

export function useFeedQuery() {
  return useQuery({ queryKey: ["feed"], queryFn: () => apiRequest<CursorPage<Article>>("/feed") });
}

export function useIssuesQuery() {
  return useQuery({ queryKey: ["issues"], queryFn: () => apiRequest<CursorPage<Issue>>("/issues") });
}

export function useVisualizationPointsQuery() {
  return useQuery({ queryKey: ["visualization", "points"], queryFn: () => apiRequest<CursorPage<VisualizationPoint>>("/visualization/points") });
}

export function useVoteMutation(articleId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: { x: number; y: number; z: number; sensationalism: number }) => apiRequest(`/articles/${articleId}/vote`, { method: "PUT", body: JSON.stringify(payload) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["article", articleId, "votes"] }),
  });
}
