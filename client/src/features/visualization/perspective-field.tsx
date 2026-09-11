"use client";

import { useMemo } from "react";
import { Box, ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { InteractiveGraph } from "@/components/graphs/interactive-graph";
import type { GraphAxes, GraphPoint } from "@/components/graphs/graph-model";
import type { VisualizationPoint } from "@/lib/api/types";
import { makeSpaceData, signed } from "./field-model";

export type { FieldView } from "./field-model";
const axes: GraphAxes = [
  { label: "편향성", min: -100, max: 100, low: "−100 좌편향", high: "+100 우편향" },
  { label: "과장성", min: 0, max: 100, low: "0 낮음", high: "100 높음" },
  { label: "분석 신뢰도", min: 0, max: 100, suffix: "%", low: "0%", high: "100%" },
];

type Props = { points: VisualizationPoint[]; selectedId: string; anchorId: string | undefined; title: string; onSelect: (id: string) => void };

export function PerspectiveField({ points, selectedId, anchorId, title, onSelect }: Props) {
  const data = useMemo<GraphPoint[]>(() => makeSpaceData(points).map((datum) => ({
    id: datum.ids[0], ids: datum.ids, label: datum.name,
    values: [datum.value[0], datum.value[2], datum.value[1]],
  })), [points]);
  const measuredIds = new Set(data.flatMap((datum) => datum.ids));
  const measured = points.filter((point) => measuredIds.has(point.id));
  const selected = points.find((point) => point.id === selectedId);
  const index = measured.findIndex((point) => point.id === selectedId);
  const anchor = points.find((point) => point.id === anchorId && point.type === "user");

  return <div className="article-space">
    <div className="article-space__topline"><span><Box size={14} /> 관점 공간</span><span>{measured.length}개 자료{anchor ? ` / 나의 편향 ${signed(anchor.x)}` : ""}</span></div>
    <InteractiveGraph axes={axes} points={data} selectedId={selectedId} title={title}
      onSelect={(ids) => onSelect(ids[(ids.indexOf(selectedId) + 1) % ids.length])}
      emptyMessage="좌표를 표시할 측정 자료가 없습니다." />
    <div className="article-space__selection">
      {selected && selected.type !== "user" ? <dl className="article-space__readout" aria-label="선택한 자료의 공간 좌표">
        <div><dt>편향</dt><dd>{signed(selected.x)}</dd></div>
        <div><dt>과장</dt><dd>{selected.sensationalism === null ? "미측정" : Math.round(selected.sensationalism)}</dd></div>
        <div><dt>신뢰도</dt><dd>{Math.round(selected.confidence * 100)}%</dd></div>
      </dl> : <span>아래 목록에서 자료를 선택하세요.</span>}
      <nav className="article-space__navigation" aria-label="그래프 자료 선택"><span>{index < 0 ? "0" : index + 1} / {measured.length}</span>
        <Button variant="ghost" aria-label="이전 자료" disabled={index <= 0} onClick={() => measured[index - 1] && onSelect(measured[index - 1].id)}><ChevronLeft size={17} /></Button>
        <Button variant="ghost" aria-label="다음 자료" disabled={index >= measured.length - 1} onClick={() => measured[index + 1] && onSelect(measured[index + 1].id)}><ChevronRight size={17} /></Button>
      </nav>
    </div>
    <div className="article-space__caption"><span><i /> 자료 <i className="is-selected" /> 선택</span><p>숫자는 같은 좌표의 자료 수 / 점을 다시 누르면 다음 자료</p></div>
  </div>;
}
