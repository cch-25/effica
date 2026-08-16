import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { VoteForm } from "@/features/voting/vote-form";

const mocks = vi.hoisted(() => ({ apiRequest: vi.fn() }));

vi.mock("@/lib/api/client", () => ({ apiRequest: mocks.apiRequest }));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("7단계 편향성·과장성 선택을 숨은 y/z 중앙값과 함께 제출한다", async () => {
  mocks.apiRequest.mockResolvedValue({});
  render(<VoteForm articleId="article-1" />);

  expect(screen.getAllByRole("button", { name: /좌편향|중립|우편향/ })).toHaveLength(7);
  expect(screen.getAllByRole("button", { name: /낮음|보통|높음/ })).toHaveLength(7);

  fireEvent.click(screen.getByRole("button", { name: "우편향 +67" }));
  fireEvent.click(screen.getByRole("button", { name: "높음 +83" }));
  fireEvent.click(screen.getByRole("button", { name: "투표 저장·수정" }));

  await waitFor(() => expect(mocks.apiRequest).toHaveBeenCalledWith("/articles/article-1/vote", {
    method: "PUT",
    body: JSON.stringify({ x: 67, y: 0, z: 0, sensationalism: 83 }),
  }));
});
