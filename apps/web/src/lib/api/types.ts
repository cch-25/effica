export type Role = "guest" | "member" | "analyst" | "reviewer" | "admin";
export type ResourceState =
  | "ready"
  | "loading"
  | "empty"
  | "partial"
  | "error"
  | "fatal"
  | "unauthorized"
  | "consent-required"
  | "stale"
  | "processing"
  | "conflict"
  | "rate-limited";

export type AxisScores = {
  x: number;
  y: number;
  z: number;
  sensationalism: number;
  confidence: number;
};

export type Article = AxisScores & {
  id: string;
  issueId: string;
  sourceId: string;
  source: string;
  title: string;
  dek: string;
  publishedAt: string;
  originalUrl: string;
  reasonCode: "ADJACENT_VIEW" | "SOURCE_DIVERSITY" | "ISSUE_BALANCE" | "RECENT_HIGH_CONFIDENCE";
  scoreVersion: string;
  stale?: boolean;
  claims: string[];
};

export type Issue = {
  id: string;
  title: string;
  summary: string;
  topic: string;
  status: "balanced" | "preparing";
  updatedAt: string;
  articleIds: string[];
};

export type VisualizationPoint = AxisScores & {
  id: string;
  label: string;
  type: "article" | "source" | "user";
  scoreVersion: string;
  observedAt: string;
};

export type AdminItem = {
  id: string;
  title: string;
  subtitle: string;
  status: string;
  metadata: Array<{ label: string; value: string }>;
};

export type ApiErrorBody = {
  error: {
    code: string;
    message: string;
    request_id: string;
    retryable: boolean;
    details: Record<string, unknown>;
  };
};
