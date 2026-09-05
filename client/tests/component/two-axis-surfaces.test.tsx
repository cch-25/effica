import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PerspectivePreview } from "@/features/share-cards/perspective-preview";
import { VisualizationExplorer } from "@/features/visualization/visualization-explorer";
import type { VisualizationPoint } from "@/lib/api/types";

const mocks = vi.hoisted(() => ({ useVisualizationPointsQuery: vi.fn(), useViewerQuery: vi.fn() }));

vi.mock("@/lib/api/queries", () => ({ useVisualizationPointsQuery: mocks.useVisualizationPointsQuery, useViewerQuery: mocks.useViewerQuery }));

vi.mock("@/features/visualization/space-renderer", () => ({
  createSpace: vi.fn(() => { throw new Error("WebGL unavailable in this test environment"); }),
}));

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

describe("관점 분석 화면", () => {
  it("시각화에서 편향성과 과장성에 분석 신뢰도를 더한 3D 좌표를 안내한다", () => {
    mocks.useVisualizationPointsQuery.mockReturnValue({ data: { items: [point] } });
    mocks.useViewerQuery.mockReturnValue({ error: { status: 401 } });

    render(<VisualizationExplorer />);

    expect(screen.getByRole("heading", { name: /세 기준으로 읽는/ })).toBeVisible();
    expect(screen.getAllByText("편향성").length).toBeGreaterThan(0);
    expect(screen.getAllByText("과장성").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /편향성: 기사의 주장과 강조점/ })).toBeVisible();
    expect(screen.getByRole("button", { name: /분석 신뢰도: 현재 근거로/ })).toBeVisible();
    expect(screen.getByRole("button", { name: /평균 신뢰도: 현재 표시된 기사들의/ })).toBeVisible();
    expect(screen.queryByText(/경제|사회문화|국가.*대외/)).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: /깊이는 분석 신뢰도인 3D 그래프/ })).toBeVisible();
  });

  it("공유 카드가 실제 활동 스냅샷의 두 점수만 노출한다", () => {
    render(<PerspectivePreview displayName="김사이" snapshot={{ x: -24, sensationalism: 37, confidence: 0.88, tier: "탐색가", creditTotal: 42 }} />);

    expect(screen.getByRole("region", { name: "김사이의 편향성과 과장성" })).toBeVisible();
    expect(screen.getByText("현재 내 활동 기준 미리보기")).toBeVisible();
    expect(screen.getAllByText(/좌편향.*-24/)).toHaveLength(2);
    expect(screen.getAllByText("37/100")).toHaveLength(2);
    expect(screen.getAllByText("편향성").length).toBeGreaterThan(0);
    expect(screen.getAllByText("과장성").length).toBeGreaterThan(0);
    expect(screen.queryByText(/경제|사회문화|국가.*대외|MY PERSPECTIVE|confidence|tier|snapshot/)).not.toBeInTheDocument();
  });

  it("실제 결과가 없으면 0점 예시 대신 설문 안내를 표시한다", () => {
    render(<PerspectivePreview displayName="" snapshot={null} />);

    expect(screen.getByRole("region", { name: "공유 카드의 편향성과 과장성" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "표시할 관점 결과가 없습니다." })).toBeVisible();
    expect(screen.getAllByText("결과 없음")).toHaveLength(2);
    expect(screen.getByRole("link", { name: "관점 설문 먼저 완료하기" })).toHaveAttribute("href", "/onboarding/questionnaire?returnTo=%2Fshare%2Fnew");
    expect(screen.queryByText(/0\/100|중립 0|현재 계산 결과/)).not.toBeInTheDocument();
  });
});
