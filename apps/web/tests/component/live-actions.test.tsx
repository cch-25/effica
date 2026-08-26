import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ArticleDwellTracker } from "@/features/reading/article-dwell-tracker";
import { ShareCardStatus } from "@/features/share-cards/share-card-status";

const mocks = vi.hoisted(() => ({ apiRequest: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ apiRequest: mocks.apiRequest }));

afterEach(() => { cleanup(); vi.clearAllMocks(); });

it("기사 체류 기록은 별도 조작 UI 없이 페이지 이탈 시 자동 전송된다", async () => {
  mocks.apiRequest.mockImplementation((path: string) => path.includes("/read-sessions/session-1/return")
    ? Promise.resolve({ status: "eligible", reason_code: "ELIGIBLE", server_elapsed_ms: 20_000, credit_delta: 12 })
    : Promise.resolve({ read_session_id: "session-1", redirect_url: "/articles/article-1", expires_at: "2026-08-26T00:00:00Z" }));
  const { container } = render(<ArticleDwellTracker articleId="article-1" />);
  await waitFor(() => expect(mocks.apiRequest).toHaveBeenCalledWith("/articles/article-1/read-sessions", expect.objectContaining({ method: "POST", authFailureMode: "return-error" })));
  expect(container).toBeEmptyDOMElement();
  fireEvent(window, new PageTransitionEvent("pagehide"));
  await waitFor(() => expect(mocks.apiRequest).toHaveBeenCalledWith("/read-sessions/session-1/return", expect.objectContaining({
    method: "POST",
    keepalive: true,
    authFailureMode: "return-error",
  })));
});

it("공유 카드 폐기는 DELETE 성공 응답 뒤 실제 상태를 갱신한다", async () => {
  mocks.apiRequest.mockResolvedValue(undefined);
  render(<ShareCardStatus initialCard={{ id: "card-1", status: "ready", public_token: "token-1", snapshot: { x: 2 } }} />);
  fireEvent.click(screen.getByRole("button", { name: "즉시 폐기" }));
  await waitFor(() => expect(mocks.apiRequest).toHaveBeenCalledWith("/share-cards/card-1", { method: "DELETE" }));
  expect(screen.getByText("폐기됨")).toBeVisible();
});
