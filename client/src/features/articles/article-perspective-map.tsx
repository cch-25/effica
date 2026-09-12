"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowUpRight, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useIssueArticlesQuery } from "@/lib/api/queries";
import type { Article, VisualizationPoint } from "@/lib/api/types";
import { PerspectiveField } from "@/features/visualization/perspective-field";
import { SelectedBiasChart, SelectedScoreChart } from "@/features/visualization/distribution-charts";

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
  const points: VisualizationPoint[] = articles.map((item) => ({
    id: item.id, label: item.title, type: "article",
    x: item.x, y: item.y, z: item.z, sensationalism: item.sensationalism,
    confidence: item.confidence, scoreVersion: item.scoreVersion, observedAt: item.publishedAt,
  }));
  const current = points.find((point) => point.id === selected.id)!;
  const isReading = selected.id === article.id;

  return <>
    <div className="article-perspective-map__context">
      <span>기사 {articles.length}개 / 가로: 편향 / 높이: 과장 / 깊이: 분석 신뢰도</span>
      {!isReading ? <Button variant="ghost" onClick={() => setSelectedId(article.id)}>읽고 있는 기사로 돌아가기</Button> : null}
    </div>
    <div className="perspective-workspace__main">
      <PerspectiveField points={points} selectedId={selected.id} anchorId={undefined} title="이 기사와 같은 이슈의 보도 관점 좌표, 깊이는 분석 신뢰도인 3D 그래프" onSelect={setSelectedId} />
      <aside className="space-inspector" aria-label="선택한 기사 관점">
        <header className="space-inspector__header">
          <span>{isReading ? "읽고 있는 기사" : "같은 이슈의 다른 기사"} / {selected.source}</span>
          <h3 className="space-inspector__title">{selected.title}</h3>
        </header>
        <SelectedBiasChart point={current} />
        <SelectedScoreChart point={current} />
        {selected.sensationalism === null ? <p className="article-perspective-map__status">과장성 측정값이 없어 이 기사는 지도에 점으로 표시하지 않습니다.</p> : null}
        {!isReading ? <Link className="text-link" href={`/articles/${selected.id}#perspective-map`}>이 기사 분석 보기 <ArrowUpRight size={15} aria-hidden="true" /></Link> : null}
      </aside>
    </div>
    {articles.length > 1 ? <div className="article-perspective-map__articles" role="group" aria-label="같은 이슈에서 비교할 기사">
      {articles.map((item) => <Button key={item.id} variant="ghost" aria-pressed={selected.id === item.id} onClick={() => setSelectedId(item.id)}>
        <span className="article-perspective-map__source">{selected.id === item.id ? <Check size={14} aria-hidden="true" /> : null}{item.source}{item.id === article.id ? <small>읽고 있는 기사</small> : null}</span>
        <strong>{item.title}</strong>
      </Button>)}
    </div> : null}
  </>;
}
