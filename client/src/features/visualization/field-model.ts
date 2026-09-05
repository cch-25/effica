import type { VisualizationPoint } from "@/lib/api/types";

export type FieldView = "article" | "source";
export type SpaceDatum = {
  name: string;
  value: [number, number, number];
  ids: string[];
  points: VisualizationPoint[];
};

export const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));
export const signed = (value: number) => `${value > 0 ? "+" : ""}${Math.round(value)}`;

// ECharts uses x/y as the floor and z as height. Confidence is a real measured
// value, not the retired API y/z fields or an artificial offset to spread points.
export function getSpaceCoordinates(point: VisualizationPoint): [number, number, number] | null {
  if (point.type === "user" || point.sensationalism === null || !Number.isFinite(point.confidence)) return null;
  return [clamp(point.x, -100, 100), clamp(point.confidence * 100, 0, 100), clamp(point.sensationalism, 0, 100)];
}

export function makeSpaceData(points: VisualizationPoint[]): SpaceDatum[] {
  const groups = new Map<string, SpaceDatum>();
  for (const point of points) {
    const value = getSpaceCoordinates(point);
    if (!value) continue;
    const key = value.join(":");
    const group = groups.get(key);
    if (group) {
      group.ids.push(point.id);
      group.points.push(point);
    } else {
      groups.set(key, { name: point.label, value, ids: [point.id], points: [point] });
    }
  }
  return [...groups.values()];
}

export function histogram(values: number[], min: number, max: number, count = 10) {
  const bins = Array<number>(count).fill(0);
  values.filter(Number.isFinite).forEach((value) => {
    bins[Math.min(count - 1, Math.floor((clamp(value, min, max) - min) / (max - min) * count))] += 1;
  });
  return bins;
}
