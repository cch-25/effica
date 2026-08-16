import { delay, http, HttpResponse } from "msw";
import { articles, issues, visualizationPoints } from "../fixtures/content";
import type {
  ArticleDto,
  ArticlePageDto,
  FeedPageDto,
  IssueDetailDto,
  IssuePageDto,
  ScoreDto,
  VisualizationPointPageDto,
} from "@/lib/api/mappers";

const prefix = "/api/v1";

const apiArticles = articles.map((article): ArticleDto => ({
  id: article.id,
  issue_id: article.issueId,
  source_id: article.sourceId,
  source: article.source,
  title: article.title,
  summary: article.dek,
  published_at: article.publishedAt,
  canonical_url: article.originalUrl,
  current_version_id: article.scoreVersion,
  status: article.stale ? "stale" : "active",
}));

const apiIssues = issues.map((issue) => ({
  id: issue.id,
  title: issue.title,
  summary: issue.summary,
  status: issue.status === "balanced" ? "active" : "candidate",
  version: 1,
  article_ids: issue.articleIds,
  opened_at: issue.updatedAt,
  last_activity_at: issue.updatedAt,
}));

export const handlers = [
  http.get(`${prefix}/feed`, async () => {
    await delay(120);
    const body: FeedPageDto = {
      personalized: false,
      next_cursor: null,
      items: articles.map((article, index) => ({
        article_id: article.id,
        issue_id: article.issueId,
        title: article.title,
        source: article.source,
        coordinate: { x: article.x, y: article.y, z: article.z, sensationalism: article.sensationalism, confidence: article.confidence },
        reason_code: article.reasonCode === "ADJACENT_VIEW" ? "ADJACENT_PERSPECTIVE" : article.reasonCode === "RECENT_HIGH_CONFIDENCE" ? "QUALITY" : "FALLBACK_BALANCED",
        rank: index + 1,
      })),
    };
    return HttpResponse.json(body);
  }),
  http.get(`${prefix}/issues`, () => HttpResponse.json({ items: apiIssues, next_cursor: null } satisfies IssuePageDto)),
  http.get(`${prefix}/issues/:issueId`, ({ params }) => {
    const issue = apiIssues.find((item) => item.id === params.issueId);
    const body: IssueDetailDto | undefined = issue ? { ...issue, distribution: { minimum_x: null, maximum_x: null, count: issue.article_ids.length } } : undefined;
    return body ? HttpResponse.json(body) : HttpResponse.json({ error: { code: "NOT_FOUND" } }, { status: 404 });
  }),
  http.get(`${prefix}/articles/:articleId`, ({ params }) => {
    const article = apiArticles.find((item) => item.id === params.articleId);
    return article ? HttpResponse.json(article) : HttpResponse.json({ error: { code: "NOT_FOUND" } }, { status: 404 });
  }),
  http.get(`${prefix}/articles/:articleId/score`, ({ params }) => {
    const article = articles.find((item) => item.id === params.articleId);
    const body: ScoreDto | undefined = article ? { id: article.scoreVersion, article_version_id: article.scoreVersion, x: article.x, y: article.y, z: article.z, sensationalism: article.sensationalism, confidence: article.confidence, components: {}, status: "ACTIVE", created_at: article.publishedAt } : undefined;
    return body ? HttpResponse.json(body) : HttpResponse.json({ error: { code: "NOT_FOUND" } }, { status: 404 });
  }),
  http.get(`${prefix}/issues/:issueId/articles`, ({ params }) => {
    const items = articles.filter((article) => article.issueId === params.issueId).map((article) => ({
      ...apiArticles.find((item) => item.id === article.id)!,
      coordinate: { x: article.x, y: article.y, z: article.z, sensationalism: article.sensationalism, confidence: article.confidence },
    }));
    return HttpResponse.json({ items, next_cursor: null } satisfies ArticlePageDto);
  }),
  http.get(`${prefix}/visualization/points`, () => HttpResponse.json({
    items: visualizationPoints.map((point) => ({ entity_type: point.type, entity_id: point.id, label: point.label, x: point.x, y: point.y, z: point.z, confidence: point.confidence })),
    next_cursor: null,
  } satisfies VisualizationPointPageDto)),
  http.post(`${prefix}/articles/:articleId/read-sessions`, () => HttpResponse.json({
    read_session_id: "read-session-01",
    redirect_url: "/articles/article-01?returned=1",
  })),
  http.post(`${prefix}/read-sessions/:readSessionId/return`, () => HttpResponse.json({
    status: "eligible",
    server_elapsed_ms: 94_000,
    credit: { delta: 12, policy_version: "credit-v4" },
  })),
  http.put(`${prefix}/articles/:articleId/vote`, async ({ request }) => HttpResponse.json({
    id: "vote-01",
    revision: 2,
    active: true,
    ...(await request.json() as object),
  })),
  http.post(`${prefix}/share-cards`, () => HttpResponse.json({ id: "card-01", status: "queued" }, { status: 202 })),
];
