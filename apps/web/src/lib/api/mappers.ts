import type { components } from "./generated/schema";
import { decodeHtmlEntities } from "./formatters";
import type { Article, Issue, IssueComparison, VisualizationPoint } from "./types";

type FeedItemDto = components["schemas"]["FeedItem"];
export type FeedPageDto = components["schemas"]["FeedPage"];
export type ArticleDto = components["schemas"]["ArticleView"];
type ArticleWithCoordinateDto = components["schemas"]["ArticleWithCoordinate"];
export type ArticlePageDto = components["schemas"]["ArticlePage"];
export type ScoreDto = components["schemas"]["ScoreView"];
type IssueDto = components["schemas"]["IssueView"];
export type IssueDetailDto = components["schemas"]["IssueDetailView"];
export type IssuePageDto = components["schemas"]["IssuePage"];
type VisualizationPointDto = components["schemas"]["VisualizationPoint"];
export type VisualizationPointPageDto = components["schemas"]["VisualizationPointPage"];

type CursorPage<T> = { items: T[]; next_cursor: string | null };

function mapReasonCode(reason: string): Article["reasonCode"] {
  switch (reason) {
    case "ADJACENT_PERSPECTIVE":
    case "PERSONALIZED_ADJACENT":
      return "ADJACENT_VIEW";
    case "PERSONALIZED_RELEVANCE":
      return "SOURCE_DIVERSITY";
    case "QUALITY":
      return "RECENT_HIGH_CONFIDENCE";
    case "BALANCED_FALLBACK":
    case "FALLBACK_BALANCED":
    default:
      return "ISSUE_BALANCE";
  }
}

function articleBase(
  dto: ArticleDto,
  coordinate: components["schemas"]["Coordinate"] | null,
  reasonCode: Article["reasonCode"],
  scoreVersion: string,
): Article {
  return {
    id: dto.id,
    issueId: dto.issue_id ?? "unclustered",
    sourceId: dto.source_id,
    source: decodeHtmlEntities(dto.source),
    title: decodeHtmlEntities(dto.title),
    dek: decodeHtmlEntities(dto.summary),
    publishedAt: dto.published_at ?? "",
    originalUrl: dto.canonical_url,
    reasonCode,
    x: coordinate?.x ?? 0,
    y: coordinate?.y ?? 0,
    z: coordinate?.z ?? 0,
    sensationalism: coordinate?.sensationalism ?? null,
    confidence: coordinate?.confidence ?? 0,
    scoreVersion,
    analysisStatus: dto.analysis_status ?? (coordinate ? "READY" : "PROCESSING"),
    analysisProvider: dto.analysis_provider ?? null,
    stale: dto.status.toLowerCase() === "stale",
    claims: [],
  };
}

function mapFeedItem(dto: FeedItemDto): Article {
  return {
    id: dto.article_id,
    issueId: dto.issue_id,
    sourceId: "",
    source: decodeHtmlEntities(dto.source),
    title: decodeHtmlEntities(dto.title),
    dek: "",
    publishedAt: dto.published_at ?? "",
    originalUrl: "",
    reasonCode: mapReasonCode(dto.reason_code),
    x: dto.coordinate.x,
    y: dto.coordinate.y,
    z: dto.coordinate.z,
    sensationalism: dto.coordinate.sensationalism ?? null,
    confidence: dto.coordinate.confidence,
    scoreVersion: dto.score_version_id,
    analysisStatus: dto.analysis_status,
    analysisProvider: dto.analysis_provider,
    claims: [],
  };
}

export function mapFeedPage(dto: FeedPageDto): CursorPage<Article> {
  return { items: dto.items.map(mapFeedItem), next_cursor: dto.next_cursor ?? null };
}

export function mapArticle(dto: ArticleDto, score: ScoreDto | null): Article {
  return articleBase(dto, score, "RECENT_HIGH_CONFIDENCE", score?.score_version_id ?? score?.id ?? "분석 준비 중");
}

function mapArticleWithCoordinate(dto: ArticleWithCoordinateDto): Article {
  return articleBase(dto, dto.coordinate ?? null, "ISSUE_BALANCE", dto.current_version_id ?? "분석 준비 중");
}

export function mapArticlePage(dto: ArticlePageDto): CursorPage<Article> {
  return { items: dto.items.map(mapArticleWithCoordinate), next_cursor: dto.next_cursor ?? null };
}

export function mapIssue(dto: IssueDto | IssueDetailDto): Issue {
  const status = dto.status.toLowerCase();
  return {
    id: dto.id,
    title: decodeHtmlEntities(dto.title),
    summary: decodeHtmlEntities(dto.summary),
    topic: dto.topic,
    status: ["active", "open"].includes(status)
      && dto.analysis_status === "READY"
      && dto.article_ids.length >= 2
      && (dto.source_count ?? 0) >= 2
      ? "balanced"
      : "preparing",
    kind: dto.kind ?? "TOPIC",
    sourceCount: dto.source_count ?? 0,
    analysisStatus: dto.analysis_status ?? "PROCESSING",
    dataAsOf: dto.data_as_of ?? null,
    freshnessStatus: dto.freshness_status ?? "CURRENT",
    editorialPriority: dto.editorial_priority ?? null,
    updatedAt: dto.last_activity_at,
    articleIds: dto.article_ids,
  };
}

export function mapIssuePage(dto: IssuePageDto): CursorPage<Issue> {
  return { items: dto.items.map(mapIssue), next_cursor: dto.next_cursor ?? null };
}

function mapVisualizationPoint(dto: VisualizationPointDto): VisualizationPoint {
  return {
    id: dto.entity_id,
    label: decodeHtmlEntities(dto.label),
    type: dto.entity_type,
    x: dto.x,
    y: dto.y,
    z: dto.z,
    sensationalism: dto.sensationalism ?? null,
    confidence: dto.confidence,
    scoreVersion: "current",
    observedAt: "",
  };
}

export function mapVisualizationPointPage(dto: VisualizationPointPageDto): CursorPage<VisualizationPoint> {
  return { items: dto.items.map(mapVisualizationPoint), next_cursor: dto.next_cursor ?? null };
}

export function mapIssueComparison(dto: IssueComparison): IssueComparison {
  return {
    ...dto,
    issue: {
      ...dto.issue,
      title: decodeHtmlEntities(dto.issue.title),
      summary: decodeHtmlEntities(dto.issue.summary),
    },
    common_facts: dto.common_facts.map((fact) => ({
      ...fact,
      text: decodeHtmlEntities(fact.text),
      evidence_refs: fact.evidence_refs.map(decodeHtmlEntities),
    })),
    dimensions: dto.dimensions.map((dimension) => ({
      ...dimension,
      label: decodeHtmlEntities(dimension.label),
    })),
    articles: dto.articles.map((entry) => ({
      ...entry,
      article: {
        ...entry.article,
        source: decodeHtmlEntities(entry.article.source),
        title: decodeHtmlEntities(entry.article.title),
        summary: decodeHtmlEntities(entry.article.summary),
        author: entry.article.author === null ? null : decodeHtmlEntities(entry.article.author),
      },
      assessment: {
        ...entry.assessment,
        summary: decodeHtmlEntities(entry.assessment.summary),
      },
      frame: {
        ...entry.frame,
        headline_frame: entry.frame.headline_frame === null ? null : decodeHtmlEntities(entry.frame.headline_frame),
        emphasis: entry.frame.emphasis.map(decodeHtmlEntities),
        omissions_note: entry.frame.omissions_note === null ? null : decodeHtmlEntities(entry.frame.omissions_note),
        evidence_refs: entry.frame.evidence_refs.map(decodeHtmlEntities),
      },
    })),
  };
}
