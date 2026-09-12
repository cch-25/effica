import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import ProgressPage from "@/app/progress/page";

const request = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({ apiRequest: request }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
it("이전 활동을 이어 불러오며 만료된 기사에는 깨진 링크를 만들지 않는다", async () => {
  request.mockImplementation(async (path: string) => {
    if (path === "/me/progress") return { read_article_count: 21, compared_issue_count: 2, source_diversity_count: 3 };
    if (path === "/me/activity") return { items: [{ id: "a", read: true, last_activity_at: "2026-09-12T01:00:00Z", article: { id: "a", title: "읽은 기사", source: "언론", issue_id: "issue-a" }, my_vote: { x: 33, sensationalism: 50 }, ai_score: { x: 10, sensationalism: 20 } }], next_cursor: "older" };
    if (path === "/me/activity?cursor=older") return { items: [{ id: "b", read: true, last_activity_at: "2026-09-11T01:00:00Z", article: null, my_vote: null, ai_score: null }], next_cursor: null };
    throw new Error(path);
  });
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ProgressPage /></QueryClientProvider>);
  expect(await screen.findByRole("link", { name: "언론: 읽은 기사" })).toHaveAttribute("href", "/articles/a");
  expect(screen.getByText(/내 평가:.*33.*AI 분석/)).toBeVisible();
  expect(screen.queryByText("2026-09-12T01:00:00Z")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "이전 기록 더 보기" }));
  expect(await screen.findByText("공개 기간이 지난 기사")).toBeVisible();
  expect(screen.queryByRole("button", { name: "이전 기록 더 보기" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "공개 기간이 지난 기사" })).not.toBeInTheDocument();
});
