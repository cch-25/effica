import { describe, expect, it } from "vitest";
import { rankingExample, weightedScore } from "@/features/algo/algo-model";

describe("interactive algorithm examples", () => {
  it("adds actual weighted contributions and rounds both signs symmetrically", () => {
    expect(weightedScore(30)).toBe(19);
    expect(weightedScore(-100)).toBe(-59);
    expect(weightedScore(100)).toBe(61);
    expect(weightedScore(-7.5)).toBe(-4);
  });
  it("recalculates the next score while enforcing diversity constraints", () => {
    const result = rankingExample(true);
    expect(result.initial.map(item => item.id)).toEqual(["A", "B", "C", "D"]);
    expect(result.selected.map(item => item.id)).toEqual(["A", "D", "B"]);
    expect(result.excluded.map(item => item.id)).toEqual(["C"]);
    expect(result.selected[2].score).toBeLessThan(result.initial[1].score);
  });
  it("keeps repeat penalties when hard constraints are disabled", () => {
    expect(rankingExample(false).selected.map(item => item.id)).toEqual(["A", "D", "C", "B"]);
  });
  it("anchors the evidence example to its original character range", () => {
    const quote = "예산 부담은 남았지만 단기 효과가 기대된다.";
    const raw = `정부가 새로운 지원 대책을 발표했다. ${quote} 시행 범위는 추가 논의한다.`;
    expect(raw.indexOf(quote)).toBe(21);
    expect(raw.slice(21, 45)).toBe(quote);
  });
});
