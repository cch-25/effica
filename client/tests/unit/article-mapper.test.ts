import { expect, it } from "vitest";
import { mapArticle, type ArticleApiResponse, type ArticleScoreApiResponse } from "@/features/articles/mapper";

it("maps API response into a feature view model", () => {
  const response: ArticleApiResponse = { id: "a1", issue_id: "i1", source_id: "s1", source: "출처", title: "제목", summary: "요약", published_at: "2026-08-16T00:00:00Z", canonical_url: "https://example.com", current_version_id: "av1", analysis_status: "READY", analysis_provider: "openai", status: "active" };
  const score: ArticleScoreApiResponse = { id: "score1", article_version_id: "av1", x: 1, y: 2, z: 3, sensationalism: 4, confidence: .8, components: {}, status: "ACTIVE", analysis_provider: "openai", analysis_status: "READY", created_at: "2026-08-16T00:00:00Z" };
  expect(mapArticle(response, score)).toMatchObject({ issueId: "i1", source: "출처", scoreVersion: "score1", x: 1 });
});
