"use client";

import { useState, type CSSProperties } from "react";
import Link from "next/link";
import { ArrowUpRight, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useIssueArticlesQuery } from "@/lib/api/queries";
import type { Article } from "@/lib/api/types";
import { PerspectiveField, type PerspectivePoint } from "@/features/visualization/perspective-field";
import { SelectedBiasChart, SelectedScoreChart } from "@/features/visualization/distribution-charts";
import { articleMapMarkers } from "./article-map-markers";

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
  const markers = articleMapMarkers(articles);
  const points: PerspectivePoint[] = articles.map((item) => ({
    id: item.id, label: item.title, type: "article",
    x: item.x, y: item.y, z: item.z, sensationalism: item.sensationalism,
    confidence: item.confidence, scoreVersion: item.scoreVersion, observedAt: item.publishedAt,
    ...markers.get(item.id),
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
      <div className="article-perspective-map__sidebar">
        <section className="article-map-legend" aria-labelledby="article-map-legend-title">
          <header><h3 id="article-map-legend-title">지도 속 기사</h3><p>색은 언론사, 번호는 기사입니다.</p></header>
          <div className="article-perspective-map__articles" role="group" aria-label="같은 이슈에서 비교할 기사">
            {articles.map((item) => {
              const identity = markers.get(item.id)!;
              const isSelected = selected.id === item.id;
              return <Button key={item.id} variant="ghost" aria-pressed={isSelected} onClick={() => setSelectedId(item.id)}>
                <span className="article-map-marker" style={{ "--article-marker-color": identity.color } as CSSProperties}>{identity.marker}</span>
                <span className="article-map-legend__story">
                  <span className="article-perspective-map__source">{item.source}{item.id === article.id ? <small>읽는 기사</small> : null}{isSelected ? <small className="article-map-legend__selected"><Check size={12} aria-hidden="true" />선택됨</small> : null}</span>
                  <strong>{item.title}</strong>
                  {item.sensationalism === null ? <small>좌표 미측정</small> : null}
                </span>
              </Button>;
            })}
          </div>
          <div className="article-map-legend__key"><span><i className="article-map-legend__selected-ring" aria-hidden="true" />테두리: 선택한 기사</span><span><i className="article-map-legend__projection" aria-hidden="true" />빈 원과 점선: 좌표 보조 표시</span></div>
        </section>
        <aside className="space-inspector" aria-label="선택한 기사 관점">
        <header className="space-inspector__header">
          <span><span className="article-map-marker article-map-marker--small" style={{ "--article-marker-color": current.color } as CSSProperties}>{current.marker}</span>{isReading ? "읽고 있는 기사" : "같은 이슈의 다른 기사"} / {selected.source}</span>
          <h3 className="space-inspector__title">{selected.title}</h3>
        </header>
        <SelectedBiasChart point={current} />
        <SelectedScoreChart point={current} />
        {selected.sensationalism === null ? <p className="article-perspective-map__status">과장성 측정값이 없어 이 기사는 지도에 점으로 표시하지 않습니다.</p> : null}
        {!isReading ? <Link className="text-link" href={`/articles/${selected.id}#perspective-map`}>이 기사 분석 보기 <ArrowUpRight size={15} aria-hidden="true" /></Link> : null}
        </aside>
      </div>
    </div>
  </>;
}
