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
import type { ConsentView, ErrorEnvelope, ReadResult, ShareCardView, VoteView } from "@/lib/api/contracts";
import { mockResponse } from "../openapi-contract";

const prefix = "/api/v1";

const mockConsents: ConsentView[] = [
  { id: "01H00000000000000000000001", purpose: "SERVICE", version: "1.0", body_hash: "service-v1", sensitive: false, granted: false },
  { id: "01H00000000000000000000002", purpose: "POLITICAL_PROFILE", version: "1.0", body_hash: "political-v1", sensitive: true, granted: false },
];
let mockCard: ShareCardView = { id: "01H00000000000000000000006", status: "ready", public_token: "mock-public-token", etag: '"mock"', snapshot: { x: 4, sensationalism: 18, confidence: 0.68 } };
const errorEnvelope = (code: string, message: string): ErrorEnvelope => mockResponse("ErrorEnvelope", { error: { code, message, request_id: "mock-request", retryable: false, details: {} } });

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
  http.get(`${prefix}/auth/providers`, () => HttpResponse.json(["mock"])),
  http.get(`${prefix}/auth/:provider/start`, () => new HttpResponse(null, { status: 302, headers: { Location: "/onboarding/consent" } })),
  http.get(`${prefix}/consents`, () => HttpResponse.json(mockConsents.map((item) => mockResponse("ConsentView", item)))),
  http.get(`${prefix}/questionnaires`, ({ request }) => {
    const kind = new URL(request.url).searchParams.get("kind") ?? "onboarding";
    const efficacy = kind === "efficacy";
    return HttpResponse.json([mockResponse("QuestionnaireVersionView", { id: efficacy ? "01H00000000000000000000004" : "01H00000000000000000000003", kind: efficacy ? "efficacy" : "onboarding", version: "1.0", schema_json: {}, scoring_json: {}, active_from: "2026-08-18T00:00:00Z", keys: efficacy ? ["confidence"] : ["economic", "social", "international"] })]);
  }),
  http.post(`${prefix}/me/consents`, async ({ request }) => {
    const body = await request.json() as { consent_version_id: string; granted: boolean };
    const consent = mockConsents.find((item) => item.id === body.consent_version_id);
    if (!consent) return HttpResponse.json(errorEnvelope("CONSENT_VERSION_STALE", "동의 버전이 만료되었습니다."), { status: 409 });
    consent.granted = body.granted;
    return HttpResponse.json(mockResponse("ConsentView", { ...consent }));
  }),
  http.patch(`${prefix}/me/demographics`, async ({ request }) => HttpResponse.json(await request.json())),
  http.post(`${prefix}/me/questionnaire-responses`, () => HttpResponse.json(mockResponse("ProfileView", { profile_id: "01H00000000000000000000005", kind: "SELF_REPORTED", x: 0, y: 0, z: 0, sensationalism: null, confidence: 0.65, source_version: "1.0", active: true }))),
  http.post(`${prefix}/me/efficacy-responses`, async ({ request }) => { const body = await request.json() as { answers: Record<string, number> }; return HttpResponse.json(mockResponse("EfficacyView", { normalized_score: Object.values(body.answers)[0], baseline_delta: null, due_survey: false })); }),
  http.post(`${prefix}/me/export`, () => HttpResponse.json(mockResponse("JobAccepted", { job_id: "01H00000000000000000000007", status: "PENDING" }), { status: 202 })),
  http.delete(`${prefix}/me`, () => HttpResponse.json(mockResponse("JobAccepted", { job_id: "01H00000000000000000000008", status: "PENDING" }), { status: 202 })),
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
    return HttpResponse.json(mockResponse("FeedPage", body));
  }),
  http.get(`${prefix}/issues`, () => HttpResponse.json(mockResponse("IssuePage", { items: apiIssues, next_cursor: null } satisfies IssuePageDto))),
  http.get(`${prefix}/issues/:issueId`, ({ params }) => {
    const issue = apiIssues.find((item) => item.id === params.issueId);
    const body: IssueDetailDto | undefined = issue ? { ...issue, distribution: { minimum_x: null, maximum_x: null, count: issue.article_ids.length } } : undefined;
    return body ? HttpResponse.json(mockResponse("IssueDetailView", body)) : HttpResponse.json(errorEnvelope("NOT_FOUND", "이슈를 찾을 수 없습니다."), { status: 404 });
  }),
  http.get(`${prefix}/articles/:articleId`, ({ params }) => {
    const article = apiArticles.find((item) => item.id === params.articleId);
    return article ? HttpResponse.json(mockResponse("ArticleView", article)) : HttpResponse.json(errorEnvelope("NOT_FOUND", "기사를 찾을 수 없습니다."), { status: 404 });
  }),
  http.get(`${prefix}/articles/:articleId/score`, ({ params }) => {
    const article = articles.find((item) => item.id === params.articleId);
    const body: ScoreDto | undefined = article ? { id: article.scoreVersion, article_version_id: article.scoreVersion, x: article.x, y: article.y, z: article.z, sensationalism: article.sensationalism, confidence: article.confidence, components: {}, status: "ACTIVE", created_at: article.publishedAt } : undefined;
    return body ? HttpResponse.json(mockResponse("ScoreView", body)) : HttpResponse.json(errorEnvelope("NOT_FOUND", "점수를 찾을 수 없습니다."), { status: 404 });
  }),
  http.get(`${prefix}/issues/:issueId/articles`, ({ params }) => {
    const items = articles.filter((article) => article.issueId === params.issueId).map((article) => ({
      ...apiArticles.find((item) => item.id === article.id)!,
      coordinate: { x: article.x, y: article.y, z: article.z, sensationalism: article.sensationalism, confidence: article.confidence },
    }));
    return HttpResponse.json(mockResponse("ArticlePage", { items, next_cursor: null } satisfies ArticlePageDto));
  }),
  http.get(`${prefix}/visualization/points`, () => HttpResponse.json(mockResponse("VisualizationPointPage", {
    items: visualizationPoints.map((point) => ({ entity_type: point.type, entity_id: point.id, label: point.label, x: point.x, y: point.y, z: point.z, confidence: point.confidence })),
    next_cursor: null,
  } satisfies VisualizationPointPageDto))),
  http.post(`${prefix}/articles/:articleId/read-sessions`, () => HttpResponse.json(mockResponse("ReadSessionView", {
    read_session_id: "01H00000000000000000000009",
    redirect_url: "/articles/article-01?returned=1",
    expires_at: "2026-08-18T12:00:00Z",
  }))),
  http.post(`${prefix}/read-sessions/:readSessionId/return`, () => HttpResponse.json(mockResponse("ReadResult", {
    status: "eligible",
    server_elapsed_ms: 94_000,
    credit_delta: 12,
    reason_code: "ELIGIBLE",
  } satisfies ReadResult))),
  http.put(`${prefix}/articles/:articleId/vote`, async ({ request }) => {
    const body = await request.json() as Pick<VoteView, "x" | "y" | "z" | "sensationalism">;
    return HttpResponse.json(mockResponse("VoteView", {
      ...body,
      revision: 2,
      quality_status: "QUALIFIED",
      active: true,
    }));
  }),
  http.delete(`${prefix}/articles/:articleId/vote`, () => new HttpResponse(null, { status: 204 })),
  http.post(`${prefix}/share-cards`, () => { mockCard = { ...mockCard, status: "ready" }; return HttpResponse.json(mockResponse("ShareCardJobAccepted", { job_id: "01H0000000000000000000000A", share_card_id: mockCard.id, status: "PENDING" }), { status: 202 }); }),
  http.get(`${prefix}/share-cards/:shareCardId`, ({ params }) => params.shareCardId === mockCard.id ? HttpResponse.json(mockResponse("ShareCardView", mockCard)) : HttpResponse.json(errorEnvelope("NOT_FOUND", "공유 카드를 찾을 수 없습니다."), { status: 404 })),
  http.delete(`${prefix}/share-cards/:shareCardId`, () => { mockCard = { ...mockCard, status: "revoked", public_token: null }; return new HttpResponse(null, { status: 204 }); }),
  http.get(`${prefix}/public/share/:publicToken/image`, () => new HttpResponse(new Uint8Array([137, 80, 78, 71]), { headers: { "Content-Type": "image/png" } })),
  http.get(`${prefix}/admin/:resource`, ({ params }) => HttpResponse.json({ items: [{ id: `${params.resource}-01`, title: `${params.resource} fixture`, status: "ACTIVE", version: 1, etag: '"v1"' }], next_cursor: null })),
  http.get(`${prefix}/admin/autopilot/recommendations`, () => HttpResponse.json({ items: [{ id: "recommendation-01", title: "추천", status: "PENDING_REVIEW" }], next_cursor: null })),
  http.get(`${prefix}/admin/autopilot/settings`, () => HttpResponse.json({ mode: "RECOMMEND", guardrails: {}, manual_locks: [], version: 1 })),
  http.post(`${prefix}/admin/autopilot/recommendations/:itemId/:action`, () => HttpResponse.json({ status: "PENDING" })),
  http.get(`${prefix}/admin/metrics/efficacy`, () => HttpResponse.json({ cohort: "all", status: "VISIBLE", count: 100 })),
  http.post(`${prefix}/admin/:resource/:itemId/:action`, () => HttpResponse.json({ status: "PENDING" })),
  http.patch(`${prefix}/admin/:resource/:itemId`, () => HttpResponse.json({ status: "ACTIVE" })),
];
