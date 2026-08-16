import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PerspectivePreview } from "@/features/share-cards/perspective-preview";
import { VisualizationExplorer } from "@/features/visualization/visualization-explorer";
import type { VisualizationPoint } from "@/lib/api/types";

const mocks = vi.hoisted(() => ({ useVisualizationPointsQuery: vi.fn() }));

vi.mock("@/lib/api/queries", () => ({ useVisualizationPointsQuery: mocks.useVisualizationPointsQuery }));

const point: VisualizationPoint = {
  id: "article-1",
  label: "한국어 기사",
  type: "article",
  x: -24,
  y: 81,
  z: -63,
  sensationalism: 37,
  confidence: 0.88,
  scoreVersion: "점수-1",
  observedAt: "2026-08-16T00:00:00Z",
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("두 기준 화면", () => {
  it("시각화에서 편향성과 과장성만 핵심 기준으로 안내한다", () => {
    mocks.useVisualizationPointsQuery.mockReturnValue({ data: { items: [point] } });

    render(<VisualizationExplorer />);

    expect(screen.getByRole("heading", { name: /두 기준으로 읽는/ })).toBeVisible();
    expect(screen.getAllByText("편향성").length).toBeGreaterThan(0);
    expect(screen.getAllByText("과장성").length).toBeGreaterThan(0);
    expect(screen.queryByText(/경제|사회문화|국가·대외/)).not.toBeInTheDocument();
    expect(screen.queryByText(/세 가지 핵심 값|3축/)).not.toBeInTheDocument();
  });

  it("공유 카드가 두 점수와 한국어 안내만 노출한다", () => {
    render(<PerspectivePreview displayName="김사이" />);

    expect(screen.getByRole("region", { name: "김사이의 편향성과 과장성" })).toBeVisible();
    expect(screen.getAllByText("편향성").length).toBeGreaterThan(0);
    expect(screen.getAllByText("과장성").length).toBeGreaterThan(0);
    expect(screen.queryByText(/경제|사회문화|국가·대외|MY PERSPECTIVE|confidence|tier/)).not.toBeInTheDocument();
  });
});
