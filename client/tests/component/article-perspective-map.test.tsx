import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ArticlePerspectiveMap } from "@/features/articles/article-perspective-map";
import { articles } from "@/mocks/fixtures/content";
import type { VisualizationPoint } from "@/lib/api/types";

const query = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/queries", () => ({ useIssueArticlesQuery: query }));
vi.mock("@/features/visualization/perspective-field", () => ({
  PerspectiveField: ({ points }: { points: VisualizationPoint[] }) => <div data-testid="map-points">{points.map((point) => point.id).join(",")}</div>,
}));

beforeEach(() => query.mockReturnValue({ data: { items: articles }, isSuccess: true }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

it("starts at the article being read and only compares ready articles in its issue", () => {
  query.mockReturnValue({ data: { items: [...articles, { ...articles[0], id: "pending", analysisStatus: "PROCESSING" }] }, isSuccess: true });
  render(<ArticlePerspectiveMap article={articles[1]} />);
  expect(screen.getByTestId("map-points")).toHaveTextContent("article-02,article-01");
  const choices = within(screen.getByRole("group", { name: "같은 이슈에서 비교할 기사" }));
  expect(choices.getAllByRole("button")).toHaveLength(3);
  expect(choices.getAllByRole("button")[0]).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(choices.getAllByRole("button")[1]);
  expect(screen.getByRole("link", { name: "이 기사 분석 보기" })).toHaveAttribute("href", "/articles/article-01#perspective-map");
  fireEvent.click(screen.getByRole("button", { name: "읽고 있는 기사로 돌아가기" }));
  expect(choices.getAllByRole("button")[0]).toHaveAttribute("aria-pressed", "true");
});

it("retains the current article when related articles fail to load and offers retry", () => {
  const refetch = vi.fn();
  query.mockReturnValue({ isError: true, refetch });
  render(<ArticlePerspectiveMap article={articles[0]} />);
  expect(screen.getByTestId("map-points")).toHaveTextContent(/^article-01$/);
  expect(screen.getByRole("status")).toHaveTextContent("다른 보도를 새로 불러오지 못했습니다.");
  fireEvent.click(screen.getByRole("button", { name: "다시 불러오기" }));
  expect(refetch).toHaveBeenCalledOnce();
});

it.each(["PROCESSING", "PARTIAL", "UNTRUSTED"] as const)("does not plot the current article when its analysis is %s", (analysisStatus) => {
  render(<ArticlePerspectiveMap article={{ ...articles[0], analysisStatus }} />);
  expect(query).toHaveBeenCalledWith("issue-housing", false);
  expect(screen.queryByTestId("map-points")).not.toBeInTheDocument();
  expect(screen.getByRole("status")).toBeVisible();
});

it("does not group unrelated unclustered articles together", () => {
  query.mockReturnValue({ data: { items: [{ ...articles[1], issueId: "unclustered" }] }, isSuccess: true });
  render(<ArticlePerspectiveMap article={{ ...articles[0], issueId: "unclustered" }} />);
  expect(query).toHaveBeenCalledWith("unclustered", false);
  expect(screen.getByTestId("map-points")).toHaveTextContent(/^article-01$/);
  expect(screen.getByText(/이 기사만 표시합니다/)).toBeVisible();
});

it("keeps a missing sensationalism measurement explicit", () => {
  render(<ArticlePerspectiveMap article={{ ...articles[0], sensationalism: null }} />);
  expect(screen.getByText("과장성 측정값이 없어 이 기사는 지도에 점으로 표시하지 않습니다.")).toBeVisible();
  expect(screen.getByText("미측정")).toBeVisible();
});
