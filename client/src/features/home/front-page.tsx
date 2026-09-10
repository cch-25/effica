"use client";

import Link from "next/link";
import { useIssuesQuery, useFeedQuery, useIssueArticleCollectionsQuery } from "@/lib/api/queries";
import { isMockMode } from "@/lib/api/mode";
import type { Article, Issue } from "@/lib/api/types";
import { IssueCard } from "@/features/issues/issue-card";
import { StatePanel } from "@/components/ui/state-panel";
import { compareIssueImportance, featuredIssueLimit, isFeaturedIssue } from "@/features/issues/issue-selection";

function NewspaperChart({ articles }: { articles: Article[] }) {
  const plotted = articles.filter((article) => article.analysisStatus === "READY" && article.sensationalism !== null).slice(0, 12);
  const labels: Array<{ x: number; y: number }> = [];
  const points = plotted.map((article) => {
    const x = 300 + Math.max(-100, Math.min(100, article.x)) * 2.62;
    const y = 206 - Math.max(0, Math.min(100, article.sensationalism ?? 0)) * 1.78;
    const candidates = [[0, 0], [0, -26], [26, 0], [-26, 0], [26, -26], [-26, -26], [0, -52]];
    const label = candidates.map(([dx, dy]) => ({ x: Math.max(50, Math.min(550, x + dx)), y: Math.max(40, Math.min(194, y + dy)) }))
      .find((point) => labels.every((other) => Math.hypot(point.x - other.x, point.y - other.y) >= 24)) ?? { x, y };
    labels.push(label);
    return { article, x, y, label };
  });
  return <figure className="front-chart">
    <svg viewBox="0 0 600 264" role="img" aria-labelledby="front-chart-title front-chart-description">
      <title id="front-chart-title">추천 기사의 편향성과 과장성</title>
      <desc id="front-chart-description">공개 분석이 있는 기사 {plotted.length}건. 가로축은 편향성 −100부터 +100, 세로축은 과장성 0부터 100입니다. 숫자는 아래 기사 목록과 같습니다.</desc>
      <defs><pattern id="newspaper-hatching" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(35)"><line x1="0" y1="0" x2="0" y2="6" stroke="#d5d5d5" strokeWidth="1" /></pattern></defs>
      <rect x="273" y="28" width="54" height="178" fill="url(#newspaper-hatching)" />
      {[0, 25, 50, 75, 100].map((value) => <g key={value}><line x1="38" y1={206 - value * 1.78} x2="562" y2={206 - value * 1.78} stroke="#c6c6c6" strokeDasharray={value === 0 ? undefined : "2 3"} /><text x="28" y={210 - value * 1.78} textAnchor="end">{value}</text></g>)}
      {[-100, -50, 0, 50, 100].map((value) => <g key={value}><line x1={300 + value * 2.62} y1="28" x2={300 + value * 2.62} y2="206" stroke={value === 0 ? "#333" : "#ddd"} /><text x={300 + value * 2.62} y="226" textAnchor="middle">{value > 0 ? "+" : ""}{value}</text></g>)}
      <text x="38" y="16">과장성</text><text x="38" y="250">좌측</text><text x="300" y="250" textAnchor="middle">편향성</text><text x="562" y="250" textAnchor="end">우측</text>
      {points.map(({ article, x, y, label }, index) => <g key={article.id}>
        <line x1={x} y1={y} x2={label.x} y2={label.y} stroke="#161616" /><circle cx={x} cy={y} r="2" fill="#161616" />
        <circle cx={label.x} cy={label.y} r="11" fill="#fff" stroke="#161616" strokeWidth="1.5" /><text x={label.x} y={label.y + 4} textAnchor="middle" fontWeight="700">{index + 1}</text>
      </g>)}
    </svg>
    <figcaption><strong>자료 도판</strong> 불러온 추천 기사 중 두 분석값이 공개된 {plotted.length}건. 빗금은 편향성 −10~+10 구간. 숫자는 아래 기사 목록이며 가까운 좌표는 연결선으로 구분합니다.</figcaption>
    {plotted.length > 0 && <ol className="front-chart__key">{plotted.map((article) => <li key={article.id}><Link href={`/articles/${article.id}`}><strong>{article.source}</strong> {article.title}</Link></li>)}</ol>}
  </figure>;
}

export function FrontPage({ fallbackIssues, fallbackArticles }: { fallbackIssues: Issue[]; fallbackArticles: Article[] }) {
  const issueQuery = useIssuesQuery();
  const feed = useFeedQuery();
  const issues = issueQuery.data?.items ?? (isMockMode() ? fallbackIssues : []);
  const articles = feed.data?.items ?? (isMockMode() ? fallbackArticles : []);
  const events = issues.filter(isFeaturedIssue).sort(compareIssueImportance).slice(0, featuredIssueLimit);
  const lead = events[0];
  const otherIssues = events.slice(1);
  const leadCollection = useIssueArticleCollectionsQuery(lead ? [lead.id] : []);
  const leadArticles = leadCollection.items.length ? leadCollection.items : articles.filter((a) => a.issueId === lead?.id);
  const dispatches = [...new Map(leadArticles.map((article) => [article.sourceId || article.source, article])).values()];
  const secondary = articles.find((article) => article.issueId !== lead?.id);
  const secondaryCollection = useIssueArticleCollectionsQuery(secondary?.issueId && secondary.issueId !== "unclustered" ? [secondary.issueId] : []);
  const brief = secondaryCollection.items.find((article) => article.id === secondary?.id) ?? secondary;
  return <>
    <div className="front-page">
      <section className="front-page__lead" aria-label="주요 이슈">
        <p className="edition-label">주요 이슈 <span>보도 비교</span></p>
        {issueQuery.isPending && !isMockMode() ? <StatePanel state="loading" /> : issueQuery.isError && !isMockMode() ? <StatePanel state="error" onRetry={() => void issueQuery.refetch()} /> : lead ? <>
          <h1><Link href={`/issues/${lead.id}`}>{lead.title}</Link></h1>
          <p className="front-page__dek">{lead.summary}</p>
          <div className="front-page__byline"><span>{lead.topic}</span><span>기사 {lead.articleIds.length}개 / 출처 {lead.sourceCount}곳</span><span>{lead.analysisStatus === "READY" ? "비교 가능" : "분석 준비 중"}</span></div>
          <div className="front-page__dispatches">{dispatches.slice(0, 3).map((article) => <article key={article.id}><p className="edition-label">{article.source}</p><h2><Link href={`/articles/${article.id}`}>{article.title}</Link></h2>{article.dek && <p>{article.dek}</p>}<Link className="text-link" href={`/articles/${article.id}`}>기사 분석 →</Link></article>)}</div>
          <Link className="front-page__read" href={`/issues/${lead.id}`}>같은 이슈의 보도 비교하기 →</Link>
        </> : <><h1>지금 살펴볼 주요 이슈</h1><StatePanel state="empty" /></>}
        {brief && <article className="front-page__secondary"><p className="edition-label">다른 주제의 보도 <span>{brief.source}</span></p><h2><Link href={`/articles/${brief.id}`}>{brief.title}</Link></h2>{brief.dek && <p>{brief.dek}</p>}<Link className="text-link" href={`/articles/${brief.id}`}>기사 분석 →</Link></article>}
      </section>
      <section className="front-page__data" aria-labelledby="front-data-title">
        <p className="edition-label">자료로 읽는 뉴스 <span>편향성과 과장성</span></p><h2 id="front-data-title">기사마다 다른 관점, 좌표로 읽다</h2>
        {feed.isPending && !isMockMode() ? <StatePanel state="loading" /> : feed.isError && !isMockMode() ? <StatePanel state="error" onRetry={() => void feed.refetch()} /> : <NewspaperChart articles={articles} />}
        <Link className="front-page__read" href="/visualization">기사 관점 지도에서 자세히 →</Link>
      </section>
    </div>
    <aside className="front-page__rail" aria-label="독자 길잡이"><h2>보도 읽기</h2><p>같은 사건도 고른 사실과 인용한 말에 따라 다르게 전해집니다. 두 기사의 공통 사실과 서로 다른 주장을 함께 살펴보세요.</p><p>도표는 기사 표현에 대한 분석입니다. 사실 여부의 판정이나 독자의 정치성향을 뜻하지 않습니다.</p><Link className="text-link" href="/issues">이슈 비교 시작 →</Link></aside>
    {otherIssues.length > 0 && <section className="home-section home-section--issues" aria-label="함께 살펴볼 이슈"><div className="section-head"><h2>함께 살펴볼 이슈</h2><span>다른 사건의 쟁점</span></div><div className="newspaper-briefs">{otherIssues.map((issue) => <IssueCard key={issue.id} issue={issue} />)}</div></section>}
  </>;
}
