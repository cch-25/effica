import { describe, expect, it } from "vitest";
import { defaultComparisonSelection, isComparisonReadyArticle, parseComparisonSelection } from "@/features/issues/comparison/selection";
import type { Article } from "@/lib/api/types";

function article(id: string, sourceId: string): Article {
  return {
    id,
    sourceId,
    issueId: "issue-1",
    source: sourceId,
    title: id,
    dek: "",
    publishedAt: "",
    originalUrl: "https://example.test",
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

  it("only accepts ready OpenAI articles with a sensationalism score", () => {
    expect(isComparisonReadyArticle(article("a", "one"))).toBe(true);
    expect(isComparisonReadyArticle({ ...article("b", "two"), analysisStatus: "PROCESSING" })).toBe(false);
    expect(isComparisonReadyArticle({ ...article("c", "three"), analysisProvider: null })).toBe(false);
    expect(isComparisonReadyArticle({ ...article("d", "four"), sensationalism: null })).toBe(false);
  });
});
