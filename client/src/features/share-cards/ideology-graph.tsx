"use client";

import { useMemo } from "react";
import { InteractiveGraph } from "@/components/graphs/interactive-graph";
import type { GraphPoint } from "@/components/graphs/graph-model";
import { signed } from "@/features/visualization/field-model";
import type { Ideology } from "./consumption";
import { ideologyAxes, ideologyRegions, interpretIdeology } from "./ideology-model";

export function IdeologyGraph({ ideology }: { ideology: Ideology }) {
  const result = interpretIdeology(ideology);
  const completed = result !== null;
  const [x, y, z] = result?.values ?? [0, 0, 0];
  const label = result?.label ?? "검사 미실시";
  const points = useMemo<GraphPoint[]>(() => completed ? [{ id: "ideology", ids: ["ideology"], label, values: [x, y, z] }] : [], [completed, label, x, y, z]);
  return <div className="ideology-graph">
    <p className="ideology-graph__intro">좌우 성향에 권력과 자유, 국가 간 관계에 대한 생각을 더한 지도입니다.</p>
    {result && <p className="ideology-graph__result"><strong>{result.label}</strong><span>국제관: {result.international === "혼합" ? "주권과 국제 협력 사이" : `${result.international} 성향`}</span></p>}
    <InteractiveGraph axes={ideologyAxes} regions={ideologyRegions} points={points} selectedId="ideology"
      title={completed ? `${label}. 검사 결과: 경제 ${x}, 사회문화 ${y}, 국제 ${z}. 가로는 좌파와 우파, 위는 권위주의, 아래는 자유주의, 깊이는 주권주의와 국제주의.` : "검사 미실시: 기본 좌표 (0,0,0). 중도 성향을 뜻하지 않습니다."}
      emptyMessage="검사를 마치면 나의 위치가 표시됩니다." />
    {result ? <dl className="ideology-coordinates">
      {[["좌우 성향", result.economic, x, "재분배와 공공 역할 ↔ 시장과 경쟁"], ["권위 / 자유", result.authority, y, "국가 통제 ↔ 개인의 자유와 권리"], ["국제관", result.international, z, "국가 주권 우선 ↔ 국제 협력 우선"]].map(([axis, tendency, value, description]) => <div key={axis}><dt>{axis}</dt><dd>{tendency} <span>{signed(Number(value))}</span></dd><p>{description}</p></div>)}
    </dl> : <p className="ideology-graph__note">검사 미실시 / 기본 좌표 (0,0,0)<br />아직 측정하지 않은 상태이며 중도를 뜻하지 않습니다.</p>}
    <details className="ideology-graph__method"><summary>이념 지도 읽는 법</summary>
      <p>왼쪽은 재분배와 공공 역할을 중시하는 좌파, 오른쪽은 시장과 경쟁을 중시하는 우파입니다. 이 지도의 좌우는 경제정책에 대한 응답을 기준으로 합니다.</p>
      <p>위쪽은 질서와 국가 통제를 중시하는 권위주의, 아래쪽은 개인의 자유와 권리를 중시하는 자유주의입니다. 자유주의는 여기서 시민적 자유를 뜻하며, 좌파와 우파 어느 쪽에도 나타날 수 있습니다.</p>
      <p>깊이는 주권주의와 국제주의를 구분합니다. 주권주의는 자국의 결정권을, 국제주의는 국가 간 협력을 우선합니다. 국제관은 좌우 판정에 합산하지 않습니다.</p>
      <p>각 축의 10문항을 -100~100으로 환산합니다. -10~+10은 좌우 축에서 중도, 나머지 축에서 혼합으로 표시합니다. 가까운 구간을 묶기 위한 표시 기준이며 특정 정당이나 사상을 확정하는 진단은 아닙니다.</p>
    </details>
    {completed && <p className="ideology-graph__note">검사 응답 기준 / 베타 결과<br />기사에 내린 평가는 이 좌표에 반영되지 않습니다.</p>}
  </div>;
}
