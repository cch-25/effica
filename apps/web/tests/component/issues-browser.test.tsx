import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { IssuesBrowser } from "@/features/issues/issues-browser";
import { issues } from "@/mocks/fixtures/content";

vi.mock("@/lib/api/queries", () => ({ useIssuesQuery: () => ({ data: { items: issues } }) }));

afterEach(cleanup);

it("주제 필터를 열고 선택한 주제의 이슈만 표시한다", () => {
  render(<IssuesBrowser fallback={issues} />);

  const filterButton = screen.getByRole("button", { name: "주제·기간" });
  fireEvent.click(filterButton);
  fireEvent.click(screen.getByRole("checkbox", { name: "과학·기술" }));

  expect(screen.getByText("AI 기본법 시행 준비")).toBeVisible();
  expect(screen.queryByText("도심 주택 공급 대책")).not.toBeInTheDocument();
  expect(filterButton).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByRole("button", { name: "1개 이슈 보기" })).toBeVisible();
});
