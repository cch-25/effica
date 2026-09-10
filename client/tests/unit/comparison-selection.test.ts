import { describe, expect, it } from "vitest";
import { defaultComparisonSelection, isComparisonReadyArticle, parseComparisonSelection } from "@/features/issues/comparison/selection";
import type { Article } from "@/lib/api/types";
import { publisherIdentity } from "@/lib/api/publisher";

function article(id: string, sourceId: string): Article {
  return {
    id,
    sourceId,
    issueId: "issue-1",
    source: sourceId,
    title: id,
    dek: "",
    publishedAt: "",
    originalUrl: `https://${sourceId}.test/article/${id}`,
    reasonCode: "ISSUE_BALANCE",
    x: 0,
    y: 0,
    z: 0,
    sensationalism: 0,
    confidence: 0.8,
    scoreVersion: "score-1",
    analysisStatus: "READY",
    analysisProvider: "openai",
    claims: [],
  };
}

const articles = [article("a", "one"), article("b", "one"), article("c", "two"), article("d", "three"), article("e", "four")];

describe("comparison URL selection", () => {
  it("defaults to three distinct sources", () => {
    expect(defaultComparisonSelection(articles)).toEqual(["a", "c", "d"]);
    expect(defaultComparisonSelection([...articles].reverse())).toEqual(["a", "c", "d"]);
  });

  it("collapses desktop and mobile publisher domains even with different source records", () => {
    const desktop = { ...article("a", "desktop"), originalUrl: "https://www.paper.co.kr/news/1" };
    const mobile = { ...article("b", "mobile"), originalUrl: "https://m.paper.co.kr/news/2" };
    const other = { ...article("c", "other"), originalUrl: "https://other.co.kr/news/3" };
    expect(publisherIdentity(desktop)).toBe("paper.co.kr");
    expect(defaultComparisonSelection([desktop, mobile, other])).toEqual(["a", "c"]);
    expect(parseComparisonSelection("a,b", [desktop, mobile, other]).correctionNeeded).toBe(true);
    expect(publisherIdentity({ ...desktop, originalUrl: "" })).toBe("desktop");
  });

  it("restores a valid two-to-four article selection", () => {
    expect(parseComparisonSelection("b,c,d,e", articles)).toEqual({
      selected: ["b", "c", "d", "e"],
      correctionNeeded: false,
      error: null,
    });
  });

  it("corrects duplicate IDs and over-limit links to a safe default", () => {
    expect(parseComparisonSelection("a,a", articles).correctionNeeded).toBe(true);
    expect(parseComparisonSelection("a,b,c,d,e", articles)).toEqual({
      selected: ["a", "c", "d"],
      correctionNeeded: true,
      error: "TOO_MANY",
    });
  });

  it("corrects unknown IDs and selections that repeat a source", () => {
    expect(parseComparisonSelection("a,missing", articles)).toEqual({
      selected: ["a", "c", "d"],
      correctionNeeded: true,
      error: null,
    });
    expect(parseComparisonSelection("a,b", articles)).toEqual({
      selected: ["a", "c", "d"],
      correctionNeeded: true,
      error: null,
    });
  });

  it("accepts ready provider or direct Codex assessments with a sensationalism score", () => {
    expect(isComparisonReadyArticle(article("a", "one"))).toBe(true);
    expect(isComparisonReadyArticle({ ...article("a", "one"), analysisProvider: "codex" })).toBe(true);
    expect(isComparisonReadyArticle({ ...article("b", "two"), analysisStatus: "PROCESSING" })).toBe(false);
    expect(isComparisonReadyArticle({ ...article("c", "three"), analysisProvider: null })).toBe(false);
    expect(isComparisonReadyArticle({ ...article("d", "four"), sensationalism: null })).toBe(false);
  });
});
