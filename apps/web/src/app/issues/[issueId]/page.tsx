import { notFound } from "next/navigation";
import { articles, issues } from "@/mocks/fixtures/content";
import { RealIssueDetail } from "@/features/issues/real-issue-detail";
import { isMockMode } from "@/lib/api/mode";
import { IssueComparison } from "@/features/issues/comparison/issue-comparison";

export default async function IssueDetailPage({ params, searchParams }: { params: Promise<{ issueId: string }>; searchParams: Promise<{ articles?: string | string[] }> }) {
  const { issueId } = await params;
  const rawArticles = (await searchParams).articles;
  const initialArticles = Array.isArray(rawArticles) ? rawArticles[0] : rawArticles;
  if (!isMockMode()) return <RealIssueDetail issueId={issueId} initialArticles={initialArticles} />;
  const issue = issues.find((item) => item.id === issueId);
  if (!issue) notFound();
  const issueArticles = articles.filter((article) => article.issueId === issue.id);
  return <IssueComparison issue={issue} articles={issueArticles} initialArticles={initialArticles} />;
}
