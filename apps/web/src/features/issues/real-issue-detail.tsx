"use client";

import { StatePanel } from "@/components/ui/state-panel";
import { useIssueArticlesQuery, useIssueQuery } from "@/lib/api/queries";
import { IssueComparison } from "./comparison/issue-comparison";
import { IssueReadiness } from "./issue-readiness";

export function RealIssueDetail({ issueId, initialArticles }: { issueId: string; initialArticles?: string }) {
  const issueQuery = useIssueQuery(issueId);
  const articlesQuery = useIssueArticlesQuery(issueId);
  if (issueQuery.isPending || articlesQuery.isPending) return <StatePanel state="loading" />;
  if (issueQuery.isError || articlesQuery.isError) return <StatePanel state="error" />;

  const issue = issueQuery.data;
  const articles = articlesQuery.data.items;
  if (articles.length === 0) return <IssueReadiness articleCount={issue.articleIds.length} sourceCount={issue.sourceCount} />;
  const comparisonKey = `${issue.id}:${initialArticles ?? ""}:${articles.map((row) => row.id).join(",")}`;
  return <IssueComparison key={comparisonKey} issue={issue} articles={articles} initialArticles={initialArticles} />;
}
