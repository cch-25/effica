import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { IssuesBrowser } from "@/features/issues/issues-browser";
import { articles, issues } from "@/mocks/fixtures/content";
import type { Issue } from "@/lib/api/types";

const mocks = vi.hoisted(() => ({ useIssuesQuery: vi.fn(), useIssueArticleCollectionsQuery: vi.fn() }));

vi.mock("@/lib/api/queries", () => ({
  useIssuesQuery: mocks.useIssuesQuery,
  useIssueArticleCollectionsQuery: mocks.useIssueArticleCollectionsQuery,
}));
vi.mock("@/features/articles/analysis-readiness-notice", () => ({ AnalysisReadinessNotice: () => <p>주요 이슈 공개 조건을 확인하고 있습니다.</p> }));

beforeEach(() => {
  mocks.useIssuesQuery.mockReturnValue({ data: { items: issues }, hasNextPage: false, isFetchingNextPage: false, fetchNextPage: () => undefined });
  mocks.useIssueArticleCollectionsQuery.mockImplementation((issueIds: string[]) => ({
    items: issueIds.includes("issue-ai") ? [articles[3]] : [],
    isPending: false,
    isError: false,
  }));
});

afterEach(cleanup);

it("아무 이슈도 없는 초기 상태에는 필터 안내 대신 실제 준비 상태를 보여 준다", () => {
  mocks.useIssuesQuery.mockReturnValue({ data: { items: [] }, hasNextPage: false, isFetchingNextPage: false });
  render(<IssuesBrowser fallback={[]} />);
  expect(screen.getByText("주요 이슈 공개 조건을 확인하고 있습니다.")).toBeVisible();
  expect(screen.queryByText("조건에 맞는 이슈가 없습니다.")).not.toBeInTheDocument();
});

it("주제 필터를 열고 선택한 주제의 이슈만 표시한다", () => {
  render(<IssuesBrowser fallback={issues} />);

  expect(screen.getByRole("heading", { name: "오늘의 이슈" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "지금 비교할 수 있는 주요 이슈" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "주제별 전체 찾아보기" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "경제" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "정치" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "사회" })).toBeVisible();
  expect(screen.getAllByText("도심 주택 공급 대책")).toHaveLength(2);
  expect(screen.getAllByText("이슈 A")).toHaveLength(2);
  expect(screen.getByText("기사")).toBeVisible();

  const filterButton = screen.getByRole("button", { name: "주제와 기간" });
  fireEvent.click(filterButton);
  fireEvent.click(screen.getByRole("checkbox", { name: "사회" }));

  expect(screen.getByText("공공 AI 기본법 시행령, 혁신과 책임의 경계")).toBeVisible();
  expect(screen.queryByText("도심 주택 공급 대책")).not.toBeInTheDocument();
  expect(filterButton).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByRole("button", { name: "0개 이슈, 1개 대주제 보기" })).toBeVisible();
});

it("비교 준비가 끝난 이슈와 주제별 목록에 선정된 모든 이슈를 남긴다", () => {
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

  expect(ranking?.querySelectorAll(":scope > li")).toHaveLength(12);
  expect(ranking?.querySelector("li:first-child")).toHaveTextContent("이슈 01");
  expect(within(ranking!.querySelector<HTMLElement>("li:first-child")!).getByText("이슈 A")).toBeVisible();
  expect(within(ranking!.querySelectorAll<HTMLElement>(":scope > li")[1]).getByText("이슈 B")).toBeVisible();
  expect(ranking).toHaveTextContent("이슈 12");
  expect(ranking).not.toHaveTextContent("01위");
  expect(screen.getByRole("heading", { name: "정치" })).toBeVisible();
  expect(screen.getByRole("button", { name: "6개 더 보기" })).toBeVisible();
});

it("분류에서 벗어난 이전 이슈를 제외하고 세 분야만 필터에 제공한다", () => {
  mocks.useIssuesQuery.mockReturnValue({ data: { items: [issues[0], { ...issues[0], id: "sports", title: "프로야구 경기 결과", topic: "스포츠" }] } });
  render(<IssuesBrowser fallback={[]} />);
  expect(screen.queryByText("프로야구 경기 결과")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "주제와 기간" }));
  expect(screen.getAllByRole("checkbox")).toHaveLength(3);
  for (const topic of ["정치", "사회", "경제"]) expect(screen.getByRole("checkbox", { name: topic })).toBeVisible();
  expect(screen.queryByRole("checkbox", { name: "스포츠" })).not.toBeInTheDocument();
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
  expect(screen.getByText("1개 준비")).toBeVisible();
});
