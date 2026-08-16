import { notFound } from "next/navigation";
import { PageHeader } from "@/components/layout/page-header";
import { ArticleCard } from "@/features/feed/article-card";
import { StatePanel } from "@/components/ui/state-panel";
import { ScoreAxis } from "@/components/ui/score-axis";
import { articles, issues } from "@/mocks/fixtures/content";

export default async function IssueDetailPage({ params }: { params: Promise<{ issueId: string }> }) {
  const { issueId } = await params;
  const issue = issues.find((item) => item.id === issueId);
  if (!issue) notFound();
  const issueArticles = articles.filter((article) => article.issueId === issue.id);

  return (
    <>
      <PageHeader eyebrow={`Issue / ${issue.topic}`} title={issue.title} description={issue.summary} />
      {issue.status === "preparing" && <StatePanel state="processing" />}
      {issue.status === "balanced" && (
        <>
          <section className="card card--padded" style={{ marginBottom: "1rem" }}>
            <div className="section-head" style={{ marginTop: 0 }}><h2>이슈 안의 관점 분포</h2><span className="badge">score-v12</span></div>
            <div className="grid grid--3"><ScoreAxis axis="x" value={7} confidence={0.82} /><ScoreAxis axis="y" value={2} confidence={0.77} /><ScoreAxis axis="z" value={-1} confidence={0.7} /></div>
          </section>
          <div className="grid grid--2">{issueArticles.map((article) => <ArticleCard key={article.id} article={article} />)}</div>
          <section className="card card--padded" style={{ marginTop: "1rem" }}><h2>핵심 주장 비교</h2><div className="table-wrap"><table className="data-table"><thead><tr><th>출처</th><th>주장</th><th>경제축</th><th>과장성</th></tr></thead><tbody>{issueArticles.flatMap((article) => article.claims.map((claim, index) => <tr key={`${article.id}-${index}`}><td>{article.source}</td><td>{claim}</td><td>{article.x > 0 ? `+${article.x}` : article.x}</td><td>{article.sensationalism}</td></tr>))}</tbody></table></div></section>
        </>
      )}
    </>
  );
}
