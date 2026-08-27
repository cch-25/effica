import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RealArticleDetail } from "@/features/articles/real-article-detail";
import { ArticleCard } from "@/features/feed/article-card";
import type { Article } from "@/lib/api/types";

const mocks = vi.hoisted(() => ({ useArticleQuery: vi.fn(), useArticleAnalysisQuery: vi.fn(), useViewerQuery: vi.fn() }));

vi.mock("@/lib/api/queries", () => ({ useArticleQuery: mocks.useArticleQuery, useArticleAnalysisQuery: mocks.useArticleAnalysisQuery, useViewerQuery: mocks.useViewerQuery }));
vi.mock("@/features/voting/vote-form", () => ({ VoteForm: () => <div>투표 폼</div> }));

const article: Article = {
  id: "article-1",
  issueId: "issue-1",
  sourceId: "source-1",
  source: "한국언론",
  title: "실제 한국어 기사 제목",
  dek: "기사 요약",
  publishedAt: "2026-08-16T00:00:00Z",
  originalUrl: "https://example.com/article-1",
  reasonCode: "ISSUE_BALANCE",
  scoreVersion: "llm-v1",
  analysisStatus: "READY",
  analysisProvider: "openai",
  x: -24,
  y: 0,
  z: 0,
  sensationalism: 0,
  confidence: 0.9,
  claims: [],
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("기사 LLM 편향 표시", () => {
  it("기사 카드에 한국어 편향 라벨과 x값을 표시한다", () => {
    render(<ArticleCard article={article} />);

    expect(screen.getByText("LLM 평가 편향 · 좌편향 · -24")).toBeVisible();
    expect(screen.getByText("LLM 평가 과장성 · 0/100")).toBeVisible();
    expect(screen.getByText("2026. 08. 16.")).toBeVisible();
    expect(screen.queryByText("8분")).not.toBeInTheDocument();
  });

  it("준비 중 기사는 임의 점수 대신 분석 상태를 표시한다", () => {
    render(<ArticleCard article={{ ...article, analysisStatus: "PROCESSING", analysisProvider: null }} />);

    expect(screen.getByText("분석 준비 중")).toBeVisible();
    expect(screen.queryByText(/LLM 평가 편향/)).not.toBeInTheDocument();
  });

  it("기사 상세에 한국어 편향 라벨과 x값을 표시한다", () => {
    mocks.useArticleQuery.mockReturnValue({ isPending: false, isError: false, data: article });
    mocks.useArticleAnalysisQuery.mockReturnValue({ isPending: false, isError: false, data: { assessments: { article_version_id: "v1", assessments: [] }, history: { items: [] } } });
    mocks.useViewerQuery.mockReturnValue({ data: undefined });

    render(<RealArticleDetail articleId={article.id} />);

    expect(screen.getByText("LLM 평가 편향 · 좌편향 · -24")).toBeVisible();
    expect(screen.getByText("LLM 평가 과장성 · 0/100")).toBeVisible();
    expect(screen.getByRole("button", { name: /편향성: 기사의 주장과 강조점/ })).toBeVisible();
    expect(screen.getByText(/각 분석 기록에서 공개 근거 제공 여부/)).toBeVisible();
    expect(screen.queryByText("사회문화")).not.toBeInTheDocument();
    expect(screen.queryByText("국가·대외")).not.toBeInTheDocument();
  });
});
