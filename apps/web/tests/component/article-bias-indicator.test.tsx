import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RealArticleDetail } from "@/features/articles/real-article-detail";
import { ArticleCard } from "@/features/feed/article-card";
import type { Article } from "@/lib/api/types";

const mocks = vi.hoisted(() => ({ useArticleQuery: vi.fn() }));

vi.mock("@/lib/api/queries", () => ({ useArticleQuery: mocks.useArticleQuery }));
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
  });

  it("기사 상세에 한국어 편향 라벨과 x값을 표시한다", () => {
    mocks.useArticleQuery.mockReturnValue({ isPending: false, isError: false, data: article });

    render(<RealArticleDetail articleId={article.id} />);

    expect(screen.getByText("LLM 평가 편향 · 좌편향 · -24")).toBeVisible();
    expect(screen.getByText("LLM 평가 과장성 · 0/100")).toBeVisible();
    expect(screen.queryByText("사회문화")).not.toBeInTheDocument();
    expect(screen.queryByText("국가·대외")).not.toBeInTheDocument();
  });
});
