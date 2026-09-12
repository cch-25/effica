import { describe, expect, it } from "vitest";
import { graphPosition } from "@/components/graphs/graph-model";
import { ideologyAxes, interpretIdeology } from "@/features/share-cards/ideology-model";

const result = (x: number, y: number, z = 0) => interpretIdeology({ completed: true, x, y, z });

describe("questionnaire ideology map", () => {
  it.each([
    [-80, -60, "권위주의 좌파 성향"], [80, -60, "권위주의 우파 성향"],
    [-80, 60, "자유주의 좌파 성향"], [80, 60, "자유주의 우파 성향"],
    [0, 0, "중도 성향"], [-10, 10, "중도 성향"], [10, -10, "중도 성향"],
    [-11, 0, "좌파 성향"], [11, 0, "우파 성향"],
    [0, -11, "권위주의 중도 성향"], [0, 11, "자유주의 중도 성향"],
  ])("interprets (%s, %s) as %s", (x, y, label) => {
    expect(result(Number(x), Number(y))?.label).toBe(label);
  });

  it("keeps internationalism independent of left/right and authority", () => {
    expect(result(-24, 37, -100)).toMatchObject({ label: "자유주의 좌파 성향", international: "주권주의" });
    expect(result(-24, 37, 100)).toMatchObject({ label: "자유주의 좌파 성향", international: "국제주의" });
    expect(result(-24, 37, 10)?.international).toBe("혼합");
  });

  it("places left on the left, authority above, liberty below and internationalism deeper", () => {
    expect(graphPosition([-100, -100, -100], ideologyAxes)).toEqual([-1.2, .825, .825]);
    expect(graphPosition([100, 100, 100], ideologyAxes)).toEqual([1.2, -.825, -.825]);
    expect(result(-24, 37, 12)?.values).toEqual([-24, 37, 12]);
  });

  it("does not call an unmeasured or invalid result centrist", () => {
    expect(interpretIdeology({ completed: false, x: 0, y: 0, z: 0 })).toBeNull();
    expect(result(NaN, 30)).toBeNull();
  });
});
