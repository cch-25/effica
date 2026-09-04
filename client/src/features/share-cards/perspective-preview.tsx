import { clampScore, formatBiasScore, formatSensationalismScore, formatTierLabel } from "@/lib/api/formatters";
import { ButtonLink } from "@/components/ui/button";

export function PerspectivePreview({
  displayName,
  template,
  compact = false,
  snapshot,
}: {
  displayName: string;
  template?: "orbit" | "editorial";
  compact?: boolean;
  snapshot?: {
    x: number;
    sensationalism: number | null;
    confidence: number;
    tier: string;
    creditTotal: number;
  } | null;
}) {
  if (!snapshot) {
    return (
      <section className={`share-preview${template ? ` share-preview--${template}` : ""}`} style={compact ? { maxWidth: 560, margin: "1.5rem auto" } : undefined} aria-label={`${displayName || "공유 카드"}의 편향성과 과장성`}>
        <p>공유 카드 미리보기</p>
        <h2>표시할 관점 결과가 없습니다.</h2>
        <dl><div><dt>편향성</dt><dd>결과 없음</dd></div><div><dt>과장성</dt><dd>결과 없음</dd></div></dl>
        <p>관점 설문을 완료하면 실제 결과를 확인하고 공유 카드를 만들 수 있습니다.</p>
        <ButtonLink href="/onboarding/questionnaire?returnTo=%2Fshare%2Fnew">관점 설문 먼저 완료하기</ButtonLink>
      </section>
    );
  }

  const bias = snapshot.x;
  const sensationalism = snapshot.sensationalism;
  const title = displayName || "나의 관점 카드";

  return (
    <section className={`share-preview${template ? ` share-preview--${template}` : ""}`} style={compact ? { maxWidth: 560, margin: "1.5rem auto" } : undefined} aria-label={`${title}의 편향성과 과장성`}>
      <p>현재 내 활동 기준 미리보기</p>
      <h2>{title}</h2>
      <div>
        <div className="axis" aria-label={`편향성 ${formatBiasScore(bias)}`}>
          <div className="axis__head"><strong>편향성</strong><span>{formatBiasScore(bias)}</span></div>
          <div className="axis__labels"><span>좌편향</span><span>우편향</span></div>
          <div className="axis__track axis__track--bias" aria-hidden="true"><span className="axis__center" /><span className="axis__marker" style={{ left: `${(clampScore(bias) + 100) / 2}%` }} /></div>
        </div>
        <div className="axis" aria-label={`과장성 ${formatSensationalismScore(sensationalism)}`}>
          <div className="axis__head"><strong>과장성</strong><span>{formatSensationalismScore(sensationalism)}</span></div>
          <div className="axis__labels"><span>낮음</span><span>높음</span></div>
          {sensationalism === null ? <small>현재 기록에는 측정값이 없습니다.</small> : <div className="axis__track" aria-hidden="true"><span className="axis__marker" style={{ left: `${sensationalism}%` }} /></div>}
        </div>
      </div>
      <dl style={{ gridTemplateColumns: "repeat(2, minmax(0, 1fr))" }}>
        <div><dt>편향성</dt><dd>{formatBiasScore(bias)}</dd></div>
        <div><dt>과장성</dt><dd>{formatSensationalismScore(sensationalism)}</dd></div>
      </dl>
      <small>{`현재 계산 결과: 분석 신뢰도 ${Math.round(snapshot.confidence * 100)}%, ${formatTierLabel(snapshot.tier)} 단계, 활동 크레딧 ${snapshot.creditTotal}`}</small>
    </section>
  );
}
