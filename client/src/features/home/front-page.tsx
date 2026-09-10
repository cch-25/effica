"use client";

import Link from "next/link";
import Image from "next/image";
import { useState } from "react";
import { useIssuesQuery, useIssueArticleCollectionsQuery } from "@/lib/api/queries";
import { isMockMode } from "@/lib/api/mode";
import type { Article, Issue } from "@/lib/api/types";
import { publisherIdentity } from "@/lib/api/publisher";
import { IssueCard } from "@/features/issues/issue-card";
import { StatePanel } from "@/components/ui/state-panel";
import { compareIssueImportance, featuredIssueLimit, isFeaturedIssue } from "@/features/issues/issue-selection";

function PublisherPhoto({ article }: { article: Article }) {
  const [failed, setFailed] = useState(false);
  if (!article.imageUrl || failed) return null;
  return <figure className="news-photo"><a href={article.originalUrl} target="_blank" rel="noreferrer"><Image src={article.imageUrl} alt={`${article.source} 원문 기사 사진`} width={800} height={500} unoptimized referrerPolicy="no-referrer" onError={() => setFailed(true)} /></a><figcaption><span>{article.title}</span><a href={article.originalUrl} target="_blank" rel="noreferrer">사진 출처: {article.source}</a></figcaption></figure>;
}

function NewspaperChart({ articles }: { articles: Article[] }) {
  const plotted = articles.filter((article) => article.analysisStatus === "READY" && article.sensationalism !== null).slice(0, 6);
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
      <title id="front-chart-title">공개 이슈 기사의 편향성과 과장성</title>
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
    <figcaption>공개 분석 {plotted.length}건. 빗금은 편향성 −10~+10 구간이며, 숫자는 기사 목록과 같습니다.</figcaption>
    {plotted.length > 0 && <ol className="front-chart__key">{plotted.map((article) => <li key={article.id}><Link href={`/articles/${article.id}`}><strong>{article.source}</strong> {article.title}</Link></li>)}</ol>}
  </figure>;
}

export function FrontPage({ fallbackIssues, fallbackArticles }: { fallbackIssues: Issue[]; fallbackArticles: Article[] }) {
  const issueQuery = useIssuesQuery();
  const issues = issueQuery.data?.items ?? (isMockMode() ? fallbackIssues : []);
  const events = issues.filter(isFeaturedIssue).sort(compareIssueImportance).slice(0, featuredIssueLimit);
  const lead = events[0];
  const otherIssues = events.slice(1);
  const collection = useIssueArticleCollectionsQuery(events.map((issue) => issue.id));
  const articles = collection.items.length ? collection.items : isMockMode() ? fallbackArticles : [];
  const leadArticles = articles.filter((article) => lead?.articleIds.includes(article.id));
  const dispatches = [...new Map(leadArticles.map((article) => [publisherIdentity(article), article])).values()];
  const photo = leadArticles.find((article) => article.imageUrl);
  const plotted = articles.filter((article) => article.analysisStatus === "READY" && article.sensationalism !== null);
  return <>
    <div className="front-page">
      <section className="front-page__lead" aria-label="주요 이슈">
        <p className="edition-label">주요 이슈 <span>보도 비교</span></p>
        {issueQuery.isPending && !isMockMode() ? <StatePanel state="loading" /> : issueQuery.isError && !isMockMode() ? <StatePanel state="error" onRetry={() => void issueQuery.refetch()} /> : lead ? <>
          <div className="front-page__opening"><div>
          <h1><Link href={`/issues/${lead.id}`}>{lead.title}</Link></h1>
          <p className="front-page__dek">{lead.summary}</p>
          <div className="front-page__byline"><span>{lead.topic}</span><span>기사 {lead.articleIds.length}개 / 출처 {lead.sourceCount}곳</span><span>{lead.analysisStatus === "READY" ? "비교 가능" : "분석 준비 중"}</span></div>
          <Link className="front-page__read" href={`/issues/${lead.id}`}>같은 이슈의 보도 비교하기 →</Link>
          </div>{photo && <PublisherPhoto key={photo.id} article={photo} />}</div>
          <div className="front-page__dispatches">{dispatches.slice(0, 3).map((article) => <article key={article.id}><p className="edition-label">{article.source}</p><h2><Link href={`/articles/${article.id}`}>{article.title}</Link></h2>{article.dek && <p>{article.dek}</p>}<Link className="text-link" href={`/articles/${article.id}`}>기사 분석 →</Link></article>)}</div>
        </> : <><h1>지금 살펴볼 주요 이슈</h1><StatePanel state="empty" /></>}
      </section>
    </div>
    {otherIssues.length > 0 && <section className="home-section home-section--issues" aria-label="함께 살펴볼 이슈"><div className="section-head"><h2>함께 살펴볼 이슈</h2><span>다른 사건의 쟁점</span></div><div className="newspaper-briefs">{otherIssues.map((issue) => <IssueCard key={issue.id} issue={issue} />)}</div></section>}
    {articles.length > 3 && <section className="home-section" aria-label="전체 이슈 기사"><div className="section-head"><h2>언론사별 보도</h2><span>공개 이슈 {events.length}개 / 기사 {articles.length}개</span></div><div className="edition-articles">{articles.filter((article) => !dispatches.slice(0, 3).some((leadArticle) => leadArticle.id === article.id)).map((article) => <article key={article.id}><p className="edition-label">{article.source}</p><h2><Link href={`/articles/${article.id}`}>{article.title}</Link></h2><p>{article.dek}</p><Link className="text-link" href={`/articles/${article.id}`}>기사 분석 →</Link></article>)}</div></section>}
    {plotted.length >= 3 && <section className="front-page__analysis" aria-labelledby="front-data-title"><div><p className="edition-label">자료로 읽는 뉴스</p><h2 id="front-data-title">보도 관점 비교</h2><ol className="analysis-story-index">{plotted.slice(0, 6).map((article) => <li key={article.id}><Link href={`/articles/${article.id}`}><strong>{article.source}</strong> {article.title}</Link></li>)}</ol><Link className="front-page__read" href="/visualization">기사 관점 지도에서 자세히 →</Link></div><NewspaperChart articles={articles} /></section>}
  </>;
}
