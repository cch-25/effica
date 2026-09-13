import { describe, expect, it } from "vitest";
import { AUTO_INTERVAL_MS, SLIDER_TRANSITION_MS, INITIAL_STATE, advanceAlgorithm, interpolateAlgorithm, rankingExample, weightedScore } from "@/features/algo/algo-model";

describe("interactive algorithm examples", () => {
  it("smoothly interpolates slider inputs without changing the target or exceeding its bounds", () => {
    const from = { ...INITIAL_STATE, mode: "weights" as const };
    const to = advanceAlgorithm(from);
    expect(SLIDER_TRANSITION_MS).toBeLessThan(AUTO_INTERVAL_MS);
    expect(interpolateAlgorithm(from, to, 0).model).toBe(30);
    expect(interpolateAlgorithm(from, to, .5).model).toBe(53);
    expect(interpolateAlgorithm(from, to, 1)).toEqual(to);
    expect(interpolateAlgorithm(from, to, 2)).toEqual(to);
    const values = Array.from({ length: 21 }, (_, i) => interpolateAlgorithm(from, to, i / 20).model);
    expect(values).toEqual([...values].sort((a, b) => a - b));
  });
  it("interpolates all three coordinates with the same easing", () => {
    const from = { ...INITIAL_STATE, mode: "coordinates" as const };
    const to = advanceAlgorithm(from);
    const middle = interpolateAlgorithm(from, to, .5);
    expect([middle.x, middle.s, middle.c]).toEqual([-23, 30, 83]);
    expect(interpolateAlgorithm(from, to, 1)).toEqual(to);
  });
  it("automatically advances every type of scene and loops collection", () => {
    expect(AUTO_INTERVAL_MS).toBe(1500);
    let fetch = INITIAL_STATE;
    for (let i = 0; i < 4; i++) fetch = advanceAlgorithm(fetch);
    expect(fetch.step).toBe(0);
    expect(advanceAlgorithm({ ...INITIAL_STATE, mode: "evidence", step: 2 }).step).toBe(0);
    expect(advanceAlgorithm({ ...INITIAL_STATE, mode: "weights" }).model).toBe(76);
    expect(advanceAlgorithm({ ...INITIAL_STATE, mode: "coordinates" }).x).toBe(-65);
    expect(advanceAlgorithm({ ...INITIAL_STATE, mode: "ranking" }).diverse).toBe(false);
  });
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
