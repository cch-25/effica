import { describe, expect, it } from "vitest";
import { GRAPH_BOUNDS, getGraphCoordinates } from "@/features/visualization/perspective-field";
import { perspectiveDistance } from "@/features/visualization/visualization-explorer";
import type { VisualizationPoint } from "@/lib/api/types";

const point = (x: number, sensationalism: number, type: VisualizationPoint["type"] = "article"): VisualizationPoint => ({
  id: `${type}-${x}-${sensationalism}`,
  label: "좌표 검증",
  type,
  x,
  y: 0,
  z: 0,
  sensationalism,
  confidence: 1,
  scoreVersion: "test",
  observedAt: "",
});

describe("perspective field coordinate mapping", () => {
  it("maps the canonical bias and sensationalism endpoints to the chart bounds", () => {
    expect(getGraphCoordinates(point(-100, 100))).toEqual({ x: GRAPH_BOUNDS.left, y: GRAPH_BOUNDS.top });
    expect(getGraphCoordinates(point(100, 0))).toEqual({ x: GRAPH_BOUNDS.right, y: GRAPH_BOUNDS.bottom });
  });

  it("moves every article point proportionally to its actual axis values", () => {
    const neutral = getGraphCoordinates(point(0, 0));
    const measured = getGraphCoordinates(point(50, 25));
    expect(measured.x - neutral.x).toBe((GRAPH_BOUNDS.right - GRAPH_BOUNDS.left) / 4);
    expect(neutral.y - measured.y).toBe((GRAPH_BOUNDS.bottom - GRAPH_BOUNDS.top) / 4);
  });

  it("keeps a user profile on the bias baseline because article sensationalism does not apply", () => {
    expect(getGraphCoordinates(point(-25, 80, "user")).y).toBe(GRAPH_BOUNDS.bottom);
  });

  it("compares an article to a user by the shared bias axis only", () => {
    expect(perspectiveDistance(point(38, 100), point(4, 0, "user"))).toBe(34);
  });
});
