import { ArrowUpRight, BookOpenCheck, Scale, Sparkles } from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { ButtonLink } from "@/components/ui/button";

export default function ProgressPage() {
  return <><PageHeader eyebrow="My activity / policy-v4" title="읽고 비교한 기록" description="활동 크레딧은 검증된 비교·복귀 활동의 기록이며 정치적 정답이나 우열을 뜻하지 않습니다." actions={<ButtonLink variant="secondary" href="/efficacy">효능감 추이 <ArrowUpRight size={15} /></ButtonLink>} />
  <div className="grid grid--4"><section className="card metric"><small>누적 크레딧</small><strong>684</strong><span className="metric__delta">이번 주 +42</span></section><section className="card metric"><small>현재 레벨</small><strong>Lv. 7</strong><span className="metric__delta">다음까지 116</span></section><section className="card metric"><small>활동 티어</small><strong>탐색가</strong><span className="metric__delta">credit snapshot</span></section><section className="card metric"><small>비교 완료 이슈</small><strong>18</strong><span className="metric__delta">3개 관점 평균</span></section></div>
  <div className="section-head"><h2>크레딧 이력</h2><Badge>immutable ledger</Badge></div><div className="table-wrap"><table className="data-table"><thead><tr><th>활동</th><th>기록 시각</th><th>변동</th><th>정책</th></tr></thead><tbody><tr><td><BookOpenCheck size={15} /> 원문 읽기 복귀 확인</td><td>2026-08-16 12:41</td><td>+12</td><td>credit-v4</td></tr><tr><td><Scale size={15} /> 이슈 비교 완료</td><td>2026-08-15 21:06</td><td>+20</td><td>credit-v4</td></tr><tr><td><Sparkles size={15} /> 잘못 지급된 크레딧 reversal</td><td>2026-08-14 09:21</td><td>−8</td><td>credit-v4</td></tr></tbody></table></div></>;
}
