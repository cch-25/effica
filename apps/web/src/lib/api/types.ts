export type { Role } from "./contracts";
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

export type Article = Omit<AxisScores, "sensationalism"> & {
  sensationalism: number | null;
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
  analysisStatus: "READY" | "PROCESSING" | "PARTIAL" | "UNTRUSTED";
  analysisProvider: "openai" | null;
  stale?: boolean;
  claims: string[];
};

export type Issue = {
  id: string;
  title: string;
  summary: string;
  topic: string;
  status: "balanced" | "preparing";
  kind: "EVENT" | "TOPIC";
  sourceCount: number;
  analysisStatus: "READY" | "PROCESSING" | "PARTIAL" | "UNTRUSTED";
  dataAsOf: string | null;
  freshnessStatus: "CURRENT" | "UPDATE_NEEDED";
  editorialPriority: number | null;
  updatedAt: string;
  articleIds: string[];
};

export type IssueComparison = {
  issue: {
    id: string;
    version: number;
    title: string;
    summary: string;
    data_as_of: string | null;
    article_count: number;
    source_count: number;
  };
  common_facts: Array<{
    id: string;
    text: string;
    article_ids: string[];
    evidence_refs: string[];
  }>;
  dimensions: Array<{ key: string; label: string }>;
  articles: Array<{
    article: {
      id: string;
      source_id: string;
      source: string;
      issue_id: string | null;
      canonical_url: string;
      title: string;
      author: string | null;
      summary: string;
      published_at: string | null;
      current_version_id: string | null;
      analysis_status: "READY";
      analysis_provider: "openai";
      status: string;
    };
    score: AxisScores & {
      id: string;
      score_version_id: string | null;
      article_version_id: string;
      weight_revision_id: string | null;
      version: number | null;
      components: Record<string, unknown>;
      components_json: Record<string, unknown> | null;
      status: string;
      analysis_provider: "openai";
      analysis_status: "READY";
      created_at: string;
    };
    assessment: {
      id: string;
      model_alias: string;
      actual_model_id: string;
      prompt_version: string;
      summary: string;
      evidence: Array<Record<string, unknown>>;
      confidence: number;
      provider: "openai";
      created_at: string;
      synthetic: false;
    };
    frame: {
      headline_frame: string | null;
      emphasis: string[];
      omissions_note: string | null;
      evidence_refs: string[];
    };
    vote_aggregate: {
      qualified: { x: number | null; y: number | null; z: number | null; sensationalism: number | null };
      qualified_count: number;
      small_segments_suppressed: boolean;
      snapshot_version: number | null;
      generated_at: string | null;
      status: "ready" | "pending";
    };
  }>;
  comparison_version: string;
  prompt_version: string;
  model_alias: string;
  actual_model_id: string;
  confidence: number;
  created_at: string;
  reviewed_at: string;
};

export type Vote = {
  x: number;
  y: number;
  z: number;
  sensationalism: number;
  revision: number;
  quality_status: string;
  active: boolean;
};

export type VoteAggregate = {
  qualified: { x: number | null; y: number | null; z: number | null; sensationalism: number | null };
  qualified_count: number;
  small_segments_suppressed: boolean;
  snapshot_version?: number | null;
  generated_at?: string | null;
  status: "ready" | "pending";
};

export type VisualizationPoint = Omit<AxisScores, "sensationalism"> & {
  sensationalism: number | null;
  id: string;
  label: string;
  type: "article" | "source" | "user";
  scoreVersion: string;
  observedAt: string;
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
