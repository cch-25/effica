import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { IssuesBrowser } from "@/features/issues/issues-browser";
import { articles, issues } from "@/mocks/fixtures/content";
import type { Issue } from "@/lib/api/types";

const mocks = vi.hoisted(() => ({ useIssuesQuery: vi.fn(), useIssueArticleCollectionsQuery: vi.fn() }));

vi.mock("@/lib/api/queries", () => ({
  useIssuesQuery: mocks.useIssuesQuery,
  useIssueArticleCollectionsQuery: mocks.useIssueArticleCollectionsQuery,
}));

beforeEach(() => {
  mocks.useIssuesQuery.mockReturnValue({ data: { items: issues }, hasNextPage: false, isFetchingNextPage: false, fetchNextPage: () => undefined });
  mocks.useIssueArticleCollectionsQuery.mockImplementation((issueIds: string[]) => ({
    items: issueIds.includes("issue-ai") ? [articles[3]] : [],
    isPending: false,
    isError: false,
  }));
});

afterEach(cleanup);

it("주제 필터를 열고 선택한 주제의 이슈만 표시한다", () => {
  render(<IssuesBrowser fallback={issues} />);

  expect(screen.getByRole("heading", { name: "오늘의 이슈" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "주요 이슈 TOP 10" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "대주제별 이슈" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "경제" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "국제" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "산업" })).toBeVisible();
  expect(screen.getAllByText("도심 주택 공급 대책")).toHaveLength(2);

  const filterButton = screen.getByRole("button", { name: "주제·기간" });
  fireEvent.click(filterButton);
  fireEvent.click(screen.getByRole("checkbox", { name: "산업" }));

  expect(screen.getByText("공공 AI 기본법 시행령, 혁신과 책임의 경계")).toBeVisible();
  expect(screen.queryByText("도심 주택 공급 대책")).not.toBeInTheDocument();
  expect(filterButton).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByRole("button", { name: "0개 이슈 · 1개 대주제 보기" })).toBeVisible();
});

it("검증된 사건 이슈에서 편집 우선순위 기준 TOP 10만 고르고 대주제에는 모두 남긴다", () => {
  const manyIssues: Issue[] = Array.from({ length: 12 }, (_, index) => ({
    ...issues[0],
    id: `ranked-${index + 1}`,
    title: `이슈 ${String(index + 1).padStart(2, "0")}`,
    topic: "정치",
    editorialPriority: index + 1,
  }));
  mocks.useIssuesQuery.mockReturnValue({ data: { items: manyIssues }, hasNextPage: false, isFetchingNextPage: false, fetchNextPage: () => undefined });

  const { container } = render(<IssuesBrowser fallback={manyIssues} />);
  const ranking = container.querySelector(".issue-rank-list");

  expect(ranking?.querySelectorAll(":scope > li")).toHaveLength(10);
  expect(ranking?.querySelector("li:first-child")).toHaveTextContent("이슈 01");
  expect(ranking).not.toHaveTextContent("이슈 11");
  expect(screen.getByRole("heading", { name: "정치" })).toBeVisible();
  expect(screen.getByRole("button", { name: "6개 더 보기" })).toBeVisible();
});

it("기사 수가 많은 광역 TOPIC으로 주요 이슈 빈자리를 채우지 않는다", () => {
  const topicBucket: Issue = {
    ...issues[0],
    id: "topic-culture",
    title: "문화",
    summary: "문화 분야의 최신 한국어 원문 기사 모음",
    topic: "사회",
    kind: "TOPIC",
    sourceCount: 20,
    articleIds: Array.from({ length: 100 }, (_, index) => `article-${index}`),
  };
  mocks.useIssuesQuery.mockReturnValue({ data: { items: [issues[0], topicBucket] }, hasNextPage: false, isFetchingNextPage: false, fetchNextPage: () => undefined });

  const { container } = render(<IssuesBrowser fallback={[]} />);
  const ranking = container.querySelector(".issue-rank-list");

  expect(ranking).toHaveTextContent(issues[0].title);
  expect(ranking).not.toHaveTextContent("문화");
  expect(screen.getByText("1/10 검증 완료")).toBeVisible();
});
