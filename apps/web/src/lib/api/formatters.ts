import type { AxisScores } from "./types";

export const AXIS_META = {
  x: { short: "경제", negative: "평등·재분배", positive: "시장·경쟁" },
  y: { short: "사회문화", negative: "질서·전통", positive: "자유·다양성" },
  z: { short: "국가·대외", negative: "국제협력", positive: "국가·안보" },
} as const;

export function clampScore(value: number, min = -100, max = 100): number {
  return Math.min(max, Math.max(min, Math.round(value)));
}

export function formatAxis(value: number, axis: keyof typeof AXIS_META): string {
  const score = clampScore(value);
  if (score === 0) return `${AXIS_META[axis].short} 중앙·판단 불충분 0`;
  const direction = score < 0 ? AXIS_META[axis].negative : AXIS_META[axis].positive;
  return `${AXIS_META[axis].short} ${direction} ${Math.abs(score)}`;
}

export function formatConfidence(value: number): string {
  const bounded = Math.min(1, Math.max(0, value));
  const label = bounded >= 0.8 ? "높음" : bounded >= 0.6 ? "보통" : "낮음";
  return `${label} · ${Math.round(bounded * 100)}%`;
}

export function validateScores(scores: AxisScores): boolean {
  return [scores.x, scores.y, scores.z].every((value) => Number.isInteger(value) && value >= -100 && value <= 100)
    && Number.isInteger(scores.sensationalism)
    && scores.sensationalism >= 0
    && scores.sensationalism <= 100
    && scores.confidence >= 0
    && scores.confidence <= 1;
}
