import type { Ideology } from "./consumption";
import { interpretIdeology } from "./ideology-model";

export function IdeologyGraph({ ideology }: { ideology: Ideology }) {
  const result = interpretIdeology(ideology);
  if (!result) return <p>아직 검사하지 않았습니다. 내 위치를 표시하려면 선택 설문에 응답해 주세요.</p>;
  const [x, y, z] = result.values;
  return <div className="ideology-graph"><p><strong>{result.label}</strong> / 국제관: {result.international}</p><div className="ux-ideology-plots">{[{ title: "좌우 성향과 권위 / 자유", value: y, top: "권위주의", bottom: "자유주의", reverse: true }, { title: "좌우 성향과 국제관", value: z, top: "국제 협력", bottom: "국가 주권", reverse: false }].map((axis) => <figure key={axis.title}><figcaption>{axis.title}</figcaption><svg viewBox="0 0 340 290" role="img" aria-label={`${axis.title}: 좌우 ${x}, 세로 ${axis.value}`}><path d="M50 35H290V245H50Z M170 35V245 M50 140H290" fill="none" stroke="currentColor" opacity=".25" /><text x="170" y="22" textAnchor="middle">{axis.top}</text><text x="170" y="275" textAnchor="middle">{axis.bottom}</text><text x="55" y="135">좌파</text><text x="285" y="135" textAnchor="end">우파</text><circle cx={170 + x * 1.2} cy={140 + axis.value * (axis.reverse ? 1.05 : -1.05)} r="7" fill="var(--accent)" /></svg></figure>)}</div><p>설문 응답을 -100부터 100으로 환산한 베타 결과입니다. 기사에 내린 평가는 이 위치에 반영되지 않습니다.</p></div>;
}
