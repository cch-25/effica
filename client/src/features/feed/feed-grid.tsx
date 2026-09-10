"use client";

import { ArticleCard } from "./article-card";
import { useFeedQuery, useIssueArticleCollectionsQuery } from "@/lib/api/queries";
import type { Article } from "@/lib/api/types";
import { isMockMode } from "@/lib/api/mode";
import { StatePanel } from "@/components/ui/state-panel";
import { Button } from "@/components/ui/button";

export function FeedGrid({ fallback }: { fallback: Article[] }) {
  const feed = useFeedQuery();
  const articles = feed.data?.items ?? (isMockMode() ? fallback : []);
  const collection = useIssueArticleCollectionsQuery(articles.map((article) => article.issueId).filter((id) => id && id !== "unclustered"));
  const summaries = new Map(collection.items.map((article) => [article.id, article]));
  if (feed.isPending && !isMockMode()) return <StatePanel state="loading" />;
  if (feed.isError && !isMockMode()) return <StatePanel state="error" onRetry={() => void feed.refetch()} />;
  if (articles.length === 0) return <StatePanel state="empty" />;
  return (
    <>
      <div className="grid grid--2">{articles.map((article) => <ArticleCard key={article.id} article={{ ...article, dek: summaries.get(article.id)?.dek || article.dek, originalUrl: summaries.get(article.id)?.originalUrl || article.originalUrl }} />)}</div>
      {feed.hasNextPage && <div className="form-actions"><Button variant="secondary" onClick={() => void feed.fetchNextPage()} disabled={feed.isFetchingNextPage}>{feed.isFetchingNextPage ? "불러오는 중…" : "더 보기"}</Button></div>}
    </>
  );
}
