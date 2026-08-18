import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useVisualizationPointsQuery } from "@/lib/api/queries";

const mocks = vi.hoisted(() => ({ apiRequest: vi.fn() }));

vi.mock("@/lib/api/client", () => ({ apiRequest: mocks.apiRequest }));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("visualization pagination", () => {
  it("loads every cursor page for article, user, and source points", async () => {
    mocks.apiRequest.mockImplementation(async (path: string) => {
      const url = new URL(path, "https://example.test");
      const type = url.searchParams.get("type") as "article" | "user" | "source";
      const cursor = url.searchParams.get("cursor");
      const suffix = cursor ? "-2" : "-1";
      return {
        items: [{
          entity_type: type,
          entity_id: `${type}${suffix}`,
          label: `${type}${suffix}`,
          x: 0,
          y: 0,
          z: 0,
          sensationalism: 0,
          confidence: 1,
        }],
        next_cursor: cursor ? null : `${type}-next`,
      };
    });

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useVisualizationPointsQuery(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data?.items.map((item) => item.id)).toEqual([
      "article-1",
      "article-2",
      "user-1",
      "user-2",
      "source-1",
      "source-2",
    ]);
    expect(mocks.apiRequest).toHaveBeenCalledWith(
      "/visualization/points?type=article&cursor=article-next",
    );
  });
});
