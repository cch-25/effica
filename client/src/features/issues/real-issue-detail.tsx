"use client";

import Link from "next/link";
import { StatePanel } from "@/components/ui/state-panel";
import { ApiError } from "@/lib/api/client";
import { useIssueArticlesQuery, useIssueQuery } from "@/lib/api/queries";
import { IssueComparison } from "./comparison/issue-comparison";

export function RealIssueDetail({ issueId, initialArticles }: { issueId: string; initialArticles?: string }) {
  const issueQuery = useIssueQuery(issueId);
  const articlesQuery = useIssueArticlesQuery(issueId);
  const unavailable = [issueQuery.error, articlesQuery.error].some((error) => error instanceof ApiError && [404, 410].includes(error.status));
  if (unavailable) return <section className="issue-readiness" role="status"><div><h1>현재 발행 목록에 없는 이슈입니다.</h1><p>발행 목록이 바뀌었거나 공개 기간이 지났습니다.</p><Link href="/issues">현재 이슈 보기</Link></div></section>;
  if (issueQuery.isPending || articlesQuery.isPending) return <StatePanel state="loading" />;
  if (issueQuery.isError || articlesQuery.isError) return <StatePanel state="error" />;

  const issue = issueQuery.data;
  const articles = articlesQuery.data.items;
  const comparisonKey = `${issue.id}:${articles.map((row) => `${row.id}:${row.analysisStatus}:${row.analysisProvider}:${row.scoreVersion}:${row.sensationalism}`).join(",")}`;
  return <IssueComparison key={comparisonKey} issue={issue} articles={articles} initialArticles={initialArticles} />;
}
