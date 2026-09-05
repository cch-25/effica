import { describe, expect, it } from "vitest";
import { getSpaceCoordinates, histogram, makeSpaceData } from "@/features/visualization/field-model";
import { perspectiveDistance } from "@/features/visualization/visualization-explorer";
import type { VisualizationPoint } from "@/lib/api/types";

const point = (x: number, sensationalism: number | null, type: VisualizationPoint["type"] = "article"): VisualizationPoint => ({
  id: `${type}-${x}-${sensationalism}`, label: "좌표 검증", type, x, y: 0, z: 0,
  sensationalism, confidence: .87, scoreVersion: "test", observedAt: "",
});

describe("3D perspective coordinates", () => {
  it("uses actual bias, confidence and sensationalism rather than retired y/z dimensions", () => {
    expect(getSpaceCoordinates({ ...point(-24, 37), y: 91, z: -83 })).toEqual([-24, 87, 37]);
    expect(getSpaceCoordinates(point(100, 100))).toEqual([100, 87, 100]);
  });
  it("does not invent a sensationalism coordinate for users or unmeasured articles", () => {
    expect(getSpaceCoordinates(point(0, 20, "user"))).toBeNull();
    expect(getSpaceCoordinates(point(0, null))).toBeNull();
  });
  it("keeps all coincident articles selectable at their exact coordinates", () => {
    const points = Array.from({ length: 20 }, (_, index) => ({ ...point(0, 5), id: `article-${index}` }));
    const groups = makeSpaceData(points);
    expect(groups).toHaveLength(1);
    expect(groups[0].ids).toEqual(points.map((item) => item.id));
    expect(groups[0].value).toEqual([0, 87, 5]);
  });
  it("keeps points with different confidence distinct in depth", () => {
    expect(makeSpaceData([point(0, 5), { ...point(0, 5), id: "different-confidence", confidence: .92 }])).toHaveLength(2);
  });
  it("compares an article to a user only by their shared bias axis", () => {
    expect(perspectiveDistance(point(38, 100), point(4, 0, "user"))).toBe(34);
  });
  it("includes both endpoint values in histograms without dropping measurements", () => {
    const bins = histogram([0, 0, 25, 75, 100, NaN], 0, 100);
    expect(bins[0]).toBe(2);
    expect(bins[9]).toBe(1);
    expect(bins.reduce((sum, value) => sum + value, 0)).toBe(5);
  });
});
