import { ExternalLink } from "lucide-react";
import { ButtonLink } from "@/components/ui/button";
import { IdeologyGraph } from "./ideology-graph";
import type { ConsumptionSnapshot } from "./consumption";

export function PerspectivePreview({ displayName, template, compact = false, snapshot, publicView = false }: {
  displayName: string;
  template?: "orbit" | "editorial";
  compact?: boolean;
  snapshot?: ConsumptionSnapshot | null;
  publicView?: boolean;
}) {
  const title = displayName ? `${displayName}의 뉴스 소비 성향` : "나의 뉴스 소비 성향";
  return <section className={`share-preview consumption-preview${template ? ` share-preview--${template}` : ""}${compact ? " consumption-preview--compact" : ""}`} aria-label={title}>
    <p>{publicView ? "카드를 만든 시점의 기록" : "현재 내 활동 기준 미리보기"}</p>
    <h2>{title}</h2>
    {!snapshot ? <p role="status">뉴스 소비 기록을 확인하지 못했습니다. 잠시 후 다시 불러와 주세요.</p> : <>
      <div className="axis" aria-label={`뉴스 소비 다양성 ${snapshot.diversity_score}/100`}>
        <div className="axis__head"><strong>다양성</strong><span>{snapshot.diversity_score}/100</span></div>
        <div className="axis__track" aria-hidden="true"><span className="axis__marker" style={{ left: `${snapshot.diversity_score}%` }} /></div>
        <div className="axis__labels"><span>0 낮음</span><span>100 높음</span></div>
        <div className="axis__labels diversity-descriptions"><span>단일한 정치성향의<br />뉴스 위주 소비</span><span>다양한 정치성향의<br />뉴스 균형 소비</span></div>
        <small>{snapshot.diversity_article_count ? `읽거나 평가한 기사 중 공개 분석이 있는 ${snapshot.diversity_article_count}개 기준` : "아직 점수에 반영할 기사 기록이 없습니다."}</small>
        {!publicView && <details className="diversity-method"><summary>다양성 점수는 어떻게 계산하나요?</summary><p>읽기 확인을 마쳤거나 평가한 서로 다른 기사를 기준으로 계산합니다. 기사의 공개 편향 점수를 좌측, 중앙, 우측으로 나누고 세 구간을 얼마나 고르게 소비했는지 반영합니다. 점수가 -10~10인 기사는 중앙 구간입니다.</p><p>12개 기사까지는 기록 수가 많아질수록 반영 비율이 커집니다. 같은 기사를 반복해서 읽거나 평가해도 한 번만 셉니다. 이 점수는 본인의 정치성향을 뜻하지 않습니다.</p></details>}
      </div>
      <div className="consumption-ideology"><h3>3차원 이념 위치</h3><IdeologyGraph ideology={snapshot.ideology} /></div>
      {!publicView && <ButtonLink variant="secondary" href="/onboarding/questionnaire?returnTo=%2Fshare%2Fnew" target="_blank" rel="noopener noreferrer">{snapshot.ideology.completed ? "정치 이념 검사 다시 하기" : "정치 이념 검사 하러 가기"}<ExternalLink size={14} aria-hidden="true" /></ButtonLink>}
    </>}
  </section>;
}
