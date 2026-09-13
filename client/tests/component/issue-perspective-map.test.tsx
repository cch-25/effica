import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { IssuePerspectiveMap } from "@/features/issues/comparison/issue-perspective-map";
import { articles } from "@/mocks/fixtures/content";
import type { VisualizationPoint } from "@/lib/api/types";

vi.mock("@/features/visualization/perspective-field", () => ({
  PerspectiveField: ({ points }: { points: VisualizationPoint[] }) => <div data-testid="issue-map-points">{points.map((point) => point.id).join(",")}</div>,
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("compares the selected issue articles and links the active point to its detail page", () => {
  render(<IssuePerspectiveMap articles={articles.slice(0, 3)} />);

  const map = screen.getByRole("region", { name: "기사 비교 3D 지도" });
  expect(within(map).getByTestId("issue-map-points")).toHaveTextContent("article-01,article-02,article-03");
  const choices = within(map).getByRole("group", { name: "3D 그래프에서 비교할 기사" });
  expect(within(choices).getAllByRole("button")).toHaveLength(3);
  expect(within(choices).getAllByRole("button")[0]).toHaveAttribute("aria-pressed", "true");

  fireEvent.click(within(choices).getAllByRole("button")[1]);

  expect(within(choices).getAllByRole("button")[1]).toHaveAttribute("aria-pressed", "true");
  expect(within(map).getByRole("complementary", { name: "선택한 기사 관점" })).toHaveTextContent(articles[1].title);
  expect(within(map).getByRole("link", { name: "선택한 기사 상세 분석 보기" })).toHaveAttribute("href", `/articles/${articles[1].id}`);
});
