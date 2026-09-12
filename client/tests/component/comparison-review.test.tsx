import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ComparisonReview } from "@/features/admin/comparison-review";
import { ApiError } from "@/lib/api/client";

const mocks = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("@/lib/api/client", async () => ({
  ...await vi.importActual<typeof import("@/lib/api/client")>("@/lib/api/client"),
  apiRequest: mocks.request,
}));
vi.mock("@/lib/api/queries", () => ({ useIssueArticlesQuery: () => ({ data: { items: [] } }) }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

const preview = {
  snapshot_id: "snapshot-1", status: "SUCCEEDED", reviewed_at: null, confidence: .8,
  common_facts: [{ id: "fact-1", text: "두 기사에서 확인한 사실", article_ids: [] }],
  dimensions: [], article_frames: {},
};

async function openReview() {
  const cache = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={cache}><ComparisonReview issueId="issue-1" title="보도 비교 검토" canApprove /></QueryClientProvider>);
  fireEvent.click(screen.getByRole("button", { name: "비교 분석 검토" }));
  await screen.findByLabelText("검토 및 승인 사유");
}

it("submits explicit exclusions and the exact reviewed snapshot before showing publication success", async () => {
  let approved = false;
  mocks.request.mockImplementation(async (_path: string, init?: RequestInit) => {
    if (init?.method === "POST") { approved = true; return {}; }
    return { ...preview, reviewed_at: approved ? "2026-09-12T00:00:00Z" : null };
  });
  await openReview();
  const submit = screen.getByRole("button", { name: "검토 완료 및 공개 승인" });
  expect(submit).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox", { name: "이 항목은 공개에서 제외" }));
  fireEvent.change(screen.getByLabelText("검토 및 승인 사유"), { target: { value: "원문에서 공통 근거를 확인하지 못했습니다." } });
  fireEvent.click(submit);
  await screen.findByText("비교 분석을 공개했습니다.");
  const [, init] = mocks.request.mock.calls.find(([, init]) => init?.method === "POST")!;
  expect(init.headers["If-Match"]).toBe("snapshot-1");
  expect(init.headers["Idempotency-Key"]).toBeTruthy();
  expect(JSON.parse(init.body)).toEqual({ reason: "원문에서 공통 근거를 확인하지 못했습니다.", excluded_fact_ids: ["fact-1"] });
});

it("requires a fresh review after a version conflict", async () => {
  mocks.request.mockImplementation(async (_path: string, init?: RequestInit) => {
    if (init?.method === "POST") throw new ApiError(409, { error: { code: "VERSION_CONFLICT", message: "changed", request_id: "test", retryable: false, details: {} } }, null);
    return preview;
  });
  await openReview();
  fireEvent.change(screen.getByLabelText("검토 및 승인 사유"), { target: { value: "검토했습니다." } });
  fireEvent.click(screen.getByRole("button", { name: "검토 완료 및 공개 승인" }));
  await screen.findByText("검토 중 분석이 변경되었습니다. 최신 내용을 다시 확인해 주세요.");
  expect(screen.getByRole("button", { name: "검토 완료 및 공개 승인" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "최신 분석 다시 검토" }));
  await waitFor(() => expect(screen.getByLabelText("검토 및 승인 사유")).toHaveValue(""));
  expect(screen.queryByText("비교 분석을 공개했습니다.")).not.toBeInTheDocument();
});
