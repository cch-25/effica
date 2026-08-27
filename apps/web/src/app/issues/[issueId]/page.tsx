import { notFound } from "next/navigation";
import { PageHeader } from "@/components/layout/page-header";
import { ArticleCard } from "@/features/feed/article-card";
import { articles, issues } from "@/mocks/fixtures/content";
import { RealIssueDetail } from "@/features/issues/real-issue-detail";
import { isMockMode } from "@/lib/api/mode";
import { IssueReadiness } from "@/features/issues/issue-readiness";

export default async function IssueDetailPage({ params, searchParams }: { params: Promise<{ issueId: string }>; searchParams: Promise<{ articles?: string | string[] }> }) {
  const { issueId } = await params;
  const rawArticles = (await searchParams).articles;
  const initialArticles = Array.isArray(rawArticles) ? rawArticles[0] : rawArticles;
  if (!isMockMode()) return <RealIssueDetail issueId={issueId} initialArticles={initialArticles} />;
  const issue = issues.find((item) => item.id === issueId);
  if (!issue) notFound();
  const issueArticles = articles.filter((article) => article.issueId === issue.id);
  const hasArticles = issueArticles.length > 0;

  return (
    <>
      <PageHeader eyebrow={`Mock 전용 이슈 / ${issue.topic}`} title={issue.title} description={issue.summary} />
      {!hasArticles && <IssueReadiness articleCount={issue.articleIds.length} sourceCount={issue.sourceCount} />}
      <p className="notice">Mock 화면에는 실제 집계가 없는 평균 점수나 독자 수치를 표시하지 않습니다.</p>
      {hasArticles && <div className="grid grid--2">{issueArticles.map((article) => <ArticleCard key={article.id} article={article} />)}</div>}
    </>
  );
}
