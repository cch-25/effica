import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { AnalysisReadinessNotice } from "@/features/articles/analysis-readiness-notice";

const mocks = vi.hoisted(() => ({ apiRequest: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ apiRequest: mocks.apiRequest }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

it("주요 이슈가 준비되면 오래된 이슈 목록도 다시 조회한다", async () => {
  mocks.apiRequest.mockResolvedValue({ status: "READY", reason: "CURRENT_EVENT_AVAILABLE", checked_at: "2026-09-10T00:00:00Z", next_eligible_at: null, refresh_interval_seconds: 900 });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(<QueryClientProvider client={client}><AnalysisReadinessNotice /></QueryClientProvider>);
  expect(await screen.findByText("비교할 수 있는 이슈가 준비되어 있습니다.")).toBeVisible();
  await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["issues"] }));
});

it("일일 제한의 재개 가능 시각을 분석 완료 예정으로 표시하지 않는다", async () => {
  mocks.apiRequest.mockResolvedValue({ status: "DEFERRED", reason: "DAILY_SELECTION_DEFERRED", checked_at: "2026-09-10T00:00:00Z", next_eligible_at: "2026-09-10T15:00:00Z" });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><AnalysisReadinessNotice articleId="a" /></QueryClientProvider>);
  expect(await screen.findByText("다음 분석 기회를 기다리고 있습니다.")).toBeVisible();
  expect(screen.getByText(/이 시각에 완료되는 것은 아닙니다/)).toBeVisible();
});
