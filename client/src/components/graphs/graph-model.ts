export type GraphAxis = { label: string; min: number; max: number; suffix?: string; low: string; high: string };
// World order: horizontal, vertical, depth. Domain coordinates stay in the data.
export type GraphAxes = readonly [GraphAxis, GraphAxis, GraphAxis];
export type GraphPoint = { id: string; ids: string[]; label: string; values: [number, number, number] };
export type GraphView = "space" | "front" | "top";

export function graphPosition(values: readonly number[], axes: GraphAxes): [number, number, number] {
  return axes.map((axis, index) => {
    const ratio = (Math.min(axis.max, Math.max(axis.min, values[index])) - axis.min) / (axis.max - axis.min);
    return (ratio - .5) * (index === 0 ? 2.4 : 1.65) * (index === 2 ? -1 : 1);
  }) as [number, number, number];
}

export function graphValue(value: number, axis: GraphAxis) {
  return `${axis.min < 0 && value > 0 ? "+" : ""}${Math.round(value)}${axis.suffix ?? ""}`;
}
