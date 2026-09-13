export type AlgorithmMode = "fetch" | "evidence" | "weights" | "coordinates" | "ranking";
export type AlgorithmState = { mode: AlgorithmMode; step: number; model: number; x: number; s: number; c: number; diverse: boolean };
export const INITIAL_STATE: AlgorithmState = { mode: "fetch", step: 0, model: 30, x: 19, s: 35, c: 75, diverse: true };
export const SIGNALS = [
  { label: "모델", value: 30, weight: .60 },
  { label: "상대 프레임", value: -10, weight: .20 },
  { label: "독자 평가", value: 20, weight: .15 },
  { label: "출처 사전값", value: 0, weight: .05 },
];
export const ARTICLES = [
  { id: "A", source: "가", issue: "예산", c: .92, h: 2 },
  { id: "B", source: "가", issue: "교통", c: .86, h: 5 },
  { id: "C", source: "나", issue: "예산", c: .84, h: 4 },
  { id: "D", source: "다", issue: "주거", c: .82, h: 8 },
];
export function weightedScore(model: number) {
  const raw = model * .6 - 2 + 3;
  return Math.sign(raw) * Math.floor(Math.abs(raw) + .5);
}
// This explanatory cohort uses R=0, Q=C and the same adjacent-view bonus (.18)
// for every candidate. Source and issue counts are recomputed after each pick.
export function rankingExample(diverse: boolean) {
  const sourceCounts: Record<string, number> = {};
  const issueCounts: Record<string, number> = {};
  const score = (item: typeof ARTICLES[number]) => .14 * Math.exp(-item.h / 168) + .36 * item.c + .20 / (1 + (sourceCounts[item.source] ?? 0)) + .08 / (1 + (issueCounts[item.issue] ?? 0)) + .18;
  const initial = ARTICLES.map(item => ({ ...item, score: score(item) }));
  const pool = [...ARTICLES];
  const selected: typeof initial = [];
  while (pool.length) {
    const candidates = pool.filter(item => !diverse || (!issueCounts[item.issue] && selected.at(-1)?.source !== item.source));
    candidates.sort((a, b) => score(b) - score(a));
    const item = candidates[0];
    if (!item) break;
    selected.push({ ...item, score: score(item) });
    sourceCounts[item.source] = (sourceCounts[item.source] ?? 0) + 1;
    issueCounts[item.issue] = (issueCounts[item.issue] ?? 0) + 1;
    pool.splice(pool.indexOf(item), 1);
  }
  return { initial, selected, excluded: pool };
}
