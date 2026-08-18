import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ReadActions } from "@/features/reading/read-actions";
import { ShareCardStatus } from "@/features/share-cards/share-card-status";

const mocks = vi.hoisted(() => ({ apiRequest: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ apiRequest: mocks.apiRequest }));

afterEach(() => { cleanup(); vi.clearAllMocks(); sessionStorage.clear(); });

it("읽기 복귀는 저장된 세션과 flat credit_delta 응답만 신뢰한다", async () => {
  sessionStorage.setItem("active-read-session:article-1", "session-1");
  mocks.apiRequest.mockResolvedValue({ status: "eligible", reason_code: "ELIGIBLE", server_elapsed_ms: 20_000, credit_delta: 12 });
  render(<ReadActions articleId="article-1" originalUrl="https://example.com/article" />);
  fireEvent.click(screen.getByRole("button", { name: "원문에서 돌아왔어요" }));
  await waitFor(() => expect(screen.getByText(/활동 크레딧 \+12/)).toBeVisible());
  expect(mocks.apiRequest).toHaveBeenCalledWith("/read-sessions/session-1/return", { method: "POST", body: JSON.stringify({ client_elapsed_ms: null }) });
});

it("읽기 세션이 없으면 query string과 무관하게 복귀 성공을 만들지 않는다", async () => {
  window.history.replaceState({}, "", "/articles/article-1?returned=1");
  render(<ReadActions articleId="article-1" originalUrl="https://example.com/article" />);
  fireEvent.click(screen.getByRole("button", { name: "원문에서 돌아왔어요" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("읽기 세션이 없습니다");
  expect(mocks.apiRequest).not.toHaveBeenCalled();
});

it("공유 카드 폐기는 DELETE 성공 응답 뒤 실제 상태를 갱신한다", async () => {
  mocks.apiRequest.mockResolvedValue(undefined);
  render(<ShareCardStatus initialCard={{ id: "card-1", status: "ready", public_token: "token-1", snapshot: { x: 2 } }} />);
  fireEvent.click(screen.getByRole("button", { name: "즉시 폐기" }));
  await waitFor(() => expect(mocks.apiRequest).toHaveBeenCalledWith("/share-cards/card-1", { method: "DELETE" }));
  expect(screen.getByText("폐기됨")).toBeVisible();
});
