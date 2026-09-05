import Link from "next/link";
import type { Issue } from "@/lib/api/types";

function formatIssueDate(issue: Issue): { dateTime: string; label: string } {
  const dateTime = issue.dataAsOf ?? issue.updatedAt;
  const date = new Date(dateTime);
  const label = Number.isFinite(date.getTime())
    ? new Intl.DateTimeFormat("ko-KR", {
        month: "long",
        day: "numeric",
        timeZone: "Asia/Seoul",
      }).format(date)
    : "기준일 확인 중";

  return { dateTime, label };
}

export function IssueCard({ issue }: { issue: Issue }) {
  const ready = issue.analysisStatus === "READY" && issue.articleIds.length >= 2 && issue.sourceCount >= 2;
  const statusLabel = ready ? "비교 가능" : issue.analysisStatus === "UNTRUSTED" ? "신뢰 분석 필요" : issue.analysisStatus === "PARTIAL" ? "일부 분석 중" : "분석 준비 중";
  const issueDate = formatIssueDate(issue);

  return (
    <article className="issue-card">
      <div className="issue-card__top">
        <span className="issue-card__topic">{issue.kind === "EVENT" ? issue.topic : "주제"}</span>
        <span className={`issue-card__status issue-card__status--${ready ? "ready" : "pending"}`}>{statusLabel}</span>
      </div>
      <h2><Link href={`/issues/${issue.id}`}>{issue.title}</Link></h2>
      <p>{issue.summary}</p>
      <div className="issue-card__foot">
        <span className="issue-card__meta">
          <time dateTime={issueDate.dateTime}>{issueDate.label} 기준</time>
          <span>기사 {issue.articleIds.length}개 / 출처 {issue.sourceCount}곳</span>
        </span>
        <Link href={`/issues/${issue.id}`}>{ready ? "보도 비교하기" : "준비 상태 보기"} →</Link>
      </div>
    </article>
  );
}
