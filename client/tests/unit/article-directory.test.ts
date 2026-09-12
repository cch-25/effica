import { describe, expect, it, vi } from "vitest";
import { collectPages, directoryEntries, loadDirectoryArticles, loadDirectoryIssues } from "@/features/articles/article-directory-data";
import { apiRequest } from "@/lib/api/client";
import { articles, issues } from "@/mocks/fixtures/content";

vi.mock("@/lib/api/client", () => ({ apiRequest: vi.fn() }));

describe("public article directory", () => {
  it("follows cursors through empty pages without losing later results", async () => {
    const load = vi.fn().mockResolvedValueOnce({ items: ["first"], next_cursor: "page2" })
      .mockResolvedValueOnce({ items: [], next_cursor: "page3" })
      .mockResolvedValueOnce({ items: ["last"], next_cursor: null });
    await expect(collectPages(load)).resolves.toEqual(["first", "last"]);
    expect(load.mock.calls).toEqual([[null], ["page2"], ["page3"]]);
  });

  it("fails explicitly on a repeated cursor instead of looping or claiming completion", async () => {
    await expect(collectPages(async () => ({ items: [], next_cursor: "same" }))).rejects.toThrow("페이지");
  });

  it("deduplicates shared articles while retaining every category membership and date order", () => {
    const older = { ...articles[0], id: "shared", publishedAt: "2026-09-01T00:00:00Z" };
    const newer = { ...articles[1], id: "newer", publishedAt: "2026-09-11T00:00:00Z" };
    const groups = [
      { ...issues[0], id: "politics", topic: "정치", articleIds: ["shared", "newer"] },
      { ...issues[0], id: "economy", topic: "경제", articleIds: ["shared"] },
    ];
    const rows = directoryEntries([older, newer, older], groups);
    expect(rows.map(({ article }) => article.id)).toEqual(["newer", "shared"]);
    expect(rows[1].issues.map((issue) => issue.topic)).toEqual(["정치", "경제"]);
  });

  it("loads later issue and global article pages", async () => {
    const request = vi.mocked(apiRequest);
    request.mockReset();
    request.mockResolvedValueOnce({ items: [], next_cursor: "next-issues" }).mockResolvedValueOnce({ items: [], next_cursor: null });
    await loadDirectoryIssues(new AbortController().signal);
    expect(request.mock.calls[1][0]).toContain("cursor=next-issues");

    request.mockResolvedValueOnce({ items: [], next_cursor: "next-articles" }).mockResolvedValueOnce({ items: [], next_cursor: null });
    await expect(loadDirectoryArticles(new AbortController().signal)).resolves.toEqual({ articles: [], failedIssueIds: [] });
    expect(request.mock.calls.some(([url]) => url.includes("cursor=next-articles"))).toBe(true);
    expect(request.mock.calls.some(([url]) => url.startsWith("/articles?"))).toBe(true);
  });
});
