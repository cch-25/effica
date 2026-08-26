import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { IssueComparison } from "@/features/issues/comparison/issue-comparison";
import { ApiError } from "@/lib/api/client";
import type { Article, Issue } from "@/lib/api/types";

const mocks = vi.hoisted(() => ({ replace: vi.fn(), useIssueComparisonQuery: vi.fn() }));

vi.mock("next/navigation", () => ({
  usePathname: () => "/issues/issue-1",
  useRouter: () => ({ replace: mocks.replace }),
}));

vi.mock("@/lib/api/queries", () => ({
  useIssueComparisonQuery: mocks.useIssueComparisonQuery,
}));

function article(id: string, source: string): Article {
  return {
    id,
    issueId: "issue-1",
    sourceId: source,
    source,
    title: `${source} 기사`,
    dek: "",
    publishedAt: "2026-08-26T00:00:00Z",
    originalUrl: "https://example.test",
    reasonCode: "ISSUE_BALANCE",
    x: 0,
    y: 0,
    z: 0,
    sensationalism: 0,
    confidence: 0.8,
    scoreVersion: "score-1",
    analysisStatus: "READY",
    analysisProvider: "openai",
    claims: [],
  };
}

const issue: Issue = {
  id: "issue-1",
  title: "비교 이슈",
  summary: "비교할 이슈의 요약",
  topic: "일반",
  status: "balanced",
  kind: "EVENT",
  sourceCount: 2,
  analysisStatus: "READY",
  dataAsOf: "2026-08-26T00:00:00Z",
  freshnessStatus: "CURRENT",
  editorialPriority: 1,
  updatedAt: "2026-08-26T00:00:00Z",
  articleIds: ["a", "b"],
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("shows an honest processing state when the reviewed comparison is not ready", () => {
  mocks.useIssueComparisonQuery.mockReturnValue({
    data: undefined,
    isPending: false,
    isError: true,
    error: new ApiError(409, {
      error: {
        code: "COMPARISON_NOT_READY",
        message: "A reviewed comparison is not ready.",
        request_id: "request-1",
        retryable: false,
        details: {},
      },
    }, null),
    refetch: vi.fn(),
  });

  render(<IssueComparison issue={issue} articles={[article("a", "출처 A"), article("b", "출처 B")]} initialArticles="a,b" />);

  expect(screen.getByRole("heading", { name: "준비 중입니다" })).toBeVisible();
  expect(screen.queryByRole("heading", { name: "잠시 연결이 불안정합니다" })).not.toBeInTheDocument();
});
