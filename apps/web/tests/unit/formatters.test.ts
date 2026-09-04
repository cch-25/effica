import { describe, expect, it } from "vitest";
import { clampScore, decodeHtmlEntities, formatAxis, formatBiasScore, formatConfidence, formatSensationalismScore, formatTierLabel, getBiasLabel, validateScores } from "@/lib/api/formatters";

describe("coordinate formatters", () => {
  it("clamps coordinates to the documented range", () => { expect(clampScore(121)).toBe(100); expect(clampScore(-121)).toBe(-100); });
  it("describes the canonical bias direction", () => { expect(formatAxis(-24, "x")).toBe("편향성 좌편향 24"); expect(formatAxis(0, "x")).toContain("판단 불충분"); });
  it("formats bounded confidence", () => { expect(formatConfidence(.86)).toBe("높음 86%"); expect(formatConfidence(9)).toBe("높음 100%"); });
  it("labels x-axis bias with the same ±10 boundaries as perspective filters", () => {
    expect(getBiasLabel(-11)).toBe("좌편향");
    expect(getBiasLabel(-10)).toBe("중립적");
    expect(getBiasLabel(10)).toBe("중립적");
    expect(getBiasLabel(11)).toBe("우편향");
  });
  it("formats an explicit signed x score with its Korean bias label", () => {
    expect(formatBiasScore(-24)).toBe("좌편향 -24");
    expect(formatBiasScore(0)).toBe("중립적 0");
    expect(formatBiasScore(24)).toBe("우편향 +24");
  });
  it("translates activity tiers without exposing unknown internal values", () => {
    expect(formatTierLabel("Bridge Builder")).toBe("관점 연결자");
    expect(formatTierLabel("unexpected-tier")).toBe("미확인");
  });
  it("formats sensationalism on its canonical 0–100 scale", () => {
    expect(formatSensationalismScore(34)).toBe("34/100");
    expect(formatSensationalismScore(120)).toBe("100/100");
  });
  it("validates bias, sensationalism, and zeroed compatibility axes", () => { expect(validateScores({ x: 0, y: 0, z: 0, sensationalism: 50, confidence: .5 })).toBe(true); expect(validateScores({ x: 0, y: -100, z: 100, sensationalism: 50, confidence: .5 })).toBe(false); expect(validateScores({ x: 101, y: 0, z: 0, sensationalism: 0, confidence: .5 })).toBe(false); });
  it("decodes repeated named and numeric HTML entities in display text", () => {
    expect(decodeHtmlEntities("&amp;#039;인용&amp;#039; &amp;middot; 안내 &#x2026;")).toBe("'인용' · 안내 …");
    expect(decodeHtmlEntities("알 수 없는 &not-a-real-entity;")).toBe("알 수 없는 &not-a-real-entity;");
  });
});
