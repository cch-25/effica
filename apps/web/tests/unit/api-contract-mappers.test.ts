import { expect, it } from "vitest";
import {
  mapFeedPage,
  mapIssuePage,
  mapVisualizationPointPage,
  type FeedPageDto,
  type IssuePageDto,
  type VisualizationPointPageDto,
} from "@/lib/api/mappers";

it("maps the generated feed contract and normalizes backend reason codes", () => {
  const response: FeedPageDto = {
    personalized: false,
    items: [{ article_id: "a1", issue_id: "i1", title: "제목", source: "출처", coordinate: { x: 1, y: 2, z: 3, sensationalism: null, confidence: 0.8 }, reason_code: "FALLBACK_BALANCED", rank: 1 }],
  };
  expect(mapFeedPage(response).items[0]).toMatchObject({ id: "a1", issueId: "i1", reasonCode: "ISSUE_BALANCE", sensationalism: null });
});

it("maps generated issue and visualization contracts to camelCase screen models", () => {
  const issues: IssuePageDto = {
    items: [{ id: "i1", title: "이슈", summary: "요약", status: "active", version: 1, article_ids: ["a1", "a2"], opened_at: "2026-08-16T00:00:00Z", last_activity_at: "2026-08-16T01:00:00Z" }],
  };
  const points: VisualizationPointPageDto = {
    items: [{ entity_type: "article", entity_id: "a1", label: "기사", x: 4, y: 5, z: 6, confidence: 0.7 }],
  };
  expect(mapIssuePage(issues).items[0]).toMatchObject({ id: "i1", status: "balanced", articleIds: ["a1", "a2"] });
  expect(mapVisualizationPointPage(points).items[0]).toMatchObject({ id: "a1", type: "article", scoreVersion: "current", sensationalism: null });
});
