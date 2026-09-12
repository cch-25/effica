export function IssueReadiness({ articleCount, sourceCount }: { articleCount: number; sourceCount: number }) {
  return <section className="issue-readiness" role="status" aria-label="이슈 비교 준비 상태"><div><strong>이 기사 조합의 공통 사실과 관점 비교는 아직 제공되지 않습니다.</strong><p>현재 분석 완료: 기사 {articleCount}개 / 출처 {sourceCount}곳. 기사별 분석과 원문은 아래 링크에서 확인할 수 있습니다.</p></div></section>;
}
