"use client";

import { useState, type CSSProperties } from "react";
import Link from "next/link";
import { ArrowUpRight, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Article } from "@/lib/api/types";
import { PerspectiveField, type PerspectivePoint } from "@/features/visualization/perspective-field";
import { SelectedBiasChart, SelectedScoreChart } from "@/features/visualization/distribution-charts";
import { articleMapMarkers } from "@/features/articles/article-map-markers";

export function IssuePerspectiveMap({ articles }: { articles: Article[] }) {
  const [selectedId, setSelectedId] = useState(articles[0]?.id ?? "");
  if (articles.length === 0) return null;

  const selected = articles.find((article) => article.id === selectedId) ?? articles[0];
  const markers = articleMapMarkers(articles);
  const points: PerspectivePoint[] = articles.map((article) => ({
    id: article.id,
    label: article.title,
    type: "article",
    x: article.x,
    y: article.y,
    z: article.z,
    sensationalism: article.sensationalism,
    confidence: article.confidence,
    scoreVersion: article.scoreVersion,
    observedAt: article.publishedAt,
    ...markers.get(article.id),
  }));
  const current = points.find((point) => point.id === selected.id)!;

  return (
    <section className="issue-perspective-map article-perspective-map perspective-workspace" aria-labelledby="issue-perspective-map-title">
      <header className="article-perspective-map__heading">
        <h3 id="issue-perspective-map-title">기사 비교 3D 지도</h3>
        <p>선택한 기사의 편향성과 과장성, 분석 신뢰도를 한 공간에서 비교합니다.</p>
      </header>
      <div className="article-perspective-map__context">
        <span>선택한 기사 {articles.length}개 / 가로: 편향성 / 높이: 과장성 / 깊이: 분석 신뢰도</span>
      </div>
      <div className="perspective-workspace__main">
        <PerspectiveField
          points={points}
          selectedId={selected.id}
          anchorId={undefined}
          title="선택한 기사들의 편향성, 과장성, 분석 신뢰도를 비교하는 3D 그래프"
          onSelect={setSelectedId}
        />
        <div className="article-perspective-map__sidebar">
          <section className="article-map-legend" aria-labelledby="issue-map-legend-title">
            <header>
              <h4 id="issue-map-legend-title">그래프 속 기사</h4>
              <p>색은 언론사, 번호는 비교 중인 기사입니다.</p>
            </header>
            <div className="article-perspective-map__articles" role="group" aria-label="3D 그래프에서 비교할 기사">
              {articles.map((article) => {
                const identity = markers.get(article.id)!;
                const isSelected = selected.id === article.id;
                return (
                  <Button
                    key={article.id}
                    variant="ghost"
                    aria-label={`${article.source} ${article.title} 그래프에서 선택`}
                    aria-pressed={isSelected}
                    onClick={() => setSelectedId(article.id)}
                  >
                    <span className="article-map-marker" style={{ "--article-marker-color": identity.color } as CSSProperties}>{identity.marker}</span>
                    <span className="article-map-legend__story">
                      <span className="article-perspective-map__source">
                        {article.source}
                        {isSelected ? <small className="article-map-legend__selected"><Check size={12} aria-hidden="true" />선택됨</small> : null}
                      </span>
                      <strong>{article.title}</strong>
                      {article.sensationalism === null ? <small>좌표 미측정</small> : null}
                    </span>
                  </Button>
                );
              })}
            </div>
            <div className="article-map-legend__key">
              <span><i className="article-map-legend__selected-ring" aria-hidden="true" />테두리: 선택한 기사</span>
              <span><i className="article-map-legend__projection" aria-hidden="true" />빈 원과 점선: 좌표 보조 표시</span>
            </div>
          </section>
          <aside className="space-inspector" aria-label="선택한 기사 관점">
            <header className="space-inspector__header">
              <span>
                <span className="article-map-marker article-map-marker--small" style={{ "--article-marker-color": current.color } as CSSProperties}>{current.marker}</span>
                선택한 기사 / {selected.source}
              </span>
              <h4 className="space-inspector__title">{selected.title}</h4>
            </header>
            <SelectedBiasChart point={current} />
            <SelectedScoreChart point={current} />
            {selected.sensationalism === null ? <p className="article-perspective-map__status">과장성 측정값이 없어 이 기사는 지도에 점으로 표시하지 않습니다.</p> : null}
            <Link className="text-link" href={`/articles/${selected.id}`}>선택한 기사 상세 분석 보기 <ArrowUpRight size={15} aria-hidden="true" /></Link>
          </aside>
        </div>
      </div>
    </section>
  );
}
