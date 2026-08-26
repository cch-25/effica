import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { VoteForm } from "@/features/voting/vote-form";
import { ApiError } from "@/lib/api/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const mocks = vi.hoisted(() => ({ apiRequest: vi.fn() }));

vi.mock("@/lib/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/client")>("@/lib/api/client");
  return { ...actual, apiRequest: mocks.apiRequest };
});

function notFound(): never {
  throw new ApiError(404, {
    error: { code: "NOT_FOUND", message: "missing", request_id: "test", retryable: false, details: {} },
  }, null);
}

function unauthorized(): never {
  throw new ApiError(401, {
    error: { code: "AUTH_REQUIRED", message: "login", request_id: "test", retryable: false, details: {} },
  }, null);
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderVoteForm() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><VoteForm articleId="article-1" /></QueryClientProvider>);
}

it("7단계 편향성·과장성 선택을 숨은 y/z 중앙값과 함께 제출한다", async () => {
  mocks.apiRequest.mockImplementation(async (_path: string, init?: RequestInit) => {
    if ((init?.method ?? "GET") === "GET") notFound();
    return { revision: 2 };
  });
  renderVoteForm();

  await waitFor(() => expect(mocks.apiRequest).toHaveBeenCalledWith("/articles/article-1/vote", { authFailureMode: "return-error" }));

  expect(await screen.findAllByRole("button", { name: /좌편향|중립|우편향/ })).toHaveLength(7);
  expect(await screen.findAllByRole("button", { name: /낮음|보통|높음/ })).toHaveLength(7);

  fireEvent.click(screen.getByRole("button", { name: "우편향 +67" }));
  fireEvent.click(screen.getByRole("button", { name: "높음 +83" }));
  fireEvent.click(screen.getByRole("button", { name: "투표 저장·수정" }));

  await waitFor(() => expect(mocks.apiRequest).toHaveBeenCalledWith("/articles/article-1/vote", {
    method: "PUT",
    body: JSON.stringify({ x: 67, y: 0, z: 0, sensationalism: 83 }),
  }));
});

it("DELETE 성공 뒤에만 투표 화면을 초기화한다", async () => {
  mocks.apiRequest.mockImplementation(async (path: string, init?: RequestInit) => {
    if ((init?.method ?? "GET") === "GET" && path.endsWith("/vote")) {
      return {
        article_id: "article-1",
        x: 67,
        y: 0,
        z: 0,
        sensationalism: 83,
        revision: 1,
        active: true,
      };
    }
    if ((init?.method ?? "GET") === "GET") notFound();
    return undefined;
  });
  renderVoteForm();
  await waitFor(() => expect(mocks.apiRequest).toHaveBeenCalledWith("/articles/article-1/vote", { authFailureMode: "return-error" }));
  fireEvent.click(await screen.findByRole("button", { name: "내 투표 삭제" }));
  await waitFor(() => expect(mocks.apiRequest).toHaveBeenCalledWith("/articles/article-1/vote", { method: "DELETE" }));
  expect(screen.getByText(/활성 투표가 삭제/)).toBeVisible();
});

it("게스트의 선택적 투표 조회는 공개 기사 화면을 유지하고 로그인 CTA를 표시한다", async () => {
  mocks.apiRequest.mockImplementation(async () => unauthorized());

  renderVoteForm();

  const link = await screen.findByRole("link", { name: "로그인 후 평가하기" });
  expect(link).toHaveAttribute("href", "/login?returnTo=%2Farticles%2Farticle-1");
});
