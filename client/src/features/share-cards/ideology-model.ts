import type { GraphAxes, GraphRegion } from "@/components/graphs/graph-model";
import type { Ideology } from "./consumption";

// Stored questionnaire coordinates remain x=economy, y=civil liberty, z=internationalism.
// Only the vertical ruler is reversed so authority appears above liberty.
export const ideologyAxes: GraphAxes = [
  { label: "좌우 성향", min: -100, max: 100, low: "좌파", high: "우파", showPoles: true },
  { label: "권위 / 자유", min: -100, max: 100, low: "권위주의", high: "자유주의", reversed: true, showPoles: true },
  { label: "국제관", min: -100, max: 100, low: "주권주의", high: "국제주의", showPoles: true },
];

export const ideologyRegions: GraphRegion[] = [
  { label: "권위주의 좌파", values: [-52, -62, 0] },
  { label: "권위주의 우파", values: [52, -62, 0] },
  { label: "자유주의 좌파", values: [-52, 62, 0] },
  { label: "자유주의 우파", values: [52, 62, 0] },
];

export const IDEOLOGY_CENTER_BAND = 10;
const band = (value: number, negative: string, neutral: string, positive: string) => value < -IDEOLOGY_CENTER_BAND ? negative : value > IDEOLOGY_CENTER_BAND ? positive : neutral;

export type IdeologyHighlightTone = "default" | "left" | "right";

export function ideologyHighlightTone(ideology: Ideology | null | undefined): IdeologyHighlightTone {
  if (!ideology) return "default";
  const economic = interpretIdeology(ideology)?.economic;
  return economic === "좌파" ? "left" : economic === "우파" ? "right" : "default";
}

export function interpretIdeology(ideology: Ideology) {
  if (!ideology.completed || ![ideology.x, ideology.y, ideology.z].every(Number.isFinite)) return null;
  const [x, y, z] = [ideology.x, ideology.y, ideology.z].map(value => Math.round(Math.max(-100, Math.min(100, value))));
  const economic = band(x, "좌파", "중도", "우파");
  const authority = band(y, "권위주의", "혼합", "자유주의");
  const international = band(z, "주권주의", "혼합", "국제주의");
  return {
    values: [x, y, z] as [number, number, number],
    economic, authority, international,
    label: `${authority === "혼합" ? "" : `${authority} `}${economic} 성향`,
  };
}
