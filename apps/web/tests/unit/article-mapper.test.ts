import { expect, it } from "vitest";
import { mapArticle, type ArticleApiResponse } from "@/features/articles/mapper";

it("maps API response into a feature view model", () => {
  const response: ArticleApiResponse = { id: "a1", issue_id: "i1", source_id: "s1", source_name: "출처", title: "제목", summary: "요약", published_at: "2026-08-16T00:00:00Z", original_url: "https://example.com", reason_code: "ISSUE_BALANCE", score: { x: 1, y: 2, z: 3, sensationalism: 4, confidence: .8, version: "v1" }, claims: ["주장"] };
  expect(mapArticle(response)).toMatchObject({ issueId: "i1", source: "출처", scoreVersion: "v1", x: 1 });
});
