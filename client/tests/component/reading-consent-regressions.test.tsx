import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ArticleDwellTracker } from "@/features/reading/article-dwell-tracker";
import { ConsentForm } from "@/features/onboarding/consent-form";

const mocks = vi.hoisted(() => ({ apiRequest: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ apiRequest: mocks.apiRequest }));
vi.mock("@/lib/api/mode", () => ({ isMockMode: () => false }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

afterEach(() => { cleanup(); vi.restoreAllMocks(); mocks.apiRequest.mockReset(); });

it("짧은 탭 이탈 후 돌아오면 새 세션에서 읽기를 기록한다", async () => {
  let elapsed = 0;
  let count = 0;
  vi.spyOn(performance, "now").mockImplementation(() => elapsed);
  const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  mocks.apiRequest.mockImplementation((path: string) => Promise.resolve(path.endsWith("/return")
    ? { status: "rejected", credit_delta: 0 }
    : { read_session_id: `session-${++count}`, redirect_url: "/articles/article-1" }));
  const view = render(<ArticleDwellTracker articleId="article-1" />);
  await waitFor(() => expect(count).toBe(1));
  elapsed = 5_000;
  visibility.mockReturnValue("hidden");
  fireEvent(document, new Event("visibilitychange"));
  await waitFor(() => expect(mocks.apiRequest).toHaveBeenCalledWith("/read-sessions/session-1/return",
    expect.objectContaining({ body: JSON.stringify({ client_elapsed_ms: 5_000 }) })));
  elapsed = 20_000;
  visibility.mockReturnValue("visible");
  fireEvent(document, new Event("visibilitychange"));
  await waitFor(() => expect(count).toBe(2));
  elapsed = 80_000;
  view.unmount();
  await waitFor(() => expect(mocks.apiRequest).toHaveBeenCalledWith("/read-sessions/session-2/return",
    expect.objectContaining({ body: JSON.stringify({ client_elapsed_ms: 60_000 }) })));
  expect(count).toBe(2);
});

it("세션 생성과 이탈 전송이 늦어져도 중복 세션을 만들지 않는다", async () => {
  let resolveCreate!: (value: unknown) => void;
  let resolveReturn!: (value: unknown) => void;
  const creation = new Promise((resolve) => { resolveCreate = resolve; });
  const returned = new Promise((resolve) => { resolveReturn = resolve; });
  const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  mocks.apiRequest.mockReturnValueOnce(creation).mockReturnValueOnce(returned)
    .mockResolvedValue({ read_session_id: "session-2", redirect_url: "/articles/article-1" });
  const view = render(<ArticleDwellTracker articleId="article-1" />);
  await waitFor(() => expect(mocks.apiRequest).toHaveBeenCalledTimes(1));
  visibility.mockReturnValue("hidden");
  fireEvent(document, new Event("visibilitychange"));
  visibility.mockReturnValue("visible");
  fireEvent(document, new Event("visibilitychange"));
  resolveCreate({ read_session_id: "session-1", redirect_url: "/articles/article-1" });
  await waitFor(() => expect(mocks.apiRequest).toHaveBeenCalledTimes(2));
  fireEvent(document, new Event("visibilitychange"));
  expect(mocks.apiRequest).toHaveBeenCalledTimes(2);
  resolveReturn({ status: "rejected" });
  await waitFor(() => expect(mocks.apiRequest).toHaveBeenCalledTimes(3));
  view.unmount();
  await waitFor(() => expect(mocks.apiRequest).toHaveBeenCalledTimes(4));
});

it("페이지 복원 시 읽기를 다시 시작하고 이탈 전송은 한 번만 한다", async () => {
  let count = 0;
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  mocks.apiRequest.mockImplementation((path: string) => Promise.resolve(path.endsWith("/return")
    ? { status: "eligible" }
    : { read_session_id: `session-${++count}`, redirect_url: "/articles/article-1" }));
  const view = render(<ArticleDwellTracker articleId="article-1" />);
  await waitFor(() => expect(count).toBe(1));
  fireEvent(window, new PageTransitionEvent("pagehide"));
  fireEvent(window, new PageTransitionEvent("pagehide"));
  await waitFor(() => expect(mocks.apiRequest).toHaveBeenCalledTimes(2));
  expect(count).toBe(1);
  fireEvent(window, new PageTransitionEvent("pageshow", { persisted: true }));
  await waitFor(() => expect(count).toBe(2));
  view.unmount();
  await waitFor(() => expect(mocks.apiRequest).toHaveBeenCalledTimes(4));
});

it.each(["SENSITIVE_POLITICAL", "POLITICAL_PROFILE"])("정치 민감정보 동의 목적 %s를 명시한다", async (purpose) => {
  mocks.apiRequest.mockResolvedValue([{ id: "political", purpose, sensitive: true, granted: false, version: "1.0" }]);
  render(<ConsentForm returnTo="/" />);
  expect(await screen.findByRole("checkbox", { name: /정치 민감정보/ })).toBeVisible();
  expect(screen.queryByText("[필수] 추가 정보 처리")).not.toBeInTheDocument();
});
