"use client";

import { ArticleCard } from "./article-card";
import { useFeedQuery } from "@/lib/api/queries";
import type { Article } from "@/lib/api/types";

export function FeedGrid({ fallback }: { fallback: Article[] }) {
  const feed = useFeedQuery();
  const articles = feed.data?.items ?? fallback;
  return <div className="grid grid--2">{articles.map((article) => <ArticleCard key={article.id} article={article} />)}</div>;
}
