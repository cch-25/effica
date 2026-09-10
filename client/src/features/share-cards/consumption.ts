export type Ideology = {
  completed: boolean;
  x: number;
  y: number;
  z: number;
  questionnaire_version?: string | null;
  questionnaire_status?: string;
};

export type ConsumptionSnapshot = {
  diversity_score: number;
  diversity_article_count: number;
  ideology: Ideology;
  tier?: string;
  credit_total?: number;
};

export function consumptionSnapshot(value: Record<string, unknown> | null | undefined): ConsumptionSnapshot | null {
  if (!value || typeof value.diversity_score !== "number" || !value.ideology || typeof value.ideology !== "object") return null;
  const ideology = value.ideology as Record<string, unknown>;
  if (typeof ideology.completed !== "boolean" || ![ideology.x, ideology.y, ideology.z].every((coordinate) => typeof coordinate === "number" && Number.isFinite(coordinate))) return null;
  return {
    diversity_score: Math.max(0, Math.min(100, value.diversity_score)),
    diversity_article_count: typeof value.diversity_article_count === "number" ? value.diversity_article_count : 0,
    ideology: ideology as Ideology,
    tier: typeof value.tier === "string" ? value.tier : undefined,
    credit_total: typeof value.credit_total === "number" ? value.credit_total : undefined,
  };
}
