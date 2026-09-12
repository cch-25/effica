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

  fireEvent.click(screen.getByRole("button", { name: "우편향" }));
  fireEvent.click(screen.getByRole("button", { name: "높음" }));
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

it("저장과 수정 결과를 안내한다", async () => {
  let saves = 0;
  mocks.apiRequest.mockImplementation(async (_path: string, init?: RequestInit) => {
    if ((init?.method ?? "GET") === "GET") notFound();
    saves += 1;
    return { revision: saves, save_status: saves === 1 ? "created" : "updated", credit_delta: saves === 1 ? 10 : 0 };
  });
  renderVoteForm();
  fireEvent.click(await screen.findByRole("button", { name: "독자 평가 저장" }));
  expect(await screen.findByText("평가가 저장되었습니다. 아래에서 AI 분석과 내 평가를 비교해 보세요.")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "독자 평가 저장" }));
  expect(await screen.findByText("수정사항이 반영되었습니다.")).toBeVisible();
  expect(screen.queryByText("평가가 저장되었습니다. 아래에서 AI 분석과 내 평가를 비교해 보세요.")).not.toBeInTheDocument();
});

it("지급 대상이 아닌 첫 평가는 크레딧 지급을 약속하지 않는다", async () => {
  mocks.apiRequest.mockImplementation(async (_path: string, init?: RequestInit) => {
    if ((init?.method ?? "GET") === "GET") notFound();
    return { revision: 1, save_status: "created", credit_delta: 0 };
  });
  renderVoteForm();
  fireEvent.click(await screen.findByRole("button", { name: "독자 평가 저장" }));
  expect(await screen.findByText("평가가 저장되었습니다. 아래에서 AI 분석과 내 평가를 비교해 보세요.")).toBeVisible();
});

it("소규모 집계로 표시된 응답에 수치가 남아 있어도 화면에는 노출하지 않는다", async () => {
  mocks.apiRequest.mockImplementation(async (path: string) => {
    if (path.endsWith("/vote")) notFound();
    return { status: "ready", qualified_count: 1, small_segments_suppressed: true, qualified: { x: 77, y: 42, z: 11, sensationalism: 69 } };
  });
  renderVoteForm();
  expect(await screen.findByText("독자 평균 공개까지 4명의 평가가 더 필요합니다.")).toBeVisible();
  expect(screen.queryByText(/편향성.*77/)).not.toBeInTheDocument();
});


it("재평가에는 응답 메타데이터를 보내지 않으며 저장된 값을 즉시 표시한다", async () => {
  const stored = { x: -33, y: 12, z: 8, sensationalism: 50, revision: 7, active: true, quality_status: "QUALIFIED", save_status: "updated", credit_delta: 0 };
  mocks.apiRequest.mockImplementation(async (path: string, init?: RequestInit) => {
    if (init?.method === "PUT") return { ...stored, ...JSON.parse(String(init.body)), revision: 8 };
    if (path.endsWith("/vote")) return stored;
    notFound();
  });
  renderVoteForm();
  fireEvent.click(await screen.findByRole("button", { name: "약간 우편향" }));
  fireEvent.click(screen.getByRole("button", { name: "독자 평가 저장" }));
  await waitFor(() => expect(mocks.apiRequest).toHaveBeenCalledWith("/articles/article-1/vote", { method: "PUT", body: JSON.stringify({ x: 33, y: 12, z: 8, sensationalism: 50 }) }));
  expect(await screen.findByText(/저장한 내 평가:.*33/)).toBeVisible();
});
