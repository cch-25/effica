import { describe, expect, it } from "vitest";
import { clampScore, formatAxis, formatConfidence, validateScores } from "@/lib/api/formatters";

describe("coordinate formatters", () => {
  it("clamps coordinates to the documented range", () => { expect(clampScore(121)).toBe(100); expect(clampScore(-121)).toBe(-100); });
  it("describes direction without good or bad labels", () => { expect(formatAxis(-24, "x")).toBe("경제 평등·재분배 24"); expect(formatAxis(0, "z")).toContain("판단 불충분"); });
  it("formats bounded confidence", () => { expect(formatConfidence(.86)).toBe("높음 · 86%"); expect(formatConfidence(9)).toBe("높음 · 100%"); });
  it("validates all coordinate and confidence bounds", () => { expect(validateScores({ x: 0, y: -100, z: 100, sensationalism: 50, confidence: .5 })).toBe(true); expect(validateScores({ x: 101, y: 0, z: 0, sensationalism: 0, confidence: .5 })).toBe(false); });
});
