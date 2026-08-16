import type { Article } from "@/lib/api/types";

export type ArticleApiResponse = {
  id: string; issue_id: string; source_id: string; source_name: string; title: string; summary: string;
  published_at: string; original_url: string; reason_code: Article["reasonCode"];
  score: { x: number; y: number; z: number; sensationalism: number; confidence: number; version: string; stale?: boolean };
  claims: string[];
};

export function mapArticle(response: ArticleApiResponse): Article {
  return { id: response.id, issueId: response.issue_id, sourceId: response.source_id, source: response.source_name, title: response.title, dek: response.summary, publishedAt: response.published_at, originalUrl: response.original_url, reasonCode: response.reason_code, ...response.score, scoreVersion: response.score.version, stale: response.score.stale, claims: response.claims };
}
