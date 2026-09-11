"use client";

import { useMemo } from "react";
import { InteractiveGraph } from "@/components/graphs/interactive-graph";
import type { GraphAxes, GraphPoint } from "@/components/graphs/graph-model";
import { signed } from "@/features/visualization/field-model";
import type { Ideology } from "./consumption";

const axes: GraphAxes = [
  { label: "경제", min: -100, max: 100, low: "경제적 좌", high: "경제적 우" },
  { label: "국제", min: -100, max: 100, low: "민족 / 주권", high: "국제 / 세계" },
  { label: "사회문화", min: -100, max: 100, low: "권위주의", high: "자유주의" },
];

export function IdeologyGraph({ ideology }: { ideology: Ideology }) {
  const { completed } = ideology;
  const [x, y, z] = completed ? [ideology.x, ideology.y, ideology.z].map((value) => Math.max(-100, Math.min(100, value))) : [0, 0, 0];
  const points = useMemo<GraphPoint[]>(() => completed ? [{ id: "ideology", ids: ["ideology"], label: "나의 검사 결과", values: [x, z, y] }] : [], [completed, x, y, z]);
  return <div className="ideology-graph">
    <InteractiveGraph axes={axes} points={points} selectedId="ideology"
      title={completed ? `검사 결과: 경제 ${x}, 사회문화 ${y}, 국제 ${z}` : "검사 미실시: 기본 좌표 (0,0,0). 중도 성향을 뜻하지 않습니다."}
      emptyMessage="검사를 마치면 나의 위치가 표시됩니다." />
    {completed ? <dl className="ideology-coordinates"><div><dt>경제 (X)</dt><dd>{signed(x)}</dd></div><div><dt>사회문화 (Y)</dt><dd>{signed(y)}</dd></div><div><dt>국제 (Z)</dt><dd>{signed(z)}</dd></div></dl> : <p className="ideology-graph__note">검사 미실시 / 기본 좌표 (0,0,0)<br />아직 측정하지 않은 상태이며 중도를 뜻하지 않습니다.</p>}
    {completed && <p className="ideology-graph__note">검사 응답 기준 / 베타 결과<br />기사에 내린 평가는 이 좌표에 반영되지 않습니다.</p>}
  </div>;
}
