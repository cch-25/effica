import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { IssuesBrowser } from "@/features/issues/issues-browser";
import { issues } from "@/mocks/fixtures/content";

const query = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/queries", () => ({ useIssuesQuery: query }));
beforeEach(() => query.mockReturnValue({ data: { items: issues } }));
afterEach(cleanup);

it("이슈를 한 번씩 표시하고 중복 기사를 빼고 수를 센다", () => {
  const rows = [{ ...issues[0], articleIds: ["a", "b"] }, { ...issues[0], id: "other", title: "다른 이슈", articleIds: ["b", "c"] }];
  query.mockReturnValue({ data: { items: rows } });
  render(<IssuesBrowser fallback={[]} />);
  expect(screen.getAllByRole("link")).toHaveLength(2);
  expect(screen.getByText("2개 이슈 / 3개 기사")).toBeVisible();
  expect(screen.queryByRole("navigation", { name: "이슈 주제" })).not.toBeInTheDocument();
});

it("현재 자료가 있는 주제로만 필터링한다", () => {
  query.mockReturnValue({ data: { items: [{ ...issues[0], topic: "정치" }, { ...issues[1], topic: "경제" }] } });
  render(<IssuesBrowser fallback={[]} />);
  expect(screen.queryByRole("button", { name: "사회" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "경제" }));
  expect(screen.getAllByRole("link")).toHaveLength(1);
  expect(screen.getByRole("link")).toHaveAttribute("href", `/issues/${issues[1].id}`);
});

it("빈 목록은 진행 중인 작업처럼 표시하지 않는다", () => {
  query.mockReturnValue({ data: { items: [] } });
  render(<IssuesBrowser fallback={[]} />);
  expect(screen.getByText("현재 표시할 이슈가 없습니다.")).toBeVisible();
});

it("지원되지 않는 주제는 표시하지 않는다", () => {
  query.mockReturnValue({ data: { items: [{ ...issues[0], topic: "스포츠" }] } });
  render(<IssuesBrowser fallback={[]} />);
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
});
