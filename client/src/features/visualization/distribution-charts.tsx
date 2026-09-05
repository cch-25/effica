import type { VisualizationPoint } from "@/lib/api/types";
import { DefinitionTooltip } from "@/components/ui/definition-tooltip";
import { analysisTerms } from "@/lib/content/analysis-terms";
import { clamp, histogram, signed } from "./field-model";

export function SelectedBiasChart({ point, average }: { point: VisualizationPoint; average: number | null }) {
  const position = (value: number) => `${(clamp(value, -100, 100) + 100) / 2}%`;
  return <div className="space-inspector__chart">
    <div className="space-inspector__chart-heading"><DefinitionTooltip {...analysisTerms.bias} /><strong>{signed(point.x)}</strong></div>
    <div className="bias-scale" role="img" aria-label={`선택한 자료의 편향성 ${signed(point.x)}${average !== null ? `, 기사 평균 ${signed(average)}` : ""}`}>
      <div className="bias-scale__plot" aria-hidden="true">
        <div className="bias-scale__track"><span className="bias-scale__neutral" /></div>
        {[-100, -50, 0, 50, 100].map((tick) => <span className="bias-scale__tick" key={tick} style={{ left: position(tick) }}><span>{signed(tick)}</span></span>)}
        {average !== null ? <span className="bias-scale__average" style={{ left: position(average) }} /> : null}
        <span className="bias-scale__selected" style={{ left: position(point.x) }} />
      </div>
      <div className="bias-scale__labels" aria-hidden="true"><span>좌편향</span><span>중립</span><span>우편향</span></div>
    </div>
    <div className="bias-scale__legend"><span><i className="bias-scale__key-selected" aria-hidden="true" />선택한 자료 {signed(point.x)}</span>{average !== null ? <span><i className="bias-scale__key-average" aria-hidden="true" />기사 평균 {signed(average)}</span> : null}</div>
  </div>;
}

export function SelectedScoreChart({ point }: { point: VisualizationPoint }) {
  const items = [{ label: "과장성", value: point.type === "user" ? null : point.sensationalism, x: 121 }, { label: "분석 신뢰도", value: point.confidence * 100, x: 241 }];
  return <div className="space-inspector__chart">
    <div className="space-inspector__chart-heading"><span>표현 강도와 분석 신뢰도</span></div>
    <svg viewBox="0 0 340 172" role="img" aria-label={`과장성 ${items[0].value === null ? "해당 없음" : Math.round(items[0].value)}, 분석 신뢰도 ${Math.round(point.confidence * 100)}%`}>
      {[0, 25, 50, 75, 100].map((tick) => <g key={tick}><line className="mini-chart__grid" x1="36" x2="320" y1={135 - tick} y2={135 - tick} /><text x="26" y={139 - tick} textAnchor="end">{tick}</text></g>)}
      {items.map(({ label, value, x }, index) => <g key={label}><rect x={x - 25} y={135 - clamp(value ?? 0, 0, 100)} width="50" height={clamp(value ?? 0, 0, 100)} className={index === 0 ? "mini-chart__bar" : "mini-chart__bar-secondary"} /><text className="mini-chart__value" x={x} y={125 - clamp(value ?? 0, 0, 100)} textAnchor="middle">{value === null ? point.type === "user" ? "해당 없음" : "미측정" : `${Math.round(value)}${index ? "%" : ""}`}</text><text x={x} y="158" textAnchor="middle">{label}</text></g>)}
    </svg>
    <div className="space-inspector__definitions"><DefinitionTooltip {...analysisTerms.sensationalism} /><DefinitionTooltip {...analysisTerms.confidence} /></div>
  </div>;
}

export function DistributionCharts({ points, current }: { points: VisualizationPoint[]; current: VisualizationPoint }) {
  const articles = points.filter((point) => point.type === "article");
  const measured = articles.filter((point) => point.sensationalism !== null);
  const charts = [
    { title: "편향 분포", values: articles.map((point) => point.x), min: -110, max: 110, bins: 11, labels: ["−100", "중립", "+100"], current: current.x, tone: "bias" },
    { title: "과장성 분포", values: measured.map((point) => point.sensationalism!), min: 0, max: 100, bins: 10, labels: ["0", "50", "100"], current: current.type === "user" ? null : current.sensationalism, tone: "sensationalism" },
    { title: "분석 신뢰도 분포", values: articles.map((point) => point.confidence * 100), min: 0, max: 100, bins: 10, labels: ["0%", "50%", "100%"], current: current.confidence * 100, tone: "confidence" },
  ];
  return <div className="space-distributions" aria-label="전체 기사 분석 분포">
    {charts.map((chart) => {
      const bins = histogram(chart.values, chart.min, chart.max, chart.bins);
      const maxCount = Math.max(2, Math.ceil(Math.max(0, ...bins) / 2) * 2);
      const step = 290 / bins.length;
      const selectedBin = chart.current === null || current.type !== "article" ? -1 : Math.min(bins.length - 1, Math.floor((clamp(chart.current, chart.min, chart.max) - chart.min) / (chart.max - chart.min) * bins.length));
      return <section key={chart.title} className="space-distributions__chart" data-tone={chart.tone}>
        <div className="space-distributions__heading"><h3>{chart.title}</h3><span>{chart.values.length}건</span></div>
        <svg viewBox="0 0 340 150" role="img" aria-label={`${chart.title}, 기사 ${chart.values.length}건, 가장 많은 구간 ${Math.max(0, ...bins)}건`}>
          {[0, 1, 2].map((tick) => <g key={tick}><line className="mini-chart__grid" x1="34" x2="324" y1={115 - tick * 44} y2={115 - tick * 44} /><text x="25" y={119 - tick * 44} textAnchor="end">{Math.round(maxCount * tick / 2)}</text></g>)}
          {bins.map((count, index) => <rect key={index} x={34 + index * step + 2} y={115 - count / maxCount * 88} width={step - 4} height={count / maxCount * 88} className={index === selectedBin ? "mini-chart__bar-active" : "mini-chart__bar"} />)}
          {chart.labels.map((label, index) => <text key={label} x={34 + index * 145} y="139" textAnchor={index === 0 ? "start" : index === 2 ? "end" : "middle"}>{label}</text>)}
        </svg>
      </section>;
    })}
  </div>;
}
