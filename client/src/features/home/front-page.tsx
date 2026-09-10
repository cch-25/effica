"use client";

import Link from "next/link";
import { useIssuesQuery, useFeedQuery, useIssueArticleCollectionsQuery } from "@/lib/api/queries";
import { isMockMode } from "@/lib/api/mode";
import type { Article, Issue } from "@/lib/api/types";
import { IssueCard } from "@/features/issues/issue-card";
import { StatePanel } from "@/components/ui/state-panel";

export function FrontPage({ fallbackIssues, fallbackArticles }: { fallbackIssues: Issue[]; fallbackArticles: Article[] }) {
  const issueQuery = useIssuesQuery();
  const feed = useFeedQuery();
  const issues = issueQuery.data?.items ?? (isMockMode() ? fallbackIssues : []);
  const articles = feed.data?.items ?? (isMockMode() ? fallbackArticles : []);
  const events = issues.filter((issue) => issue.kind === "EVENT" && issue.freshnessStatus === "CURRENT")
    .sort((a, b) => Number(b.analysisStatus === "READY") - Number(a.analysisStatus === "READY") || (a.editorialPriority ?? 999) - (b.editorialPriority ?? 999));
  const lead = events[0];
  const otherIssues = events.slice(1, 4);
  const leadCollection = useIssueArticleCollectionsQuery(lead ? [lead.id] : []);
  const dispatches = leadCollection.items.length ? leadCollection.items : articles.filter((a) => a.issueId === lead?.id);
  const ready = articles.filter((article) => article.analysisStatus === "READY");
  const bins = [ready.filter((a) => a.x < -10).length, ready.filter((a) => a.x >= -10 && a.x <= 10).length, ready.filter((a) => a.x > 10).length];
  const max = Math.max(1, ...bins);
  return <>
    <div className="front-page">
      <section className="front-page__lead" aria-label="주요 이슈">
        <p className="edition-label">주요 이슈 <span>보도 비교</span></p>
        {issueQuery.isPending && !isMockMode() ? <StatePanel state="loading" /> : issueQuery.isError && !isMockMode() ? <StatePanel state="error" onRetry={() => void issueQuery.refetch()} /> : lead ? <>
          <h1><Link href={`/issues/${lead.id}`}>{lead.title}</Link></h1>
          <p className="front-page__dek">{lead.summary}</p>
          <div className="front-page__byline"><span>{lead.topic}</span><span>기사 {lead.articleIds.length}개 / 출처 {lead.sourceCount}곳</span><span>{lead.analysisStatus === "READY" ? "비교 가능" : "분석 준비 중"}</span></div>
          <div className="front-page__dispatches">{dispatches.slice(0, 2).map((article) => <article key={article.id}><p className="edition-label">{article.source}</p><h2><Link href={`/articles/${article.id}`}>{article.title}</Link></h2><p>{article.dek}</p><Link className="text-link" href={`/articles/${article.id}`}>기사 분석 →</Link></article>)}</div>
          <Link className="front-page__read" href={`/issues/${lead.id}`}>같은 이슈의 보도 비교하기 →</Link>
        </> : <><h1>지금 살펴볼 주요 이슈</h1><StatePanel state="empty" /></>}
      </section>
      <section className="front-page__data" aria-labelledby="front-data-title">
        <p className="edition-label">자료로 읽는 뉴스</p><h2 id="front-data-title">기사의 관점은<br />어디에 놓여 있나</h2>
        {feed.isPending && !isMockMode() ? <StatePanel state="loading" /> : feed.isError && !isMockMode() ? <StatePanel state="error" onRetry={() => void feed.refetch()} /> : <figure className="front-chart"><figcaption>불러온 추천 기사의 편향 분포</figcaption><div className="front-chart__plot" role="img" aria-label={`공개 분석 기사 ${ready.length}건. 좌측 ${bins[0]}건, 중앙 ${bins[1]}건, 우측 ${bins[2]}건.`}>{bins.map((count, i) => <div className="front-chart__column" key={i}><strong>{count}<small>건</small></strong><span className={`front-chart__bar front-chart__bar--${i}`} style={{ height: `${count / max * 116}px` }} /><span>{["좌측", "중앙", "우측"][i]}</span></div>)}</div><p>공개 분석 {ready.length}건 기준 / 중앙 −10~+10</p></figure>}
        <p className="front-page__caption">기사의 표현을 분석한 값입니다. 독자의 정치성향을 나타내지 않습니다.</p>
        <Link className="text-link" href="/visualization">기사 관점 지도에서 자세히 →</Link>
      </section>
      <aside className="front-page__rail" aria-label="독자 길잡이"><p className="edition-label">읽기 안내</p><h2>하나의 사건,<br />여러 개의 시선</h2><p>어떤 사실을 골랐는지, 누구의 말을 인용했는지. 같은 사건을 다룬 기사도 전하는 방식은 다릅니다.</p><p>이슈를 고른 뒤 두 기사를 나란히 읽어 보세요. 공통된 사실과 서로 다른 주장을 함께 살필 수 있습니다.</p><Link className="front-page__read" href="/issues">이슈 비교 시작 →</Link><nav className="edition-directory" aria-label="지면 안내"><Link href="/issues"><span>보도 비교</span><span>02</span></Link><Link href="/visualization"><span>자료 분석</span><span>03</span></Link><Link href="/progress"><span>독자 기록</span><span>04</span></Link></nav></aside>
    </div>
    {otherIssues.length > 0 && <section className="home-section home-section--issues" aria-label="함께 살펴볼 이슈"><div className="section-head"><h2>함께 살펴볼 이슈</h2><span>다른 사건의 쟁점</span></div><div className="newspaper-briefs">{otherIssues.map((issue) => <IssueCard key={issue.id} issue={issue} />)}</div></section>}
  </>;
}
