import { clampScore, formatBiasScore, formatSensationalismScore } from "@/lib/api/formatters";

export function PerspectivePreview({
  displayName,
  template,
  compact = false,
}: {
  displayName: string;
  template?: "orbit" | "editorial";
  compact?: boolean;
}) {
  const bias = 4;
  const sensationalism = 18;

  return (
    <section className={`share-preview${template ? ` share-preview--${template}` : ""}`} style={compact ? { maxWidth: 560, margin: "1.5rem auto" } : undefined} aria-label={`${displayName || "표시 이름 없음"}의 편향성과 과장성`}>
      <p>나의 관점 / 2026</p>
      <h2>{displayName || "표시 이름 없음"}</h2>
      <div>
        <div className="axis" aria-label={`편향성 ${formatBiasScore(bias)}`}>
          <div className="axis__head"><strong>편향성</strong><span>{formatBiasScore(bias)}</span></div>
          <div className="axis__labels"><span>좌편향</span><span>우편향</span></div>
          <div className="axis__track axis__track--bias" aria-hidden="true"><span className="axis__center" /><span className="axis__marker" style={{ left: `${(clampScore(bias) + 100) / 2}%` }} /></div>
        </div>
        <div className="axis" aria-label={`과장성 ${formatSensationalismScore(sensationalism)}`}>
          <div className="axis__head"><strong>과장성</strong><span>{formatSensationalismScore(sensationalism)}</span></div>
          <div className="axis__labels"><span>낮음</span><span>높음</span></div>
          <div className="axis__track" aria-hidden="true"><span className="axis__marker" style={{ left: `${sensationalism}%` }} /></div>
        </div>
      </div>
      <dl style={{ gridTemplateColumns: "repeat(2, minmax(0, 1fr))" }}>
        <div><dt>편향성</dt><dd>{formatBiasScore(bias)}</dd></div>
        <div><dt>과장성</dt><dd>{formatSensationalismScore(sensationalism)}</dd></div>
      </dl>
      <small>현재 응답 결과 · 분석 신뢰도 68% · 탐색가 단계</small>
    </section>
  );
}
