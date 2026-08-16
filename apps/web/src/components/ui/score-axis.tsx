import { formatAxis, formatConfidence, AXIS_META } from "@/lib/api/formatters";

export function ScoreAxis({ axis, value, confidence }: { axis: keyof typeof AXIS_META; value: number; confidence?: number }) {
  const meta = AXIS_META[axis];
  const left = `${Math.max(0, Math.min(100, (value + 100) / 2))}%`;
  return (
    <div className="axis" aria-label={formatAxis(value, axis)}>
      <div className="axis__head"><strong>{meta.short}</strong><span>{value > 0 ? `+${value}` : value}</span></div>
      <div className="axis__labels"><span>− {meta.negative}</span><span>+ {meta.positive}</span></div>
      <div className="axis__track" aria-hidden="true"><span className="axis__center" /><span className="axis__marker" style={{ left }} /></div>
      {confidence !== undefined && <small>분석 신뢰도 {formatConfidence(confidence)}</small>}
    </div>
  );
}
