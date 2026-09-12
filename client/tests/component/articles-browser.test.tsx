import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ArticlesBrowser } from "@/features/articles/articles-browser";
import { articles, issues } from "@/mocks/fixtures/content";

const mocks = vi.hoisted(() => ({
  loadIssues: vi.fn(),
  loadArticles: vi.fn(),
  push: vi.fn(),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock("@/features/articles/article-directory-data", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/features/articles/article-directory-data")>();
  return { ...actual, loadDirectoryIssues: mocks.loadIssues, loadDirectoryArticles: mocks.loadArticles };
});

describe("articles browser", () => {
  beforeEach(() => {
    mocks.loadIssues.mockReset();
    mocks.loadArticles.mockReset();
    mocks.push.mockReset();
  });

  it("loads and displays articles from every topic without category navigation", async () => {
    const allIssues = [
      { ...issues[0], id: "politics", topic: "정치", articleIds: ["politics-article"] },
      { ...issues[0], id: "society", topic: "사회", articleIds: ["society-article"] },
      { ...issues[0], id: "economy", topic: "경제", articleIds: ["economy-article"] },
    ];
    const allArticles = [
      { ...articles[0], id: "politics-article", title: "정치 기사" },
      { ...articles[0], id: "society-article", title: "사회 기사" },
      { ...articles[0], id: "economy-article", title: "경제 기사" },
    ];
    mocks.loadIssues.mockResolvedValue(allIssues);
    mocks.loadArticles.mockResolvedValue({ articles: allArticles, failedIssueIds: [] });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(<QueryClientProvider client={queryClient}><ArticlesBrowser filters={{ q: "", source: "" }} /></QueryClientProvider>);

    for (const title of ["정치 기사", "사회 기사", "경제 기사"]) expect(await screen.findByRole("link", { name: title })).toBeVisible();
    expect(screen.queryByRole("navigation", { name: "기사 카테고리" })).not.toBeInTheDocument();
    expect(screen.getByText("모든 기사를 최신순으로 읽고, 언론사 원문과 분석을 확인하세요.")).toBeVisible();
    expect(screen.getByText("전체 기사 3개")).toBeVisible();
    await waitFor(() => expect(mocks.loadArticles).toHaveBeenCalledWith(expect.any(AbortSignal)));
  });
});
