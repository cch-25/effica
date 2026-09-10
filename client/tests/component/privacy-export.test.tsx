import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { PrivacyActions } from "@/features/auth/privacy-actions";

const mocks = vi.hoisted(() => ({ apiRequest: vi.fn() }));
vi.mock("@/lib/api/client", async () => ({ ...await vi.importActual("@/lib/api/client"), apiRequest: mocks.apiRequest }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><PrivacyActions /></QueryClientProvider>);
}

it("페이지를 다시 열어도 완료된 파일을 내려받을 수 있다", async () => {
  mocks.apiRequest.mockImplementation(async (path: string) => path === "/consents" ? [] : {
    job_id: "private-job", status: "SUCCEEDED", download_ready: true,
    download_url: "/api/v1/me/export/private-job/download", expires_at: "2026-09-17T00:00:00Z", failure_code: null,
  });
  show();
  expect(await screen.findByRole("link", { name: "내 데이터 다운로드" })).toHaveAttribute("href", "/api/v1/me/export/private-job/download");
  expect(screen.queryByText(/private-job/)).not.toBeInTheDocument();
});

it("실패한 재요청에 완료 알림이나 내부 작업 상태를 표시하지 않는다", async () => {
  mocks.apiRequest.mockImplementation(async (path: string) => path === "/consents" ? [] : {
    job_id: "private-job", status: "DEAD", download_ready: false, download_url: null, expires_at: null, failure_code: "EXPORT_FAILED",
  });
  show();
  fireEvent.click(await screen.findByRole("button", { name: "새 파일 요청" }));
  expect((await screen.findAllByText("내 데이터 파일을 준비하지 못했습니다. 다시 요청해 주세요.")).length).toBeGreaterThan(0);
  expect(screen.queryByText("완료")).not.toBeInTheDocument();
  expect(screen.queryByText(/DEAD|private-job/)).not.toBeInTheDocument();
});

it("진행 중인 요청을 복구하면 중복 요청을 막고 준비 상태를 알려 준다", async () => {
  mocks.apiRequest.mockImplementation(async (path: string) => path === "/consents" ? [] : {
    job_id: "private-job", status: "LEASED", download_ready: false, download_url: null, expires_at: null, failure_code: null,
  });
  show();
  expect(await screen.findByRole("button", { name: "파일 준비 중" })).toBeDisabled();
  expect(screen.getByText(/완료되면 이 화면에 다운로드 버튼/)).toBeVisible();
});
