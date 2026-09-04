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
import type { IssueComparison } from "@/lib/api/types";
import { mockResponse } from "../openapi-contract";

const prefix = "/api/v1";

const mockConsents: ConsentView[] = [
  { id: "01H00000000000000000000001", purpose: "SERVICE", version: "1.0", body_hash: "service-v1", sensitive: false, granted: false },
  { id: "01H00000000000000000000002", purpose: "POLITICAL_PROFILE", version: "1.0", body_hash: "political-v1", sensitive: true, granted: false },
];
let mockCard: ShareCardView = { id: "01H00000000000000000000006", status: "ready", public_token: "mock-public-token", etag: '"mock"', snapshot: { x: 4, sensationalism: 18, confidence: 0.68 } };
let mockEfficacyHistory = {
  baseline: 52,
  responses: [
    { id: "01H0000000000000000000000C", questionnaire_version_id: "01H00000000000000000000004", normalized_score: 52, submitted_at: "2026-05-12T00:00:00Z" },
    { id: "01H0000000000000000000000D", questionnaire_version_id: "01H00000000000000000000004", normalized_score: 64, submitted_at: "2026-08-12T00:00:00Z" },
  ],
  due_survey: true,
};
type MockLlmUsage = { enabled: boolean; status: "RUNNING" | "STOPPED"; version: number; cancelled_jobs: number; updated_by: string | null; updated_at: string | null };
let mockLlmUsage: MockLlmUsage = { enabled: false, status: "STOPPED", version: 1, cancelled_jobs: 0, updated_by: null, updated_at: null };
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
  analysis_status: article.analysisStatus,
  analysis_provider: article.analysisProvider,
  status: article.stale ? "stale" : "active",
}));

const apiIssues = issues.map((issue) => ({
  id: issue.id,
  title: issue.title,
  summary: issue.summary,
  topic: issue.topic,
  status: issue.status === "balanced" ? "active" : "candidate",
  version: 1,
  article_ids: issue.articleIds,
  kind: issue.kind,
  source_count: issue.sourceCount,
  analysis_status: issue.analysisStatus,
  data_as_of: issue.dataAsOf,
  freshness_status: issue.freshnessStatus,
  editorial_priority: issue.editorialPriority,
  opened_at: issue.updatedAt,
  last_activity_at: issue.updatedAt,
}));

export const handlers = [
  http.get(`${prefix}/auth/providers`, () => HttpResponse.json(["google"])),
  http.post(`${prefix}/auth/admin/login`, async ({ request }) => {
    const body = await request.json() as { username?: string; password?: string };
    if (body.username !== "dev" || body.password !== "1234") {
      return HttpResponse.json(
        errorEnvelope("ADMIN_CREDENTIALS_INVALID", "관리자 계정 정보가 올바르지 않습니다."),
        { status: 401 },
      );
    }
    return new HttpResponse(null, { status: 204 });
  }),
  http.get(`${prefix}/auth/:provider/start`, ({ request }) => {
    const returnTo = new URL(request.url).searchParams.get("returnTo") || "/";
    const location = returnTo.startsWith("/") && !returnTo.startsWith("//") && returnTo !== "/"
      ? `/onboarding/consent?returnTo=${encodeURIComponent(returnTo)}`
      : "/onboarding/consent";
    return new HttpResponse(null, { status: 302, headers: { Location: location } });
  }),
  http.get(`${prefix}/me`, () => HttpResponse.json(mockResponse("UserView", {
    id: "01HZZZZZZZZZZZZZZZZZZZZZZ1",
    display_name: "Mock 사용자",
    role: "MEMBER",
    consent_complete: true,
    onboarding_complete: true,
    behavioral_profile_active: false,
  }))),
  http.get(`${prefix}/me/progress`, () => HttpResponse.json({
    credit_total: 12,
    level: 1,
    tier: "Explorer",
    policy_version: "tier-v1",
    read_article_count: 1,
    compared_issue_count: 1,
    source_diversity_count: 1,
    self_reported_profile: { x: 4, y: 0, z: 0, sensationalism: null, confidence: 0.68 },
    behavioral_profile: null,
  })),
  http.get(`${prefix}/me/credits`, () => HttpResponse.json({
    items: [{
      id: "01H0000000000000000000000B",
      event_type: "QUALIFIED_READ",
      event_key: "read:01H00000000000000000000009",
      delta: 12,
      policy_version: "credit-v1",
      status: "POSTED",
      created_at: "2026-08-16T12:41:00Z",
    }],
    next_cursor: null,
  })),
  http.get(`${prefix}/me/efficacy`, () => HttpResponse.json(mockEfficacyHistory)),
  http.get(`${prefix}/consents`, () => HttpResponse.json(mockConsents.map((item) => mockResponse("ConsentView", item)))),
  http.get(`${prefix}/questionnaires`, ({ request }) => {
    const kind = new URL(request.url).searchParams.get("kind") ?? "onboarding";
    const efficacy = kind === "efficacy";
    const keys = efficacy ? ["baseline", "current"] : ["economic", "social", "international"];
    return HttpResponse.json([mockResponse("QuestionnaireVersionView", {
      id: efficacy ? "01H00000000000000000000004" : "01H00000000000000000000003",
      kind: efficacy ? "efficacy" : "onboarding",
      version: "1.0",
      schema_json: {
        questions: keys.map((id) => ({ id, required: true, minimum: efficacy ? 0 : -100, maximum: efficacy ? 100 : 100 })),
      },
      scoring_json: {},
      active_from: "2026-08-18T00:00:00Z",
      keys,
    })]);
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
  http.post(`${prefix}/me/efficacy-responses`, async ({ request }) => {
    const body = await request.json() as { answers: Record<string, number> };
    const values = Object.values(body.answers);
    const normalizedScore = values.length ? Math.round(values.reduce((sum, value) => sum + value, 0) / values.length) : 50;
    mockEfficacyHistory = {
      ...mockEfficacyHistory,
      responses: [...mockEfficacyHistory.responses, {
        id: "01H0000000000000000000000E",
        questionnaire_version_id: "01H00000000000000000000004",
        normalized_score: normalizedScore,
        submitted_at: new Date().toISOString(),
      }],
      due_survey: false,
    };
    return HttpResponse.json(mockResponse("EfficacyView", {
      normalized_score: normalizedScore,
      baseline_delta: normalizedScore - mockEfficacyHistory.baseline,
      due_survey: false,
    }));
  }),
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
        published_at: article.publishedAt,
        analysis_provider: "openai",
        analysis_status: "READY",
        score_version_id: article.scoreVersion,
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
    const body: ScoreDto | undefined = article ? { id: article.scoreVersion, article_version_id: article.scoreVersion, x: article.x, y: article.y, z: article.z, sensationalism: article.sensationalism, confidence: article.confidence, components: {}, status: "ACTIVE", analysis_provider: "openai", analysis_status: "READY", created_at: article.publishedAt } : undefined;
    return body ? HttpResponse.json(mockResponse("ScoreView", body)) : HttpResponse.json(errorEnvelope("NOT_FOUND", "점수를 찾을 수 없습니다."), { status: 404 });
  }),
  http.get(`${prefix}/articles/:articleId/assessments`, ({ params }) => {
    const article = articles.find((item) => item.id === params.articleId);
    if (!article) return HttpResponse.json(errorEnvelope("NOT_FOUND", "분석을 찾을 수 없습니다."), { status: 404 });
    return HttpResponse.json(mockResponse("AssessmentPage", {
      article_version_id: article.scoreVersion,
      assessments: [{
        id: `assessment-${article.id}`,
        model_alias: "openai-bias-v1",
        actual_model_id: "gpt-5.6-luna",
        prompt_version: "bias-sensationalism-v1",
        summary: article.claims[0] ?? "공개 가능한 분석 요약이 없습니다.",
        evidence: article.claims.map((quote) => ({ quote })),
        confidence: article.confidence,
        provider: "openai",
        created_at: article.publishedAt,
        synthetic: false,
      }],
    }));
  }),
  http.get(`${prefix}/articles/:articleId/score-history`, ({ params }) => {
    const article = articles.find((item) => item.id === params.articleId);
    if (!article) return HttpResponse.json(errorEnvelope("NOT_FOUND", "점수 이력을 찾을 수 없습니다."), { status: 404 });
    return HttpResponse.json(mockResponse("Page", {
      items: [{
        id: article.scoreVersion,
        score_version_id: article.scoreVersion,
        x: article.x,
        sensationalism: article.sensationalism,
        confidence: article.confidence,
        created_at: article.publishedAt,
      }],
      next_cursor: null,
    }));
  }),
  http.get(`${prefix}/issues/:issueId/articles`, ({ params }) => {
    const items = articles.filter((article) => article.issueId === params.issueId).map((article) => ({
      ...apiArticles.find((item) => item.id === article.id)!,
      coordinate: { x: article.x, y: article.y, z: article.z, sensationalism: article.sensationalism, confidence: article.confidence },
    }));
    return HttpResponse.json(mockResponse("ArticlePage", { items, next_cursor: null } satisfies ArticlePageDto));
  }),
  http.get(`${prefix}/issues/:issueId/comparison`, ({ params, request }) => {
    const issue = apiIssues.find((item) => item.id === params.issueId);
    if (!issue) return HttpResponse.json(errorEnvelope("NOT_FOUND", "이슈를 찾을 수 없습니다."), { status: 404 });

    const requestedIds = new URL(request.url).searchParams.getAll("article_ids");
    const selected = requestedIds
      .map((articleId) => articles.find((article) => article.id === articleId && article.issueId === issue.id))
      .filter((article): article is (typeof articles)[number] => article !== undefined);
    const sourceCount = new Set(selected.map((article) => article.sourceId)).size;
    const valid = requestedIds.length >= 2
      && requestedIds.length <= 4
      && selected.length === requestedIds.length
      && new Set(requestedIds).size === requestedIds.length
      && sourceCount === selected.length
      && selected.every((article) => article.analysisStatus === "READY"
        && article.analysisProvider === "openai"
        && article.sensationalism !== null);
    if (!valid) {
      return HttpResponse.json(
        errorEnvelope("COMPARISON_ARTICLES_INVALID", "서로 다른 출처의 비교 준비 완료 기사 2개부터 4개까지 선택해 주세요."),
        { status: 400 },
      );
    }

    const frames: Record<string, { headline: string; emphasis: string[]; omission: string }> = {
      "article-01": {
        headline: "공급 속도보다 정책의 실행 조건을 먼저 살펴봅니다.",
        emphasis: ["인허가 병목", "공공 기여 기준"],
        omission: "단기 가격 변화는 구체적으로 다루지 않습니다.",
      },
      "article-02": {
        headline: "규제 완화가 민간 공급에 미칠 효과를 중심으로 봅니다.",
        emphasis: ["재건축 규제", "공급 확대"],
        omission: "세입자 이주 지원은 자세히 다루지 않습니다.",
      },
      "article-05": {
        headline: "공급 확대 과정에서 세입자 보호가 필요한 이유를 짚습니다.",
        emphasis: ["이주 지원", "주거 안정"],
        omission: "사업 기간 단축 효과는 구체적으로 비교하지 않습니다.",
      },
    };
    const body: IssueComparison = {
      issue: {
        id: issue.id,
        version: issue.version,
        title: issue.title,
        summary: issue.summary,
        data_as_of: issue.data_as_of,
        article_count: issue.article_ids.length,
        source_count: issue.source_count,
      },
      common_facts: [
        {
          id: "fact-housing-policy",
          text: "정부는 도심 주택 공급 확대를 위해 정비사업 관련 제도 개선을 추진하고 있습니다.",
          article_ids: selected.map((article) => article.id),
          evidence_refs: selected.map((article) => `${article.source} 기사 본문`),
        },
        {
          id: "fact-policy-tradeoff",
          text: "보도들은 공급 확대 과정에서 사업 속도와 보호 장치가 함께 논의된다고 설명합니다.",
          article_ids: selected.map((article) => article.id),
          evidence_refs: selected.map((article) => `${article.source} 기사 본문`),
        },
      ],
      dimensions: [
        { key: "headline_frame", label: "핵심 관점" },
        { key: "emphasis", label: "강조한 쟁점" },
      ],
      articles: selected.map((article) => {
        const frame = frames[article.id] ?? {
          headline: `${issue.title}에서 ${article.source}가 강조한 쟁점을 설명합니다.`,
          emphasis: article.claims.slice(0, 2),
          omission: "선택한 기사만으로 확인하기 어려운 맥락이 있습니다.",
        };
        return {
          article: {
            id: article.id,
            source_id: article.sourceId,
            source: article.source,
            issue_id: article.issueId,
            canonical_url: article.originalUrl,
            title: article.title,
            author: null,
            summary: article.dek,
            published_at: article.publishedAt,
            current_version_id: article.scoreVersion,
            analysis_status: "READY" as const,
            analysis_provider: "openai" as const,
            status: "active",
          },
          score: {
            id: article.scoreVersion,
            score_version_id: article.scoreVersion,
            article_version_id: article.scoreVersion,
            weight_revision_id: null,
            version: 1,
            x: article.x,
            y: article.y,
            z: article.z,
            sensationalism: article.sensationalism ?? 0,
            confidence: article.confidence,
            components: {},
            components_json: null,
            status: "ACTIVE",
            analysis_provider: "openai" as const,
            analysis_status: "READY" as const,
            created_at: article.publishedAt,
          },
          assessment: {
            id: `assessment-${article.id}`,
            model_alias: "openai-bias-v1",
            actual_model_id: "gpt-5.6-luna",
            prompt_version: "bias-sensationalism-v1",
            summary: article.dek,
            evidence: article.claims.map((quote) => ({ quote })),
            confidence: article.confidence,
            provider: "openai" as const,
            created_at: article.publishedAt,
            synthetic: false as const,
          },
          frame: {
            headline_frame: frame.headline,
            emphasis: frame.emphasis,
            omissions_note: frame.omission,
            evidence_refs: article.claims,
          },
          vote_aggregate: {
            qualified: { x: null, y: null, z: null, sensationalism: null },
            qualified_count: 0,
            small_segments_suppressed: true,
            snapshot_version: null,
            generated_at: null,
            status: "ready" as const,
          },
        };
      }),
      comparison_version: "mock-comparison-v1",
      prompt_version: "issue-framing-v1",
      model_alias: "openai-comparison-v1",
      actual_model_id: "gpt-5.6-luna",
      confidence: 0.84,
      created_at: "2026-08-16T03:05:00Z",
      reviewed_at: "2026-08-16T03:30:00Z",
    };
    return HttpResponse.json(mockResponse("IssueComparisonView", body));
  }),
  http.get(`${prefix}/visualization/points`, () => HttpResponse.json(mockResponse("VisualizationPointPage", {
    items: visualizationPoints.map((point) => ({ entity_type: point.type, entity_id: point.id, label: point.label, x: point.x, y: point.y, z: point.z, sensationalism: point.sensationalism, confidence: point.confidence })),
    next_cursor: null,
  } satisfies VisualizationPointPageDto))),
  http.post(`${prefix}/articles/:articleId/read-sessions`, ({ params }) => HttpResponse.json(mockResponse("ReadSessionView", {
    read_session_id: "01H00000000000000000000009",
    redirect_url: `/articles/${params.articleId}?returned=1`,
    expires_at: "2026-08-18T12:00:00Z",
  }))),
  http.post(`${prefix}/read-sessions/:readSessionId/return`, () => HttpResponse.json(mockResponse("ReadResult", {
    status: "eligible",
    server_elapsed_ms: 94_000,
    credit_delta: 12,
    reason_code: "ELIGIBLE",
  } satisfies ReadResult))),
  http.get(`${prefix}/articles/:articleId/vote`, ({ params }) => (
    params.articleId === "article-05"
      ? HttpResponse.json(errorEnvelope("AUTH_REQUIRED", "로그인이 필요합니다."), { status: 401 })
      : HttpResponse.json(errorEnvelope("NOT_FOUND", "활성 투표를 찾을 수 없습니다."), { status: 404 })
  )),
  http.get(`${prefix}/articles/:articleId/votes/aggregate`, () => HttpResponse.json({
    qualified: { x: null, y: null, z: null, sensationalism: null },
    qualified_count: 0,
    small_segments_suppressed: true,
    snapshot_version: null,
    generated_at: null,
    status: "ready",
  })),
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
  http.post(`${prefix}/share-cards/:shareCardId/retry`, ({ params }) => { mockCard = { ...mockCard, status: "queued", etag: null }; return HttpResponse.json(mockResponse("ShareCardJobAccepted", { job_id: "01H0000000000000000000000A", share_card_id: String(params.shareCardId), status: "PENDING" }), { status: 202 }); }),
  http.delete(`${prefix}/share-cards/:shareCardId`, () => { mockCard = { ...mockCard, status: "revoked", public_token: null }; return new HttpResponse(null, { status: 204 }); }),
  http.get(`${prefix}/public/share/:publicToken`, ({ params }) => (
    params.publicToken === mockCard.public_token
      ? HttpResponse.json({
        id: mockCard.id,
        template: "orbit",
        display_name: "김사이",
        snapshot: mockCard.snapshot,
        etag: mockCard.etag,
      })
      : HttpResponse.json(errorEnvelope("NOT_FOUND", "공개 카드를 찾을 수 없습니다."), { status: 404 })
  )),
  http.get(`${prefix}/public/share/:publicToken/image`, () => new HttpResponse(new Uint8Array([137, 80, 78, 71]), { headers: { "Content-Type": "image/png" } })),
  http.get(`${prefix}/admin/:resource`, ({ params }) => HttpResponse.json({ items: [{ id: `${params.resource}-01`, title: `${params.resource} fixture`, status: "ACTIVE", version: 1, etag: '"v1"' }], next_cursor: null })),
  http.get(`${prefix}/admin/autopilot/recommendations`, () => HttpResponse.json({ items: [{ id: "recommendation-01", title: "추천", status: "PENDING_REVIEW" }], next_cursor: null })),
  http.get(`${prefix}/admin/autopilot/settings`, () => HttpResponse.json({ mode: "RECOMMEND", guardrails: {}, manual_locks: [], version: 1 })),
  http.get(`${prefix}/admin/runtime/llm-usage`, () => HttpResponse.json(mockLlmUsage)),
  http.put(`${prefix}/admin/runtime/llm-usage`, async ({ request }) => {
    const body = await request.json() as { enabled: boolean };
    mockLlmUsage = { enabled: body.enabled, status: body.enabled ? "RUNNING" : "STOPPED", version: mockLlmUsage.version + 1, cancelled_jobs: body.enabled ? 0 : 7, updated_by: "mock-admin", updated_at: new Date().toISOString() };
    return HttpResponse.json(mockLlmUsage);
  }),
  http.post(`${prefix}/admin/autopilot/recommendations/:itemId/:action`, () => HttpResponse.json({ status: "PENDING" })),
  http.get(`${prefix}/admin/metrics/efficacy`, () => HttpResponse.json({ cohort: "all", status: "VISIBLE", count: 100 })),
  http.post(`${prefix}/admin/:resource/:itemId/:action`, () => HttpResponse.json({ status: "PENDING" })),
  http.patch(`${prefix}/admin/:resource/:itemId`, () => HttpResponse.json({ status: "ACTIVE" })),
];
