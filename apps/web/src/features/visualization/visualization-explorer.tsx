"use client";

import { useMemo, useState } from "react";
import { visualizationPoints as fixturePoints } from "@/mocks/fixtures/content";
import { useViewerQuery, useVisualizationPointsQuery } from "@/lib/api/queries";
import { formatBiasScore, formatSensationalismScore } from "@/lib/api/formatters";
import { isMockMode } from "@/lib/api/mode";
import { StatePanel } from "@/components/ui/state-panel";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/client";
import type { VisualizationPoint } from "@/lib/api/types";
import { PerspectiveField } from "./perspective-field";
import { DefinitionTooltip } from "@/components/ui/definition-tooltip";
import { analysisTerms } from "@/lib/content/analysis-terms";

export function VisualizationExplorer() {
  const pointsQuery = useVisualizationPointsQuery();
  const viewer = useViewerQuery();
  if (pointsQuery.isPending && !isMockMode()) return <StatePanel state="loading" />;
  if (pointsQuery.isError && !isMockMode()) return <StatePanel state="error" onRetry={() => void pointsQuery.refetch()} />;
  const sampledPoints = pointsQuery.data?.items ?? (isMockMode() ? fixturePoints : []);
  const visualizationPoints = [...new Map(sampledPoints.map((point) => [`${point.type}:${point.id}:${point.type === "user" ? point.label : ""}`, point])).values()]
    .map((point) => point.type === "user" ? { ...point, id: `${point.id}:${point.label}` } : point);
  if (visualizationPoints.length === 0) return <StatePanel state="empty" />;
  const userPoints = visualizationPoints.filter((point) => point.type === "user");
  const userPoint = userPoints.find((point) => point.label.includes("행동 기반")) ?? userPoints[0];
  const isGuest = viewer.error instanceof ApiError && viewer.error.status === 401;
  const articles = visualizationPoints.filter((point) => point.type === "article");
  const sortedArticles = userPoint
    ? articles.slice().sort((a, b) => perspectiveDistance(a, userPoint) - perspectiveDistance(b, userPoint))
    : articles;
  const orderedPoints = [
    ...(userPoint ? [userPoint] : []),
    ...sortedArticles,
    ...visualizationPoints.filter((point) => point.type === "source"),
    ...userPoints.filter((point) => point.id !== userPoint?.id),
  ];
  const initialPoint = sortedArticles[0] ?? userPoint ?? orderedPoints[0];
  return (
    <>
      {!isGuest && viewer.data && !userPoint ? <div className="notice">자기보고 설문이나 기사 읽기·평가 기록이 생기면 이 지도를 나의 관점 기준으로 정렬합니다.</div> : null}
      <VisualizationFieldContent points={orderedPoints} initialPointId={initialPoint.id} personalPointId={userPoint?.id} />
    </>
  );
}

export function perspectiveDistance(point: VisualizationPoint, personalPoint: VisualizationPoint) {
  const biasGap = point.x - personalPoint.x;
  if (personalPoint.type === "user" || personalPoint.sensationalism === null) return Math.abs(biasGap);
  const sensationalismGap = (point.sensationalism ?? 0) - personalPoint.sensationalism;
  return Math.sqrt(biasGap ** 2 + (sensationalismGap * .65) ** 2);
}

function distanceLabel(distance: number) {
  if (distance <= 12) return "현재 관점과 가까운 기사";
  if (distance <= 28) return "부담 없이 넓히는 인접 관점";
  return "관점을 크게 넓히는 기사";
}

function VisualizationFieldContent({ points, initialPointId, personalPointId }: { points: VisualizationPoint[]; initialPointId: string; personalPointId?: string }) {
  const [selectedId, setSelectedId] = useState(initialPointId);
  const current = points.find((point) => point.id === selectedId) ?? points[0];
  const personalPoint = points.find((point) => point.id === personalPointId);
  const personal = current.type === "user";
  const sensationalismLabel = personal || current.sensationalism === null ? "해당 없음" : formatSensationalismScore(current.sensationalism);
  const currentDistance = personalPoint && current.type === "article" ? perspectiveDistance(current, personalPoint) : null;
  const counts = points.reduce((result, point) => {
    result[point.type] += 1;
    return result;
  }, { article: 0, source: 0, user: 0 });

  const distribution = useMemo(() => {
    const articles = points.filter((point) => point.type === "article");
    const measurable = articles.filter((point) => point.sensationalism !== null);
    const biasValues = articles.map((point) => point.x);
    return {
      averageConfidence: articles.length ? articles.reduce((sum, point) => sum + point.confidence, 0) / articles.length : 0,
      averageSensationalism: measurable.length ? measurable.reduce((sum, point) => sum + (point.sensationalism ?? 0), 0) / measurable.length : null,
      biasMin: biasValues.length ? Math.min(...biasValues) : 0,
      biasMax: biasValues.length ? Math.max(...biasValues) : 0,
    };
  }, [points]);

  const graphTitle = `${personalPoint ? "나의 편향 기준과 " : ""}기사 편향성·과장성 좌표 분포`;

  return (
    <section className="perspective-solid" aria-labelledby="perspective-solid-title">
      <div className="perspective-solid__visual">
        <PerspectiveField points={points} selectedId={current.id} anchorId={personalPoint?.id} title={graphTitle} />
      </div>

      <div className="perspective-solid__summary">
        <p className="eyebrow">{personal ? "자기보고 기준점" : current.type === "source" ? "출처 집계" : "선택한 기사"}</p>
        <h2 id="perspective-solid-title">{personalPoint ? "나의 편향 기준으로 읽는 기사 좌표" : "두 기준으로 읽는 기사 좌표"}</h2>
        <p className="perspective-solid__selection">{current.label}</p>
        {personalPoint && currentDistance !== null ? (
          <div className="perspective-solid__personal">
            <strong>{distanceLabel(currentDistance)}</strong>
            <span>{personalPoint.label}과의 편향 거리 {Math.round(currentDistance)} · 붉은 선은 나의 편향 기준, 검은 테두리는 선택 자료</span>
          </div>
        ) : null}
        <p className="perspective-solid__intro">모든 점은 실제 분석 수치에 놓입니다. 배경 형태는 전체 기사 좌표로 계산하며, 기사를 선택해도 분포 자체를 왜곡하지 않습니다.</p>

        <dl className="perspective-solid__readout">
          <div>
            <dt><DefinitionTooltip {...analysisTerms.bias} /></dt>
            <dd>{formatBiasScore(current.x)}</dd>
          </div>
          <div>
            <dt><DefinitionTooltip {...analysisTerms.sensationalism} /></dt>
            <dd>{sensationalismLabel}</dd>
          </div>
          <div>
            <dt><DefinitionTooltip {...analysisTerms.confidence} /></dt>
            <dd>{Math.round(current.confidence * 100)}%</dd>
          </div>
        </dl>

        <dl className="perspective-solid__distribution" aria-label="기사 분석 분포 요약">
          <div><dt><DefinitionTooltip {...analysisTerms.biasRange} /></dt><dd>{formatBiasScore(distribution.biasMin)} — {formatBiasScore(distribution.biasMax)}</dd></div>
          <div><dt><DefinitionTooltip {...analysisTerms.averageSensationalism} /></dt><dd>{distribution.averageSensationalism === null ? "미측정" : Math.round(distribution.averageSensationalism)}</dd></div>
          <div><dt><DefinitionTooltip {...analysisTerms.averageConfidence} /></dt><dd>{Math.round(distribution.averageConfidence * 100)}%</dd></div>
        </dl>
      </div>

      <div className="perspective-solid__scope" aria-label="시각화에 포함된 자료">
        <span>기사 <strong>{counts.article}</strong></span>
        <span>출처 <strong>{counts.source}</strong></span>
        <span>자기보고 <strong>{counts.user}</strong></span>
        <span className="perspective-solid__legend">분포 배경이 진할수록 기사가 많이 모인 구간</span>
      </div>

      <div className="perspective-solid__index" role="group" aria-label="그래프에서 확인할 자료">
        {points.map((point, index) => (
          <Button
            key={point.id}
            variant="ghost"
            aria-pressed={current.id === point.id}
            data-selected={current.id === point.id ? "" : undefined}
            onClick={() => setSelectedId(point.id)}
          >
            <span>{String(index + 1).padStart(2, "0")}</span>
            <strong>{point.label}</strong>
            <small>{point.type === "user" ? point.label : personalPoint && point.type === "article" ? distanceLabel(perspectiveDistance(point, personalPoint)) : `${formatBiasScore(point.x)} · 과장 ${point.sensationalism ?? "—"}`}</small>
          </Button>
        ))}
      </div>
    </section>
  );
}
