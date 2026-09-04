"use client";

import { ArticleCard } from "./article-card";
import { useFeedQuery } from "@/lib/api/queries";
import type { Article } from "@/lib/api/types";
import { isMockMode } from "@/lib/api/mode";
import { StatePanel } from "@/components/ui/state-panel";
import { Button } from "@/components/ui/button";

export function FeedGrid({ fallback }: { fallback: Article[] }) {
  const feed = useFeedQuery();
  if (feed.isPending && !isMockMode()) return <StatePanel state="loading" />;
  if (feed.isError && !isMockMode()) return <StatePanel state="error" onRetry={() => void feed.refetch()} />;
  const articles = feed.data?.items ?? (isMockMode() ? fallback : []);
  if (articles.length === 0) return <StatePanel state="empty" />;
  return (
    <>
      <div className="grid grid--2">{articles.map((article) => <ArticleCard key={article.id} article={article} />)}</div>
      {feed.hasNextPage && <div className="form-actions"><Button variant="secondary" onClick={() => void feed.fetchNextPage()} disabled={feed.isFetchingNextPage}>{feed.isFetchingNextPage ? "불러오는 중…" : "더 보기"}</Button></div>}
    </>
  );
}
