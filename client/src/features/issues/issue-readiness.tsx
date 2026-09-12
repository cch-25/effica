import { CircleDashed } from "lucide-react";

export function IssueReadiness({ articleCount, sourceCount }: { articleCount: number; sourceCount: number }) {
  const gathering = articleCount < 2 || sourceCount < 2;
  return (
    <section className="issue-readiness" role="status" aria-label="이슈 비교 준비 상태">
      <CircleDashed size={18} aria-hidden="true" />
      <div>
        <strong>{gathering ? "확보한 기사의 분석을 준비하고 있습니다." : "교차 기사 분석을 편집 검수하고 있습니다."}</strong>
        <p>{gathering ? "이 이슈는 서로 다른 언론사 3곳 이상의 원문을 확보했습니다. 기사별 분석이 끝나면 점수를 비교할 수 있습니다." : "기사별 공개 점수는 바로 비교할 수 있으며, 공통 사실과 보도 프레임은 편집 검수가 끝난 뒤 공개됩니다."}</p>
        <span>비교 준비 완료 기사 {articleCount}개, 출처 {sourceCount}곳</span>
      </div>
    </section>
  );
}
