"use client";

import { useId } from "react";
import type { VisualizationPoint } from "@/lib/api/types";

type PerspectiveFieldProps = {
  points: VisualizationPoint[];
  selectedId: string;
  anchorId: string | undefined;
  title: string;
};

export const GRAPH_BOUNDS = {
  width: 640,
  height: 500,
  left: 76,
  right: 616,
  top: 72,
  bottom: 418,
} as const;

const BIAS_EXTENT = 100;
const SENSATIONALISM_MAX = 100;
const BIAS_BANDWIDTH = 24;
const SENSATIONALISM_BANDWIDTH = 18;
const X_TICKS = [-100, -50, 0, 50, 100];
const Y_TICKS = [0, 25, 50, 75, 100];

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, value));
}

function articleSensationalism(point: VisualizationPoint) {
  return point.type === "user" ? 0 : clamp(point.sensationalism ?? 0, 0, SENSATIONALISM_MAX);
}

function xPosition(value: number) {
  const ratio = (clamp(value, -BIAS_EXTENT, BIAS_EXTENT) + BIAS_EXTENT) / (BIAS_EXTENT * 2);
  return GRAPH_BOUNDS.left + ratio * (GRAPH_BOUNDS.right - GRAPH_BOUNDS.left);
}

function yPosition(value: number) {
  const ratio = clamp(value, 0, SENSATIONALISM_MAX) / SENSATIONALISM_MAX;
  return GRAPH_BOUNDS.bottom - ratio * (GRAPH_BOUNDS.bottom - GRAPH_BOUNDS.top);
}

export function getGraphCoordinates(point: VisualizationPoint) {
  return {
    x: xPosition(point.x),
    y: yPosition(articleSensationalism(point)),
  };
}

function densityAt(bias: number, sensationalism: number, articles: VisualizationPoint[]) {
  return articles.reduce((sum, article) => {
    const biasDistance = (bias - article.x) / BIAS_BANDWIDTH;
    const sensationalismDistance = (sensationalism - articleSensationalism(article)) / SENSATIONALISM_BANDWIDTH;
    return sum + Math.exp(-0.5 * (biasDistance ** 2 + sensationalismDistance ** 2));
  }, 0);
}

function signed(value: number) {
  if (value > 0) return `+${Math.round(value)}`;
  return `${Math.round(value)}`;
}

function pointValue(point: VisualizationPoint) {
  if (point.type === "user") return `나의 편향 기준 ${signed(point.x)}`;
  const sensationalism = point.sensationalism === null ? "미측정" : Math.round(point.sensationalism);
  return `편향 ${signed(point.x)} · 과장 ${sensationalism}`;
}

function selectedLabelPosition(x: number, y: number) {
  const width = 174;
  const height = 48;
  const placeLeft = x > (GRAPH_BOUNDS.left + GRAPH_BOUNDS.right) / 2;
  return {
    x: clamp(placeLeft ? x - width - 18 : x + 18, GRAPH_BOUNDS.left + 5, GRAPH_BOUNDS.right - width - 5),
    y: clamp(y - height - 18, GRAPH_BOUNDS.top + 5, GRAPH_BOUNDS.bottom - height - 8),
    width,
    height,
  };
}

export function PerspectiveField({ points, selectedId, anchorId, title }: PerspectiveFieldProps) {
  const gradientPrefix = useId().replaceAll(":", "");
  const articles = points.filter((point) => point.type === "article");
  const sources = points.filter((point) => point.type === "source");
  const selected = points.find((point) => point.id === selectedId) ?? points[0];
  const selectedIndex = points.findIndex((point) => point.id === selected.id);
  const selectedPosition = getGraphCoordinates(selected);
  const label = selectedLabelPosition(selectedPosition.x, selectedPosition.y);
  const anchor = points.find((point) => point.id === anchorId && point.type === "user");
  const anchorX = anchor ? xPosition(anchor.x) : null;
  const densityMaximum = Math.max(0, ...articles.map((article) => densityAt(article.x, articleSensationalism(article), articles)));
  const densityRadiusX = ((GRAPH_BOUNDS.right - GRAPH_BOUNDS.left) * BIAS_BANDWIDTH) / (BIAS_EXTENT * 2) * 1.65;
  const densityRadiusY = ((GRAPH_BOUNDS.bottom - GRAPH_BOUNDS.top) * SENSATIONALISM_BANDWIDTH) / SENSATIONALISM_MAX * 1.65;

  return (
    <div className="perspective-field">
      <div className="perspective-field__header">
        <div>
          <strong>기사 좌표 분포</strong>
          <p>점 하나는 기사 한 건입니다. 가까이 모인 곳일수록 배경이 진해집니다.</p>
        </div>
        <span>기사 {articles.length}건</span>
      </div>

      <svg className="perspective-field__chart" viewBox={`0 0 ${GRAPH_BOUNDS.width} ${GRAPH_BOUNDS.height}`} role="img" aria-label={title}>
        <title>{title}</title>
        <desc>가로축은 마이너스 100 좌편향부터 플러스 100 우편향, 세로축은 0부터 100까지의 기사 과장성입니다. 모든 기사 점은 실제 분석 좌표에 놓이고 배경의 진하기는 기사 밀도를 나타냅니다.</desc>
        <defs>
          <clipPath id={`${gradientPrefix}-plot`}>
            <rect x={GRAPH_BOUNDS.left} y={GRAPH_BOUNDS.top} width={GRAPH_BOUNDS.right - GRAPH_BOUNDS.left} height={GRAPH_BOUNDS.bottom - GRAPH_BOUNDS.top} />
          </clipPath>
          {articles.map((article, index) => {
            const density = densityAt(article.x, articleSensationalism(article), articles);
            const strength = densityMaximum > 0 ? density / densityMaximum : 0;
            return (
              <radialGradient key={article.id} id={`${gradientPrefix}-density-${index}`}>
                <stop offset="0" stopColor="#16867f" stopOpacity={0.3 + strength * 0.28} />
                <stop offset="0.62" stopColor="#5baaa5" stopOpacity={0.13 + strength * 0.12} />
                <stop offset="1" stopColor="#5baaa5" stopOpacity="0" />
              </radialGradient>
            );
          })}
        </defs>

        <rect className="perspective-field__plot-background" x={GRAPH_BOUNDS.left} y={GRAPH_BOUNDS.top} width={GRAPH_BOUNDS.right - GRAPH_BOUNDS.left} height={GRAPH_BOUNDS.bottom - GRAPH_BOUNDS.top} />
        <rect className="perspective-field__neutral-zone" x={xPosition(-10)} y={GRAPH_BOUNDS.top} width={xPosition(10) - xPosition(-10)} height={GRAPH_BOUNDS.bottom - GRAPH_BOUNDS.top} />

        {Y_TICKS.map((tick) => {
          const y = yPosition(tick);
          return (
            <g key={`y-${tick}`}>
              <line className="perspective-field__grid-line" x1={GRAPH_BOUNDS.left} y1={y} x2={GRAPH_BOUNDS.right} y2={y} />
              <text className="perspective-field__tick" x={GRAPH_BOUNDS.left - 14} y={y + 5} textAnchor="end">{tick}</text>
            </g>
          );
        })}
        {X_TICKS.map((tick) => {
          const x = xPosition(tick);
          return (
            <g key={`x-${tick}`}>
              <line className={tick === 0 ? "perspective-field__zero-line" : "perspective-field__grid-line"} x1={x} y1={GRAPH_BOUNDS.top} x2={x} y2={GRAPH_BOUNDS.bottom} />
              <text className="perspective-field__tick" x={x} y={GRAPH_BOUNDS.bottom + 25} textAnchor="middle">{signed(tick)}</text>
            </g>
          );
        })}

        <g clipPath={`url(#${gradientPrefix}-plot)`}>
          {articles.map((article, index) => {
            const position = getGraphCoordinates(article);
            return <ellipse key={article.id} cx={position.x} cy={position.y} rx={densityRadiusX} ry={densityRadiusY} fill={`url(#${gradientPrefix}-density-${index})`} />;
          })}
        </g>

        {anchorX !== null ? (
          <g className="perspective-field__personal-marker">
            <line x1={anchorX} y1={GRAPH_BOUNDS.top} x2={anchorX} y2={GRAPH_BOUNDS.bottom} />
            <path d={`M ${anchorX} ${GRAPH_BOUNDS.bottom - 3} l -8 -13 h 16 z`} />
            <text x={anchorX} y={GRAPH_BOUNDS.top - 15} textAnchor="middle">나 {signed(anchor?.x ?? 0)}</text>
          </g>
        ) : null}

        {articles.map((article) => {
          const position = getGraphCoordinates(article);
          return <circle key={article.id} className="perspective-field__article-point" cx={position.x} cy={position.y} r="5.5" />;
        })}
        {sources.map((source) => {
          const position = getGraphCoordinates(source);
          return <rect key={source.id} className="perspective-field__source-point" x={position.x - 5} y={position.y - 5} width="10" height="10" transform={`rotate(45 ${position.x} ${position.y})`} />;
        })}

        {selected.type === "user" ? (
          <circle className="perspective-field__selection-ring" cx={selectedPosition.x} cy={GRAPH_BOUNDS.bottom - 10} r="14" />
        ) : (
          <circle className="perspective-field__selection-ring" cx={selectedPosition.x} cy={selectedPosition.y} r="13" />
        )}
        <g className="perspective-field__selected-label">
          <line x1={selectedPosition.x} y1={selected.type === "user" ? GRAPH_BOUNDS.bottom - 10 : selectedPosition.y} x2={label.x + (selectedPosition.x > label.x ? label.width : 0)} y2={label.y + label.height / 2} />
          <rect x={label.x} y={label.y} width={label.width} height={label.height} />
          <text x={label.x + 12} y={label.y + 19}>선택 {String(selectedIndex + 1).padStart(2, "0")}</text>
          <text className="perspective-field__selected-value" x={label.x + 12} y={label.y + 38}>{pointValue(selected)}</text>
        </g>

        <line className="perspective-field__axis-line" x1={GRAPH_BOUNDS.left} y1={GRAPH_BOUNDS.bottom} x2={GRAPH_BOUNDS.right} y2={GRAPH_BOUNDS.bottom} />
        <line className="perspective-field__axis-line" x1={GRAPH_BOUNDS.left} y1={GRAPH_BOUNDS.top} x2={GRAPH_BOUNDS.left} y2={GRAPH_BOUNDS.bottom} />
        <text className="perspective-field__axis-title" x={(GRAPH_BOUNDS.left + GRAPH_BOUNDS.right) / 2} y={GRAPH_BOUNDS.height - 18} textAnchor="middle">기사의 편향성 · 좌편향 ← 0 → 우편향</text>
        <text className="perspective-field__axis-title" x="18" y={(GRAPH_BOUNDS.top + GRAPH_BOUNDS.bottom) / 2} textAnchor="middle" transform={`rotate(-90 18 ${(GRAPH_BOUNDS.top + GRAPH_BOUNDS.bottom) / 2})`}>기사의 과장성 · 높을수록 자극적</text>
        <text className="perspective-field__neutral-label" x={xPosition(0)} y={GRAPH_BOUNDS.top + 21} textAnchor="middle">중립 구간</text>
      </svg>

      <div className="perspective-field__key" aria-hidden="true">
        <span><i className="perspective-field__key-article" />기사</span>
        <span><i className="perspective-field__key-source" />출처 평균</span>
        {anchor ? <span><i className="perspective-field__key-personal" />나의 편향 기준</span> : null}
        <span><i className="perspective-field__key-density" />기사 밀집 영역</span>
      </div>
    </div>
  );
}
