import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ProgressPage from "@/app/progress/page";

const mocks = vi.hoisted(() => ({ apiRequest: vi.fn() }));

vi.mock("@/lib/api/client", () => ({ apiRequest: mocks.apiRequest }));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("progress credit pagination", () => {
  it("loads older ledger rows without presenting the first page as a total", async () => {
    mocks.apiRequest.mockImplementation(async (path: string) => {
      if (path === "/me/progress") {
        return { credit_total: 30, level: 1, tier: "STARTER", policy_version: "v1" };
      }
      if (path === "/me/credits") {
        return {
          items: [
            { event_type: "READ_RETURN", created_at: "2026-08-19T00:00:00Z", delta: 10, policy_version: "v1" },
            { event_type: "UNRECOGNIZED_EVENT", created_at: "2026-08-19T01:00:00Z", delta: 0, policy_version: "v1" },
          ],
          next_cursor: "older",
        };
      }
      if (path === "/me/credits?cursor=older") {
        return {
          items: [{ event_type: "COMPARE", created_at: "2026-08-18T00:00:00Z", delta: 20, policy_version: "v1" }],
          next_cursor: null,
        };
      }
      throw new Error(`unexpected request: ${path}`);
    });

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <ProgressPage />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("원문 읽기 복귀 확인")).toBeVisible();
    expect(screen.getByText("기타 활동")).toBeVisible();
    expect(screen.queryByText("READ_RETURN")).not.toBeInTheDocument();
    expect(screen.queryByText("UNRECOGNIZED_EVENT")).not.toBeInTheDocument();
    expect(screen.getByText("불러온 기록")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "이전 기록 더 보기" }));

    await waitFor(() => expect(screen.getByText("이슈 비교")).toBeVisible());
    expect(screen.queryByText("COMPARE")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "이전 기록 더 보기" })).not.toBeInTheDocument();
  });
});
