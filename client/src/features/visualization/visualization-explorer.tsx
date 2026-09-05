"use client";

import { useEffect, useMemo, useState } from "react";
import { visualizationPoints as fixturePoints } from "@/mocks/fixtures/content";
import { useViewerQuery, useVisualizationPointsQuery } from "@/lib/api/queries";
import { isMockMode } from "@/lib/api/mode";
import { StatePanel } from "@/components/ui/state-panel";
import { Button, ButtonLink } from "@/components/ui/button";
import { ApiError, apiRequest } from "@/lib/api/client";
import type { VisualizationPoint } from "@/lib/api/types";
import { PerspectiveField, type FieldView } from "./perspective-field";
import { ArrowUpRight, Check } from "lucide-react";
import { DefinitionTooltip } from "@/components/ui/definition-tooltip";
import { analysisTerms } from "@/lib/content/analysis-terms";
import { DistributionCharts, SelectedBiasChart, SelectedScoreChart } from "./distribution-charts";
import { signed } from "./field-model";

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
      {!isGuest && viewer.data && !userPoint ? <div className="notice">자기보고 설문이나 기사 읽기와 평가 기록이 생기면 이 지도를 나의 관점 기준으로 정렬합니다.</div> : null}
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

function SelectedArticleLinks({ articleId }: { articleId: string }) {
  const [issueId, setIssueId] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void apiRequest<{ issue_id?: string | null }>(`/articles/${encodeURIComponent(articleId)}`)
      .then((article) => {
        if (active) setIssueId(article.issue_id ?? null);
      })
      .catch(() => undefined);
    return () => { active = false; };
  }, [articleId]);

  return (
    <div className="form-actions" aria-label="선택한 기사에서 이어서 보기">
      <ButtonLink href={`/articles/${articleId}`}>선택한 기사 분석 보기<ArrowUpRight size={15} aria-hidden="true" /></ButtonLink>
      {issueId ? <ButtonLink variant="secondary" href={`/issues/${issueId}`}>관련 이슈에서 다른 보도 비교하기</ButtonLink> : null}
    </div>
  );
}

function VisualizationFieldContent({ points, initialPointId, personalPointId }: { points: VisualizationPoint[]; initialPointId: string; personalPointId?: string }) {
  const [selectedId, setSelectedId] = useState(initialPointId);
  const [view, setView] = useState<FieldView>(points.find((point) => point.id === initialPointId)?.type === "source" ? "source" : "article");
  function selectPoint(id: string) {
    setSelectedId(id);
    const point = points.find((item) => item.id === id);
    if (point && point.type !== "user") setView(point.type);
  }
  function changeView(nextView: FieldView) {
    setView(nextView);
    const first = points.find((point) => point.type === nextView);
    if (first) setSelectedId(first.id);
  }
  const current = points.find((point) => point.id === selectedId) ?? points.find((point) => point.id === initialPointId) ?? points[0];
  const personalPoint = points.find((point) => point.id === personalPointId);
  const personal = current.type === "user";
  const currentDistance = personalPoint && current.type === "article" ? perspectiveDistance(current, personalPoint) : null;
  const distribution = useMemo(() => {
    const articles = points.filter((point) => point.type === "article");
    const measurable = articles.filter((point) => point.sensationalism !== null);
    const biasValues = articles.map((point) => point.x);
    return {
      averageBias: articles.length ? articles.reduce((sum, point) => sum + point.x, 0) / articles.length : null,
      averageConfidence: articles.length ? articles.reduce((sum, point) => sum + point.confidence, 0) / articles.length : 0,
      averageSensationalism: measurable.length ? measurable.reduce((sum, point) => sum + (point.sensationalism ?? 0), 0) / measurable.length : null,
      biasMin: biasValues.length ? Math.min(...biasValues) : 0,
      biasMax: biasValues.length ? Math.max(...biasValues) : 0,
    };
  }, [points]);

  const graphTitle = `${personalPoint ? "나의 편향 기준과 " : ""}기사 편향성과 과장성 좌표 분포, 깊이는 분석 신뢰도인 3D 그래프`;
  const visiblePoints = points.filter((point) => point.type === view);

  return (
    <section className="perspective-workspace" aria-labelledby="perspective-solid-title">
      <h2 id="perspective-solid-title" className="sr-only">{personalPoint ? "나의 편향 기준으로 읽는 기사 좌표" : "세 기준으로 읽는 기사 좌표"}</h2>
      <div className="perspective-workspace__toolbar">
        <div className="space-view-switch" role="group" aria-label="지도에 표시할 자료">
          <Button variant="ghost" aria-pressed={view === "article"} onClick={() => changeView("article")}>기사 <span>{points.filter((point) => point.type === "article").length}</span></Button>
          <Button variant="ghost" aria-pressed={view === "source"} onClick={() => changeView("source")}>출처 평균 <span>{points.filter((point) => point.type === "source").length}</span></Button>
        </div>
        <span>가로: 편향 / 높이: 과장 / 깊이: 신뢰도</span>
      </div>
      <div className="perspective-workspace__main">
        <PerspectiveField points={[...visiblePoints, ...points.filter((point) => point.type === "user")]} selectedId={current.id} anchorId={personalPoint?.id} title={graphTitle} onSelect={selectPoint} />
        <aside className="space-inspector" aria-label="선택한 자료 분석">
          <header className="space-inspector__header">
            <span>{personal ? "나의 기준" : current.type === "source" ? "출처 평균" : "선택한 기사"}</span>
            <h3 className="space-inspector__title">{current.label}</h3>
          </header>
          <SelectedBiasChart point={current} average={distribution.averageBias} />
          <SelectedScoreChart point={current} />
          {currentDistance !== null ? <p className="space-inspector__personal">{distanceLabel(currentDistance)} <strong>차이 {Math.round(currentDistance)}점</strong></p> : null}
          {current.type === "article" ? <SelectedArticleLinks key={current.id} articleId={current.id} /> : null}
        </aside>
      </div>
      <DistributionCharts points={points} current={current} />
      <div className="space-summary" aria-label="기사 분석 분포 요약">
        <span><DefinitionTooltip {...analysisTerms.biasRange} /><strong>{signed(distribution.biasMin)} ~ {signed(distribution.biasMax)}</strong></span>
        <span><DefinitionTooltip {...analysisTerms.averageSensationalism} /><strong>{distribution.averageSensationalism === null ? "미측정" : Math.round(distribution.averageSensationalism)}</strong></span>
        <span><DefinitionTooltip {...analysisTerms.averageConfidence} /><strong>{Math.round(distribution.averageConfidence * 100)}%</strong></span>
        <span className="space-summary__note">숫자가 있는 점은 같은 좌표의 자료입니다.</span>
      </div>
      <div className="space-article-list" role="group" aria-label="그래프에서 확인할 자료" id="space-article-list">
        <div className="space-article-list__heading"><h3>{view === "article" ? "기사 목록" : "출처 목록"}</h3><span>편향</span><span>과장</span><span>신뢰도</span></div>
        {points.filter((point) => point.type === view || point.type === "user").map((point) => (
          <Button key={point.id} variant="ghost" aria-pressed={current.id === point.id} onClick={() => selectPoint(point.id)}>
            <span className="space-article-list__title"><i aria-hidden="true">{current.id === point.id ? <Check size={13} /> : null}</i><strong>{point.label}</strong>{point.type === "user" ? <small>나의 기준</small> : null}</span>
            <span>{signed(point.x)}</span>
            <span>{point.type === "user" ? "해당 없음" : point.sensationalism === null ? "미측정" : Math.round(point.sensationalism)}</span>
            <span>{Math.round(point.confidence * 100)}%</span>
          </Button>
        ))}
      </div>
    </section>
  );
}
