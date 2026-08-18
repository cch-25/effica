import { notFound } from "next/navigation";
import { PageHeader } from "@/components/layout/page-header";
import { ArticleCard } from "@/features/feed/article-card";
import { StatePanel } from "@/components/ui/state-panel";
import { articles, issues } from "@/mocks/fixtures/content";
import { RealIssueDetail } from "@/features/issues/real-issue-detail";
import { isMockMode } from "@/lib/api/mode";
import { clampScore, formatBiasScore, formatConfidence, formatSensationalismScore } from "@/lib/api/formatters";

export default async function IssueDetailPage({ params }: { params: Promise<{ issueId: string }> }) {
  const { issueId } = await params;
  if (!isMockMode()) return <RealIssueDetail issueId={issueId} />;
  const issue = issues.find((item) => item.id === issueId);
  if (!issue) notFound();
  const issueArticles = articles.filter((article) => article.issueId === issue.id);
  const average = (key: "x" | "sensationalism" | "confidence") => issueArticles.length
    ? issueArticles.reduce((sum, article) => sum + (article[key] ?? 0), 0) / issueArticles.length
    : 0;
  const bias = Math.round(average("x"));
  const sensationalism = Math.round(average("sensationalism"));
  const confidence = average("confidence");
  const hasArticles = issueArticles.length > 0;

  return (
    <>
      <PageHeader eyebrow={`이슈 / ${issue.topic}`} title={issue.title} description={issue.summary} />
      {!hasArticles && <StatePanel state="processing" />}
      {issue.status === "balanced" && hasArticles && (
        <section className="card card--padded" style={{ marginBottom: "1rem" }}>
          <div className="section-head" style={{ marginTop: 0 }}><h2>이슈 기사 LLM 평가</h2><span className="badge">score-v12</span></div>
          <p style={{ color: "var(--muted)" }}>이 이슈에 포함된 기사들의 평균값입니다. 분석 신뢰도 {formatConfidence(confidence)}</p>
          <div className="grid grid--2">
            <div className="axis" aria-label={`편향성 ${formatBiasScore(bias)}`}><div className="axis__head"><strong>편향성</strong><span>{formatBiasScore(bias)}</span></div><div className="axis__labels"><span>좌편향</span><span>우편향</span></div><div className="axis__track axis__track--bias" aria-hidden="true"><span className="axis__center" /><span className="axis__marker" style={{ left: `${(clampScore(bias) + 100) / 2}%` }} /></div></div>
            <div className="axis" aria-label={`과장성 ${formatSensationalismScore(sensationalism)}`}><div className="axis__head"><strong>과장성</strong><span>{formatSensationalismScore(sensationalism)}</span></div><div className="axis__labels"><span>낮음</span><span>높음</span></div><div className="axis__track" aria-hidden="true"><span className="axis__marker" style={{ left: `${clampScore(sensationalism, 0, 100)}%` }} /></div></div>
          </div>
        </section>
      )}
      {hasArticles && <div className="grid grid--2">{issueArticles.map((article) => <ArticleCard key={article.id} article={article} />)}</div>}
      {issue.status === "balanced" && hasArticles && (
        <section className="card card--padded" style={{ marginTop: "1rem" }}><h2>핵심 주장 비교</h2><div className="table-wrap"><table className="data-table"><thead><tr><th>출처</th><th>주장</th><th>LLM 평가 편향성</th><th>LLM 평가 과장성</th></tr></thead><tbody>{issueArticles.flatMap((article) => article.claims.map((claim, index) => <tr key={`${article.id}-${index}`}><td>{article.source}</td><td>{claim}</td><td>{formatBiasScore(article.x)}</td><td>{formatSensationalismScore(article.sensationalism)}</td></tr>))}</tbody></table></div></section>
      )}
    </>
  );
}
