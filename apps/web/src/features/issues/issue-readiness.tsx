import { CircleDashed } from "lucide-react";

export function IssueReadiness({ articleCount, sourceCount }: { articleCount: number; sourceCount: number }) {
  const gathering = articleCount < 2 || sourceCount < 2;
  return (
    <section className="issue-readiness" role="status" aria-label="이슈 비교 준비 상태">
      <CircleDashed size={18} aria-hidden="true" />
      <div>
        <strong>{gathering ? "비교할 보도를 더 모으고 있습니다." : "교차 기사 분석을 편집 검수하고 있습니다."}</strong>
        <p>{gathering ? "서로 다른 출처의 기사 2개 이상이 모이면 기사별 분석 비교를 시작합니다." : "기사별 공개 점수는 바로 비교할 수 있으며, 공통 사실과 보도 프레임은 편집 검수가 끝난 뒤 공개됩니다."}</p>
        <span>현재 기사 {articleCount}개 · 출처 {sourceCount}곳</span>
      </div>
    </section>
  );
}
