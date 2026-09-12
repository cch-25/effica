"use client";

import { useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { useIssueArticlesQuery } from "@/lib/api/queries";
import type { Article } from "@/lib/api/types";

type Props = { article: Article; relatedArticles?: Article[] };

export function ArticlePerspectiveMap({ article, relatedArticles }: Props) {
  const hasIssue = article.issueId !== "unclustered";
  const ready = article.analysisStatus === "READY";
  const query = useIssueArticlesQuery(article.issueId, ready && hasIssue);
  const candidates = query.data?.items ?? relatedArticles ?? [];
  const articles = [...new Map([
    article,
    ...candidates.filter((item) => hasIssue && item.issueId === article.issueId && item.id !== article.id),
  ].filter((item) => item.analysisStatus === "READY").map((item) => [item.id, item])).values()];

  return <section id="perspective-map" className="article-perspective-map perspective-workspace" aria-labelledby="article-perspective-title">
    <header className="article-perspective-map__heading">
      <h2 id="article-perspective-title">기사 관점 지도</h2>
      <p>읽고 있는 기사의 위치를 확인하고, 같은 이슈의 다른 보도와 비교합니다.</p>
    </header>
    {!ready ? <p className="article-perspective-map__status" role="status">{article.analysisStatus === "UNTRUSTED" ? "이 기사는 분석 공개 기준을 충족하지 않아 좌표를 표시하지 않습니다." : "이 기사의 분석이 준비되면 관점 좌표를 표시합니다."}</p> : <>
      {relatedArticles === undefined && hasIssue && query.isPending ? <p className="article-perspective-map__status" role="status">같은 이슈의 다른 보도를 불러오고 있습니다.</p> : null}
      {hasIssue && query.isError ? <div className="article-perspective-map__status" role="status">다른 보도를 새로 불러오지 못했습니다. <Button variant="ghost" onClick={() => void query.refetch()}>다시 불러오기</Button></div> : null}
      {(relatedArticles !== undefined || !hasIssue || query.isSuccess) && articles.length === 1 ? <p className="article-perspective-map__status">같은 이슈에서 비교할 분석 기사가 아직 없어 이 기사만 표시합니다.</p> : null}
      <ArticlePerspectiveContent key={article.id} article={article} articles={articles} />
    </>}
  </section>;
}

function ArticlePerspectiveContent({ article, articles }: { article: Article; articles: Article[] }) {
  const [selectedId, setSelectedId] = useState(article.id);
  const selected = articles.find((item) => item.id === selectedId) ?? article;
  return <div className="ux-scatter-layout">
    <svg className="ux-scatter" viewBox="0 0 560 350" role="img" aria-label="기사 관점: 가로 편향성 -100부터 100, 세로 과장성 0부터 100. 점이 진할수록 분석 신뢰도가 높습니다.">
      <path d="M60 25V290H510 M285 25V290" fill="none" stroke="currentColor" opacity=".25" />
      {[0, 50, 100].map((value) => <g key={value}><path d={`M60 ${290 - value * 2.5}H510`} stroke="currentColor" opacity=".12" /><text x="48" y={295 - value * 2.5} textAnchor="end">{value}</text></g>)}
      <text x="60" y="320">좌편향 -100</text><text x="285" y="320" textAnchor="middle">중립 0</text><text x="510" y="320" textAnchor="end">우편향 +100</text><text x="60" y="18">과장성</text>
      {articles.filter((item) => item.sensationalism !== null).map((item, index) => <g key={item.id}>
        <circle cx={60 + (item.x + 100) * 2.25} cy={290 - item.sensationalism! * 2.5} r={selected.id === item.id ? 9 : 7} fill="var(--accent)" opacity={.35 + item.confidence * .65} stroke={selected.id === item.id ? "currentColor" : "none"} strokeWidth="2"><title>{`${index + 1}. ${item.source}: 편향성 ${item.x}, 과장성 ${item.sensationalism}, 신뢰도 ${Math.round(item.confidence * 100)}%`}</title></circle>
      </g>)}
    </svg>
    <div>{selected.sensationalism === null && <p>과장성 측정값이 없어 이 기사는 지도에 점으로 표시하지 않습니다.</p>}<p>점을 가리키면 점수를 볼 수 있습니다. 겹친 기사도 아래 목록에서 각각 선택할 수 있습니다.</p><div className="ux-scatter-choices" role="group" aria-label="지도 기사 선택">{articles.map((item, index) => <Button key={item.id} variant="ghost" aria-pressed={selected.id === item.id} onClick={() => setSelectedId(item.id)}>{index + 1}. {item.source}</Button>)}</div><h3>{selected.title}</h3><p>편향성 {selected.x > 0 ? "+" : ""}{selected.x} / 과장성 {selected.sensationalism ?? "미측정"}</p>{selected.id !== article.id && <Link href={`/articles/${selected.id}`}>이 기사 분석 보기 →</Link>}</div>
  </div>;
}
