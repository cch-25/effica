"use client";

import { PageHeader } from "@/components/layout/page-header";
import { StatePanel } from "@/components/ui/state-panel";
import { ArticleCard } from "@/features/feed/article-card";
import { useIssueArticlesQuery, useIssueQuery } from "@/lib/api/queries";

export function RealIssueDetail({ issueId }: { issueId: string }) {
  const issueQuery = useIssueQuery(issueId);
  const articlesQuery = useIssueArticlesQuery(issueId);
  if (issueQuery.isPending || articlesQuery.isPending) return <StatePanel state="loading" />;
  if (issueQuery.isError || articlesQuery.isError) return <StatePanel state="error" />;

  const issue = issueQuery.data;
  const articles = articlesQuery.data.items;
  return (
    <>
      <PageHeader eyebrow={`Issue / ${issue.topic}`} title={issue.title} description={issue.summary} />
      {articles.length === 0 && <StatePanel state="processing" />}
      {articles.length > 0 && <div className="grid grid--2">{articles.map((article) => <ArticleCard key={article.id} article={article} />)}</div>}
    </>
  );
}
