import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { setupServer } from "msw/node";
import { handlers } from "@/mocks/handlers";
import type { IssueComparison } from "@/lib/api/types";

const server = setupServer(...handlers);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("mock issue comparison", () => {
  it("returns reviewed common facts and a distinct frame for each selected article", async () => {
    const response = await fetch(
      `${window.location.origin}/api/v1/issues/issue-housing/comparison?article_ids=article-01&article_ids=article-02`,
    );
    const body = await response.json() as IssueComparison;

    expect(response.status).toBe(200);
    expect(body.common_facts.map((fact) => fact.text)).toContain(
      "정부는 도심 주택 공급 확대를 위해 정비사업 관련 제도 개선을 추진하고 있습니다.",
    );
    expect(body.articles).toHaveLength(2);
    expect(body.articles.map((entry) => entry.frame.headline_frame)).toEqual([
      "공급 속도보다 정책의 실행 조건을 먼저 살펴봅니다.",
      "규제 완화가 민간 공급에 미칠 효과를 중심으로 봅니다.",
    ]);
  });
});
