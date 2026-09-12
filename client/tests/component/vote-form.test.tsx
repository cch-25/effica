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

it("7단계 편향성과 과장성 선택을 숨은 y/z 중앙값과 함께 제출한다", async () => {
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
  fireEvent.click(screen.getByRole("button", { name: "독자 평가 저장" }));

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
  fireEvent.click(await screen.findByRole("button", { name: "내 평가 삭제" }));
  await waitFor(() => expect(mocks.apiRequest).toHaveBeenCalledWith("/articles/article-1/vote", { method: "DELETE" }));
  expect(screen.getByText(/현재 독자 평가를 삭제/)).toBeVisible();
});

it("게스트의 선택적 투표 조회는 공개 기사 화면을 유지하고 로그인 CTA를 표시한다", async () => {
  mocks.apiRequest.mockImplementation(async () => unauthorized());

  renderVoteForm();

  const link = await screen.findByRole("link", { name: "로그인 후 평가하기" });
  expect(link).toHaveAttribute("href", "/login?returnTo=%2Farticles%2Farticle-1");
});

it("첫 지급은 서버의 실제 금액을 보여 주고 재저장은 수정 안내만 보여 준다", async () => {
  let saves = 0;
  mocks.apiRequest.mockImplementation(async (_path: string, init?: RequestInit) => {
    if ((init?.method ?? "GET") === "GET") notFound();
    saves += 1;
    return { revision: saves, save_status: saves === 1 ? "created" : "updated", credit_delta: saves === 1 ? 10 : 0 };
  });
  renderVoteForm();
  fireEvent.click(await screen.findByRole("button", { name: "독자 평가 저장" }));
  expect(await screen.findByText("크레딧 10이 지급되었습니다.")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "독자 평가 저장" }));
  expect(await screen.findByText("수정사항이 반영되었습니다.")).toBeVisible();
  expect(screen.queryByText("크레딧 10이 지급되었습니다.")).not.toBeInTheDocument();
});

it("지급 대상이 아닌 첫 평가는 크레딧 지급을 약속하지 않는다", async () => {
  mocks.apiRequest.mockImplementation(async (_path: string, init?: RequestInit) => {
    if ((init?.method ?? "GET") === "GET") notFound();
    return { revision: 1, save_status: "created", credit_delta: 0 };
  });
  renderVoteForm();
  fireEvent.click(await screen.findByRole("button", { name: "독자 평가 저장" }));
  expect(await screen.findByText("평가가 저장되었습니다. 이번 저장으로 추가 지급된 크레딧은 없습니다.")).toBeVisible();
});

it("소규모 집계로 표시된 응답에 수치가 남아 있어도 화면에는 노출하지 않는다", async () => {
  mocks.apiRequest.mockImplementation(async (path: string) => {
    if (path.endsWith("/vote")) notFound();
    return { status: "ready", qualified_count: 1, small_segments_suppressed: true, qualified: { x: 77, y: 42, z: 11, sensationalism: 69 } };
  });
  renderVoteForm();
  expect(await screen.findByText("공개 기준보다 참여자가 적어 점수를 표시하지 않습니다.")).toBeVisible();
  expect(screen.queryByText(/편향성.*77/)).not.toBeInTheDocument();
});
