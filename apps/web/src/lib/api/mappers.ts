import type { components } from "./generated/schema";
import type { Article, Issue, VisualizationPoint } from "./types";

export type FeedItemDto = components["schemas"]["FeedItem"];
export type FeedPageDto = components["schemas"]["FeedPage"];
export type ArticleDto = components["schemas"]["ArticleView"];
export type ArticleWithCoordinateDto = components["schemas"]["ArticleWithCoordinate"];
export type ArticlePageDto = components["schemas"]["ArticlePage"];
export type ScoreDto = components["schemas"]["ScoreView"];
export type IssueDto = components["schemas"]["IssueView"];
export type IssueDetailDto = components["schemas"]["IssueDetailView"];
export type IssuePageDto = components["schemas"]["IssuePage"];
export type VisualizationPointDto = components["schemas"]["VisualizationPoint"];
export type VisualizationPointPageDto = components["schemas"]["VisualizationPointPage"];

export type CursorPage<T> = { items: T[]; next_cursor: string | null };

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
  coordinate: components["schemas"]["Coordinate"],
  reasonCode: Article["reasonCode"],
  scoreVersion: string,
): Article {
  return {
    id: dto.id,
    issueId: dto.issue_id ?? "unclustered",
    sourceId: dto.source_id,
    source: dto.source,
    title: dto.title,
    dek: dto.summary,
    publishedAt: dto.published_at ?? "",
    originalUrl: dto.canonical_url,
    reasonCode,
    x: coordinate.x,
    y: coordinate.y,
    z: coordinate.z,
    sensationalism: coordinate.sensationalism ?? null,
    confidence: coordinate.confidence,
    scoreVersion,
    stale: dto.status.toLowerCase() === "stale",
    claims: [],
  };
}

export function mapFeedItem(dto: FeedItemDto): Article {
  return {
    id: dto.article_id,
    issueId: dto.issue_id,
    sourceId: "",
    source: dto.source,
    title: dto.title,
    dek: "",
    publishedAt: "",
    originalUrl: "",
    reasonCode: mapReasonCode(dto.reason_code),
    x: dto.coordinate.x,
    y: dto.coordinate.y,
    z: dto.coordinate.z,
    sensationalism: dto.coordinate.sensationalism ?? null,
    confidence: dto.coordinate.confidence,
    scoreVersion: "current",
    claims: [],
  };
}

export function mapFeedPage(dto: FeedPageDto): CursorPage<Article> {
  return { items: dto.items.map(mapFeedItem), next_cursor: dto.next_cursor ?? null };
}

export function mapArticle(dto: ArticleDto, score: ScoreDto): Article {
  return articleBase(dto, score, "RECENT_HIGH_CONFIDENCE", score.score_version_id ?? score.id);
}

export function mapArticleWithCoordinate(dto: ArticleWithCoordinateDto): Article {
  return articleBase(dto, dto.coordinate, "ISSUE_BALANCE", dto.current_version_id ?? "current");
}

export function mapArticlePage(dto: ArticlePageDto): CursorPage<Article> {
  return { items: dto.items.map(mapArticleWithCoordinate), next_cursor: dto.next_cursor ?? null };
}

export function mapIssue(dto: IssueDto | IssueDetailDto): Issue {
  const status = dto.status.toLowerCase();
  return {
    id: dto.id,
    title: dto.title,
    summary: dto.summary,
    topic: "일반",
    status: ["active", "open"].includes(status) && dto.article_ids.length >= 2 ? "balanced" : "preparing",
    updatedAt: dto.last_activity_at,
    articleIds: dto.article_ids,
  };
}

export function mapIssuePage(dto: IssuePageDto): CursorPage<Issue> {
  return { items: dto.items.map(mapIssue), next_cursor: dto.next_cursor ?? null };
}

export function mapVisualizationPoint(dto: VisualizationPointDto): VisualizationPoint {
  return {
    id: dto.entity_id,
    label: dto.label,
    type: dto.entity_type,
    x: dto.x,
    y: dto.y,
    z: dto.z,
    sensationalism: null,
    confidence: dto.confidence,
    scoreVersion: "current",
    observedAt: "",
  };
}

export function mapVisualizationPointPage(dto: VisualizationPointPageDto): CursorPage<VisualizationPoint> {
  return { items: dto.items.map(mapVisualizationPoint), next_cursor: dto.next_cursor ?? null };
}
