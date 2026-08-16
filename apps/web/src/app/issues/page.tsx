import { Filter } from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { IssueCard } from "@/features/issues/issue-card";
import { issues } from "@/mocks/fixtures/content";

export const metadata = { title: "이슈" };

export default function IssuesPage() {
  return (
    <>
      <PageHeader eyebrow="Issues / 03" title="오늘의 이슈를 관점별로" description="기사가 충분히 모인 이슈만 균형 묶음으로 표시합니다. 조건을 충족하지 못한 이슈는 준비 중 상태를 숨기지 않습니다." actions={<button className="button button--secondary"><Filter size={16} /> 주제·기간</button>} />
      <div className="grid grid--2">{issues.map((issue) => <IssueCard key={issue.id} issue={issue} />)}</div>
    </>
  );
}
