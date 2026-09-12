import { describe, expect, it } from "vitest";
import { articles, issues } from "@/mocks/fixtures/content";
import type { Issue } from "@/lib/api/types";
import { articlesForHomeIssue, buildHomeEdition, homePublishedAt, publisherPreview } from "@/features/home/home-edition";

const issue = (id: string, title: string, priority: number, extra: Partial<Issue> = {}): Issue => ({
  ...issues[0], id, title, topic: "정치", editorialPriority: priority,
  dataAsOf: "2026-09-11T03:00:00Z", updatedAt: "2026-09-11T03:00:00Z",
  articleIds: [`${id}-a`, `${id}-b`, `${id}-c`], ...extra,
});

export const hearingIssues = [
  issue("kim", "김승원 법무부 장관 후보자 신약 청탁 의혹과 인사청문 검증 공방", 1),
  issue("yong", "용혜인 성평등가족부 장관 후보자의 국회의원 겸직 및 공직 적격성 논란", 2),
  issue("witness", "김승원 용혜인 강신철 장관 후보자 인사청문회 증인 채택 무산", 3),
  issue("hormuz", "호르무즈 해협 파병과 안보 지원을 둘러싼 정부 국회 공방", 4),
  issue("hearing", "김승원 용혜인 장관 후보자 인사청문회와 각종 의혹 검증", 5),
];

describe("homepage issue groups", () => {
  it("groups the reported four overlapping appointment angles, preserving all cohorts", () => {
    const groups = buildHomeEdition(hearingIssues);
    expect(groups).toHaveLength(2);
    expect(groups[0].title).toBe("장관 후보자 인사청문회");
    expect(groups[0].issues.map((item) => item.id)).toEqual(["kim", "yong", "witness", "hearing"]);
    expect(groups[1].issues.map((item) => item.id)).toEqual(["hormuz"]);
    expect(groups[0].issues[0].articleIds).toEqual(["kim-a", "kim-b", "kim-c"]);
  });

  it("groups before limiting so lower-ranked distinct events remain discoverable", () => {
    const next = issue("tax", "종합부동산세 공제 한도 개편", 6);
    expect(buildHomeEdition([...hearingIssues, next], 3).map((group) => group.id)).toEqual(["kim", "hormuz", "tax"]);
  });

  it("does not equate a shared politician, generic words, or distant events", () => {
    const other = [
      issue("tax", "김승원 종합부동산세 개편안 발의 논란", 6),
      issue("other-name", "이정민 장관 후보자 국회의원 겸직 논란", 7),
      issue("old", hearingIssues[0].title, 8, { dataAsOf: "2026-08-01T00:00:00Z" }),
    ];
    expect(buildHomeEdition([hearingIssues[0], ...other])).toHaveLength(4);
  });

  it("excludes broad topics and stale/undersourced issues without filling empty slots", () => {
    expect(buildHomeEdition([
      issue("topic", "정치", 1, { kind: "TOPIC" }),
      issue("stale", "노동시간 개편", 2, { freshnessStatus: "UPDATE_NEEDED" }),
      issue("thin", "세금 개편", 3, { sourceCount: 2 }),
    ])).toEqual([]);
  });
});

it("restricts articles by canonical membership, sorts them, and keeps the newest per publisher", () => {
  const newest = { ...articles[0], id: "new", publishedAt: "2026-09-11T02:00:00Z" };
  const old = { ...newest, id: "old", publishedAt: "2026-09-10T02:00:00Z", originalUrl: "https://www.seoul.example/old" };
  const other = { ...articles[1], id: "other", publishedAt: "2026-09-11T01:00:00Z" };
  const selected = issue("kim", "이슈", 1, { articleIds: ["old", "new", "other"] });
  const scoped = articlesForHomeIssue(selected, [old, articles[2], other, newest]);
  expect(scoped.map((item) => item.id)).toEqual(["new", "other", "old"]);
  expect(publisherPreview(scoped).map((item) => item.id)).toEqual(["new", "other"]);
  expect(homePublishedAt("")).toBe("발행 시각 미확인");
  expect(homePublishedAt("2026-09-11T02:00:00Z")).toContain("11:00");
});
