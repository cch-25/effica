import Link from "next/link";
import type { Issue } from "@/lib/api/types";
import { Badge } from "@/components/ui/badge";

export function IssueCard({ issue }: { issue: Issue }) {
  return (
    <article className="card issue-card">
      <div className="issue-card__top"><Badge>{issue.topic}</Badge><Badge tone={issue.status === "balanced" ? "positive" : "warning"}>{issue.status === "balanced" ? "비교 가능" : "균형 묶음 준비 중"}</Badge></div>
      <h2><Link href={`/issues/${issue.id}`}>{issue.title}</Link></h2>
      <p>{issue.summary}</p>
      <div className="issue-card__foot"><span>{issue.articleIds.length}개 기사</span><Link href={`/issues/${issue.id}`}>이슈 살펴보기 →</Link></div>
    </article>
  );
}
