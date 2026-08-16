import { delay, http, HttpResponse } from "msw";
import { articles, issues, visualizationPoints } from "../fixtures/content";

const prefix = "/api/v1";

export const handlers = [
  http.get(`${prefix}/feed`, async () => {
    await delay(120);
    return HttpResponse.json({ items: articles, next_cursor: null });
  }),
  http.get(`${prefix}/issues`, () => HttpResponse.json({ items: issues, next_cursor: null })),
  http.get(`${prefix}/issues/:issueId`, ({ params }) => {
    const issue = issues.find((item) => item.id === params.issueId);
    return issue ? HttpResponse.json(issue) : HttpResponse.json({ error: { code: "NOT_FOUND" } }, { status: 404 });
  }),
  http.get(`${prefix}/articles/:articleId`, ({ params }) => {
    const article = articles.find((item) => item.id === params.articleId);
    return article ? HttpResponse.json(article) : HttpResponse.json({ error: { code: "NOT_FOUND" } }, { status: 404 });
  }),
  http.get(`${prefix}/visualization/points`, () => HttpResponse.json({ items: visualizationPoints, next_cursor: null })),
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
