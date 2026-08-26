import Link from "next/link";
import type { Issue } from "@/lib/api/types";
import { Badge } from "@/components/ui/badge";

export function IssueCard({ issue }: { issue: Issue }) {
  const ready = issue.analysisStatus === "READY" && issue.sourceCount >= 3;
  const statusLabel = ready ? "비교 가능" : issue.analysisStatus === "UNTRUSTED" ? "신뢰 분석 필요" : issue.analysisStatus === "PARTIAL" ? "일부 분석 중" : "분석 준비 중";
  return (
    <article className="card issue-card">
      <div className="issue-card__top"><Badge>{issue.kind === "EVENT" ? "사건" : issue.topic}</Badge><Badge tone={ready ? "positive" : "warning"}>{statusLabel}</Badge></div>
      <h2><Link href={`/issues/${issue.id}`}>{issue.title}</Link></h2>
      <p>{issue.summary}</p>
      <div className="issue-card__foot"><span>{issue.articleIds.length}개 기사 · {issue.sourceCount}개 출처</span><Link href={`/issues/${issue.id}`}>이슈 살펴보기 →</Link></div>
    </article>
  );
}
