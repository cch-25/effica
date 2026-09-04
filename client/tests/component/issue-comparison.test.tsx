import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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

it("shows public article-level analysis while the cross-article review is pending", () => {
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

  expect(screen.getByRole("status", { name: "이슈 비교 준비 상태" })).toBeVisible();
  expect(screen.getByText("비교 준비 완료 기사 2개, 출처 2곳")).toBeVisible();
  expect(screen.getByRole("heading", { name: "기사별 AI 분석 비교" })).toBeVisible();
  expect(screen.getByText("공통 사실과 보도 프레임은 편집 검수 후 공개됩니다.")).toBeVisible();
  expect(screen.getAllByRole("button", { name: /편향성:/ })).toHaveLength(2);
  expect(screen.getAllByRole("link", { name: /기사 원문 보기, 새 창/ })).toHaveLength(2);
  expect(screen.queryByRole("heading", { name: "공통으로 확인된 사실" })).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "잠시 연결이 불안정합니다" })).not.toBeInTheDocument();
});

it("keeps the comparison focused on shared facts, framing, and the two scores", () => {
  mocks.useIssueComparisonQuery.mockReturnValue({
    data: {
      issue: {
        id: "issue-1",
        article_count: 2,
        source_count: 2,
        data_as_of: "2026-08-26T00:00:00Z",
      },
      common_facts: [{ id: "fact-1", text: "두 기사는 같은 정책 발표를 다룹니다." }],
      articles: [
        {
          article: { id: "a", source: "출처 A", title: "출처 A 기사", published_at: "2026-08-26T00:00:00Z", canonical_url: "https://a.example.test" },
          score: { x: -24, sensationalism: 31, confidence: .91, created_at: "2026-08-26T00:10:00Z" },
          assessment: { summary: "정책 수혜 범위를 중심으로 설명합니다.", model_alias: "analysis", actual_model_id: "gpt-5", prompt_version: "v1" },
          frame: { headline_frame: "수혜 대상을 중심으로 봅니다.", emphasis: ["수혜 대상"], omissions_note: "집행 일정은 확인되지 않았습니다.", evidence_refs: ["문단 2"] },
          vote_aggregate: { status: "ready", qualified_count: 3, qualified: { x: -10, sensationalism: 28 }, small_segments_suppressed: false },
        },
        {
          article: { id: "b", source: "출처 B", title: "출처 B 기사", published_at: "2026-08-26T00:00:00Z", canonical_url: "https://b.example.test" },
          score: { x: 38, sensationalism: 52, confidence: .86, created_at: "2026-08-26T00:11:00Z" },
          assessment: { summary: "정책 집행 조건을 중심으로 설명합니다.", model_alias: "analysis", actual_model_id: "gpt-5", prompt_version: "v1" },
          frame: { headline_frame: "집행 조건을 중심으로 봅니다.", emphasis: ["집행 조건"], omissions_note: null, evidence_refs: ["문단 1"] },
          vote_aggregate: { status: "ready", qualified_count: 0, qualified: { x: null, sensationalism: null }, small_segments_suppressed: true },
        },
      ],
      comparison_version: "comparison-v1",
      model_alias: "comparison",
      actual_model_id: "gpt-5",
      prompt_version: "v1",
      reviewed_at: "2026-08-26T01:00:00Z",
    },
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  });

  render(<IssueComparison issue={issue} articles={[article("a", "출처 A"), article("b", "출처 B")]} initialArticles="a,b" />);

  expect(screen.getByRole("heading", { name: "공통으로 확인된 사실" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "보도별 관점" })).toBeVisible();
  expect(screen.getAllByText("핵심 관점")).toHaveLength(2);
  expect(screen.getAllByRole("link", { name: /기사 원문 보기, 새 창/ })).toHaveLength(2);
  expect(screen.getAllByRole("button", { name: /편향성:/ })).toHaveLength(2);
  expect(screen.getAllByText(/분석 신뢰도/)).toHaveLength(2);
  expect(screen.getAllByText("독자 평가 / AI 평가와 별도")).toHaveLength(2);
  expect(screen.getAllByRole("link", { name: "상세 분석 보기" })).toHaveLength(2);
});

it("repairs an invalid article URL to a ready selection from distinct sources", () => {
  mocks.useIssueComparisonQuery.mockReturnValue({
    data: undefined,
    isPending: true,
    isError: false,
    error: null,
    refetch: vi.fn(),
  });

  render(<IssueComparison issue={issue} articles={[article("a", "출처 A"), article("b", "출처 B")]} initialArticles="missing,b" />);

  expect(mocks.replace).toHaveBeenCalledWith("/issues/issue-1?articles=a%2Cb", { scroll: false });
  expect(screen.getByText("2개 기사, 2곳 출처 선택")).toBeVisible();
});

it("does not add a second article from an already selected source", () => {
  mocks.useIssueComparisonQuery.mockReturnValue({
    data: undefined,
    isPending: true,
    isError: false,
    error: null,
    refetch: vi.fn(),
  });

  render(<IssueComparison
    issue={{ ...issue, articleIds: ["a", "b", "c"] }}
    articles={[article("a", "출처 A"), article("b", "출처 B"), article("c", "출처 A")]}
    initialArticles="a,b"
  />);
  fireEvent.click(screen.getByRole("button", { name: "출처 A 기사 비교에 추가하기" }));

  expect(screen.getByText("같은 출처에서는 기사 1개만 선택할 수 있습니다.")).toBeVisible();
  expect(screen.getByText("2개 기사, 2곳 출처 선택")).toBeVisible();
  expect(mocks.replace).not.toHaveBeenCalled();
});

it("keeps issue context and hides the selector while fewer than two articles are ready", () => {
  mocks.useIssueComparisonQuery.mockReturnValue({
    data: undefined,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  });
  const processing = { ...article("b", "출처 B"), analysisStatus: "PROCESSING" as const };

  render(<IssueComparison issue={issue} articles={[article("a", "출처 A"), processing]} initialArticles="a,b" />);

  expect(screen.getByRole("heading", { name: "비교 이슈" })).toBeVisible();
  expect(screen.getByText("비교할 이슈의 요약")).toBeVisible();
  expect(screen.getByRole("link", { name: "전체 이슈로 돌아가기" })).toHaveAttribute("href", "/issues");
  expect(screen.getByText("비교 준비 완료 기사 1개, 출처 1곳")).toBeVisible();
  expect(screen.getByRole("heading", { name: "현재 확인할 수 있는 기사" })).toBeVisible();
  expect(screen.getByRole("link", { name: "출처 A 기사" })).toHaveAttribute("href", "/articles/a");
  expect(screen.queryByRole("heading", { name: "비교할 기사" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /기사 원문 보기, 새 창/ })).not.toBeInTheDocument();
});
