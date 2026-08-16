"use client";

import { visualizationPoints as fixturePoints } from "@/mocks/fixtures/content";
import { useVisualizationPointsQuery } from "@/lib/api/queries";
import { formatBiasScore, formatSensationalismScore } from "@/lib/api/formatters";

export function VisualizationExplorer() {
  const pointsQuery = useVisualizationPointsQuery();
  const visualizationPoints = pointsQuery.data?.items.length ? pointsQuery.data.items : fixturePoints;
  const current = visualizationPoints.find((point) => point.type === "user") ?? visualizationPoints[0];
  const counts = visualizationPoints.reduce((result, point) => {
    result[point.type] += 1;
    return result;
  }, { article: 0, source: 0, user: 0 });

  return (
    <section className="perspective-solid" aria-labelledby="perspective-solid-title">
      <div className="perspective-solid__visual">
        <svg viewBox="0 0 640 600" role="img" aria-labelledby="perspective-solid-svg-title perspective-solid-svg-desc">
          <title id="perspective-solid-svg-title">현재 관점의 편향성과 과장성</title>
          <desc id="perspective-solid-svg-desc">파란색 왼쪽 텍스트는 좌우 편향성을, 빨간색 오른쪽 텍스트는 과장성을 나타냅니다.</desc>
          <polygon className="perspective-solid__shadow" points="84,458 324,584 584,448 342,326" />
          <polygon className="perspective-solid__face perspective-solid__face--top" points="320,42 574,176 320,314 66,176" />
          <polygon className="perspective-solid__face perspective-solid__face--left" points="66,176 320,314 320,566 66,428" />
          <polygon className="perspective-solid__face perspective-solid__face--right" points="320,314 574,176 574,428 320,566" />

          <text className="perspective-solid__label perspective-solid__label--top" x="320" y="151" textAnchor="middle">LLM 기사 분석</text>
          <text className="perspective-solid__value perspective-solid__value--top" x="320" y="210" textAnchor="middle">두 가지 기준</text>

          <text className="perspective-solid__label perspective-solid__label--left" x="192" y="337" textAnchor="middle">편향성</text>
          <text className="perspective-solid__value perspective-solid__value--left" x="192" y="401" textAnchor="middle">{formatBiasScore(current.x)}</text>

          <text className="perspective-solid__label perspective-solid__label--right" x="448" y="337" textAnchor="middle">과장성</text>
          <text className="perspective-solid__value perspective-solid__value--right" x="448" y="401" textAnchor="middle">{formatSensationalismScore(current.sensationalism)}</text>
        </svg>
      </div>

      <div className="perspective-solid__summary">
        <p className="eyebrow">현재 관점</p>
        <h2 id="perspective-solid-title">두 기준으로 읽는<br />현재 관점</h2>
        <p className="perspective-solid__intro">편향성은 좌편향에서 우편향까지, 과장성은 낮음에서 높음까지 한눈에 비교합니다.</p>

        <dl className="perspective-solid__readout">
          <div>
            <dt>편향성</dt>
            <dd>{formatBiasScore(current.x)}</dd>
          </div>
          <div>
            <dt>과장성</dt>
            <dd>{formatSensationalismScore(current.sensationalism)}</dd>
          </div>
        </dl>

        <div className="perspective-solid__scope" aria-label="시각화에 포함된 자료">
          <span>분석 신뢰도 <strong>{Math.round(current.confidence * 100)}%</strong></span>
          <span>기사 <strong>{counts.article}</strong></span>
          <span>언론사 <strong>{counts.source}</strong></span>
          <span>응답 <strong>{counts.user}</strong></span>
        </div>
      </div>
    </section>
  );
}
