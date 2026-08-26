import type { AxisScores } from "./types";

const HTML_ENTITIES: Readonly<Record<string, string>> = {
  amp: "&",
  apos: "'",
  gt: ">",
  hellip: "…",
  laquo: "«",
  ldquo: "“",
  lsquo: "‘",
  lt: "<",
  mdash: "—",
  middot: "·",
  nbsp: "\u00a0",
  ndash: "–",
  quot: '"',
  raquo: "»",
  rdquo: "”",
  rsquo: "’",
};

function decodeHtmlEntitiesOnce(value: string): string {
  return value.replace(/&(#x[\da-f]+|#\d+|[a-z][\da-z]+);/gi, (match, entity: string) => {
    if (entity[0] !== "#") return HTML_ENTITIES[entity.toLowerCase()] ?? match;
    const hexadecimal = entity[1]?.toLowerCase() === "x";
    const codePoint = Number.parseInt(entity.slice(hexadecimal ? 2 : 1), hexadecimal ? 16 : 10);
    if (!Number.isInteger(codePoint) || codePoint < 0 || codePoint > 0x10ffff) return match;
    try {
      return String.fromCodePoint(codePoint);
    } catch {
      return match;
    }
  });
}

export function decodeHtmlEntities(value: string): string {
  let decoded = value;
  for (let pass = 0; pass < 3; pass += 1) {
    const next = decodeHtmlEntitiesOnce(decoded);
    if (next === decoded) break;
    decoded = next;
  }
  return decoded;
}

export const AXIS_META = {
  x: { short: "편향성", negative: "좌편향", positive: "우편향" },
} as const;

export type BiasLabel = "좌편향" | "중립적" | "우편향";
export const BIAS_CENTER_THRESHOLD = 10;

export function getBiasLabel(value: number): BiasLabel {
  const score = clampScore(value);
  if (score < -BIAS_CENTER_THRESHOLD) return "좌편향";
  if (score > BIAS_CENTER_THRESHOLD) return "우편향";
  return "중립적";
}

export function formatBiasScore(value: number): string {
  const score = clampScore(value);
  return `${getBiasLabel(score)} · ${score > 0 ? `+${score}` : score}`;
}

export function formatSensationalismScore(value: number | null): string {
  if (value === null) return "미측정";
  return `${clampScore(value, 0, 100)}/100`;
}

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

export function formatPublishedDate(value: string): string {
  if (!value) return "게시일 미확인";
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "게시일 미확인";
  return new Intl.DateTimeFormat("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone: "Asia/Seoul",
  }).format(date);
}

export function formatDataAsOf(value: string): string {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "데이터 기준일 확인 중";
  return `데이터 기준 ${new Intl.DateTimeFormat("ko-KR", {
    month: "long",
    day: "numeric",
    timeZone: "Asia/Seoul",
  }).format(date)}`;
}

export function validateScores(scores: AxisScores): boolean {
  return Number.isInteger(scores.x)
    && scores.x >= -100
    && scores.x <= 100
    && scores.y === 0
    && scores.z === 0
    && Number.isInteger(scores.sensationalism)
    && scores.sensationalism >= 0
    && scores.sensationalism <= 100
    && scores.confidence >= 0
    && scores.confidence <= 1;
}
