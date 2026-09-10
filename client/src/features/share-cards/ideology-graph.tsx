import { useId } from "react";
import type { Ideology } from "./consumption";

function project(x: number, y: number, z: number) {
  return [240 + x * 1.25 + y * .72, 197 + x * .30 - y * .53 - z * 1.05];
}
function path(points: number[][]) { return points.map((point, i) => `${i ? "L" : "M"}${point.join(",")}`).join(" "); }

export function IdeologyGraph({ ideology }: { ideology: Ideology }) {
  const titleId = useId();
  const { completed } = ideology;
  const coords = completed ? [ideology.x, ideology.y, ideology.z].map((n) => Math.max(-100, Math.min(100, n))) : [0, 0, 0];
  const [x, y, z] = coords;
  const position = project(x, y, z);
  const floor = project(x, y, -70);
  const edges = [-70, 70].flatMap((a) => [-70, 70].flatMap((b) => [
    [project(-70, a, b), project(70, a, b)],
    [project(a, -70, b), project(a, 70, b)],
    [project(a, b, -70), project(a, b, 70)],
  ]));
  return <div className="ideology-graph">
    <svg viewBox="0 0 500 370" role="img" aria-labelledby={titleId}>
      <title id={titleId}>{completed ? `검사 결과: 경제 ${x}, 사회문화 ${y}, 국제 ${z}` : "검사 미실시: 기본 좌표 (0,0,0). 중도 성향을 뜻하지 않습니다."}</title>
      <g fill="none" stroke="var(--line)" strokeWidth="1">{edges.map((edge, i) => <path key={i} d={path(edge)} />)}</g>
      <g fill="none" strokeWidth="2">
        <path d={path([project(-115, 0, 0), project(115, 0, 0)])} stroke="#303030" />
        <path d={path([project(0, -115, 0), project(0, 115, 0)])} stroke="#5a5a5a" strokeDasharray="6 4" />
        <path d={path([project(0, 0, -100), project(0, 0, 115)])} stroke="#404040" strokeDasharray="2 4" />
        {completed && <path d={path([position, floor])} stroke="var(--muted)" strokeDasharray="4 4" strokeWidth="1" />}
      </g>
      <g className="ideology-graph__labels" textAnchor="middle">
        <text x="65" y="154" fill="#303030">경제적 좌</text><text x="414" y="245" fill="#303030">경제적 우</text>
        <text x="141" y="281" fill="#5a5a5a">사회문화적</text><text x="141" y="299" fill="#5a5a5a">권위주의</text>
        <text x="368" y="128" fill="#5a5a5a">사회문화적</text><text x="368" y="146" fill="#5a5a5a">자유주의</text>
        <text x="240" y="42" fill="#404040">국제주의 / 세계주의</text>
        <text x="240" y="337" fill="#404040">민족주의 / 주권주의</text>
      </g>
      <circle cx={position[0]} cy={position[1]} r="7" fill="var(--ink)" stroke="var(--paper, #ffffff)" strokeWidth="2" />
      {!completed && <text x={position[0] + 12} y={position[1] - 10} className="ideology-graph__coordinate">(0,0,0)</text>}
    </svg>
    {completed ? <dl className="ideology-coordinates"><div><dt>경제 (X)</dt><dd>{x > 0 ? "+" : ""}{x}</dd></div><div><dt>사회문화 (Y)</dt><dd>{y > 0 ? "+" : ""}{y}</dd></div><div><dt>국제 (Z)</dt><dd>{z > 0 ? "+" : ""}{z}</dd></div></dl> : <p className="ideology-graph__note">검사 미실시 / 기본 좌표 (0,0,0)<br />아직 측정하지 않은 상태이며 중도를 뜻하지 않습니다.</p>}
    {completed && <p className="ideology-graph__note">검사 응답 기준 / 베타 결과<br />기사에 내린 평가는 이 좌표에 반영되지 않습니다.</p>}
  </div>;
}
