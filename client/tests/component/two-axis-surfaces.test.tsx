import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PerspectivePreview } from "@/features/share-cards/perspective-preview";
import { ArticlePerspectiveMap } from "@/features/articles/article-perspective-map";
import { articles } from "@/mocks/fixtures/content";

const mocks = vi.hoisted(() => ({ useIssueArticlesQuery: vi.fn() }));

vi.mock("@/lib/api/queries", () => ({ useIssueArticlesQuery: mocks.useIssueArticlesQuery }));

vi.mock("@/components/graphs/three-scene", () => ({
  createGraphScene: vi.fn(() => { throw new Error("WebGL unavailable in this test environment"); }),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("관점 분석 화면", () => {
  it("시각화에서 편향성과 과장성에 분석 신뢰도를 더한 3D 좌표를 안내한다", () => {
    mocks.useIssueArticlesQuery.mockReturnValue({ data: { items: articles }, isSuccess: true });

    render(<ArticlePerspectiveMap article={articles[0]} />);

    expect(screen.getByRole("heading", { name: "기사 관점 지도" })).toBeVisible();
    expect(screen.getAllByText("편향성").length).toBeGreaterThan(0);
    expect(screen.getAllByText("과장성").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /편향성: 기사의 주장과 강조점/ })).toBeVisible();
    expect(screen.getByRole("button", { name: /분석 신뢰도: 현재 근거로/ })).toBeVisible();
    expect(screen.queryByText(/경제|사회문화|국가.*대외/)).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: /깊이는 분석 신뢰도인 3D 그래프/ })).toBeVisible();
  });

  it("공유 카드가 기사 소비 다양성과 별도 검사 좌표를 분리한다", () => {
    render(<PerspectivePreview displayName="김사이" snapshot={{ diversity_score: 68, diversity_article_count: 12, ideology: { completed: true, x: -24, y: 37, z: 12 } }} />);

    expect(screen.getByRole("region", { name: "김사이의 뉴스 소비 성향" })).toBeVisible();
    expect(screen.getByText("현재 내 활동 기준 미리보기")).toBeVisible();
    expect(screen.getByText("68/100")).toBeVisible();
    expect(screen.getByRole("img", { name: "검사 결과: 경제 -24, 사회문화 37, 국제 12" })).toBeVisible();
    expect(screen.queryByText("과장성")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "정치 이념 검사 다시 하기" })).toHaveAttribute("target", "_blank");
  });

  it("기록 조회 실패를 검사 미실시나 0점으로 대체하지 않는다", () => {
    render(<PerspectivePreview displayName="" snapshot={null} />);

    expect(screen.getByRole("status")).toHaveTextContent("뉴스 소비 기록을 확인하지 못했습니다.");
    expect(screen.queryByText(/0\/100/)).not.toBeInTheDocument();
  });

  it("미실시 검사는 기본 원점과 미측정 설명을 함께 표시한다", () => {
    render(<PerspectivePreview displayName="" snapshot={{ diversity_score: 0, diversity_article_count: 0, ideology: { completed: false, x: 99, y: 99, z: 99 } }} />);
    expect(screen.getByRole("img", { name: /검사 미실시: 기본 좌표/ })).toBeVisible();
    expect(screen.getByText(/아직 측정하지 않은 상태이며 중도를 뜻하지 않습니다/)).toBeVisible();
    expect(screen.getByRole("link", { name: "정치 이념 검사 하러 가기" })).toHaveAttribute("href", "/onboarding/questionnaire?returnTo=%2Fshare%2Fnew");
  });
});
