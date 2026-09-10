import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { IssueGrid } from "@/features/issues/issue-grid";
import { issues } from "@/mocks/fixtures/content";

const query = vi.hoisted(() => ({ useIssuesQuery: vi.fn() }));
vi.mock("@/lib/api/queries", () => query);
vi.mock("@/lib/api/mode", () => ({ isMockMode: () => false }));
afterEach(cleanup);

describe("home issues during limited analysis", () => {
  it("keeps partial events visible with an honest preparation status", () => {
    query.useIssuesQuery.mockReturnValue({ data: { items: [
      { ...issues[0], analysisStatus: "PARTIAL", freshnessStatus: "CURRENT" },
    ] } });
    render(<IssueGrid fallback={[]} featuredOnly />);
    expect(screen.getByText(issues[0].title)).toBeVisible();
    expect(screen.getByText("일부 분석 중")).toBeVisible();
    expect(screen.getByRole("link", { name: "준비 상태 보기 →" })).toBeVisible();
    expect(screen.queryByText("표시할 내용이 없습니다")).not.toBeInTheDocument();
    expect(screen.queryByText("비교 가능")).not.toBeInTheDocument();
  });

  it("preserves editorial priority and excludes stale events and topic buckets", () => {
    query.useIssuesQuery.mockReturnValue({ data: { items: [
      { ...issues[0], id: "partial", title: "준비 중인 사건", analysisStatus: "PARTIAL", editorialPriority: 2 },
      { ...issues[0], id: "topic", title: "주제 모음", kind: "TOPIC" },
      { ...issues[0], id: "stale", title: "지난 사건", freshnessStatus: "UPDATE_NEEDED" },
      { ...issues[0], id: "ready", title: "분석 완료 사건", analysisStatus: "READY" },
    ] } });
    render(<IssueGrid fallback={[]} featuredOnly />);
    expect(screen.getAllByRole("listitem")[0]).toHaveTextContent("분석 완료 사건");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("requires three publishers and caps the homepage at five curated events", () => {
    query.useIssuesQuery.mockReturnValue({ data: { items: [
      { ...issues[0], id: "two", title: "출처 부족", sourceCount: 2 },
      { ...issues[0], id: "few-articles", title: "기사 부족", articleIds: ["a", "b"] },
      { ...issues[0], id: "sports", title: "경기 결과", topic: "스포츠" },
      ...Array.from({ length: 6 }, (_, index) => ({ ...issues[0], id: `policy-${index}`, title: `정책 쟁점 ${index}`, editorialPriority: index + 1 })),
    ] } });
    render(<IssueGrid fallback={[]} featuredOnly />);
    expect(screen.getAllByRole("listitem")).toHaveLength(5);
    expect(screen.getAllByRole("listitem")[0]).toHaveTextContent("정책 쟁점 0");
    for (const title of ["출처 부족", "기사 부족", "경기 결과", "정책 쟁점 5"]) expect(screen.queryByText(title)).not.toBeInTheDocument();
  });
});
