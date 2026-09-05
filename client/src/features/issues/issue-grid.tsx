"use client";

import { IssueCard } from "./issue-card";
import { useIssuesQuery } from "@/lib/api/queries";
import type { Issue } from "@/lib/api/types";
import { isMockMode } from "@/lib/api/mode";
import { StatePanel } from "@/components/ui/state-panel";

export function IssueGrid({ fallback, columns = 2, featuredOnly = false }: { fallback: Issue[]; columns?: 2 | 3; featuredOnly?: boolean }) {
  const query = useIssuesQuery();
  if (query.isPending && !isMockMode()) return <StatePanel state="loading" />;
  if (query.isError && !isMockMode()) return <StatePanel state="error" onRetry={() => void query.refetch()} />;
  const source = query.data?.items ?? (isMockMode() ? fallback : []);
  const issues = featuredOnly
    ? source
        .filter((issue) => issue.kind === "EVENT" && issue.analysisStatus === "READY" && issue.freshnessStatus === "CURRENT" && issue.sourceCount >= 3)
        .sort((left, right) => {
          const rightTime = new Date(right.dataAsOf ?? right.updatedAt).getTime();
          const leftTime = new Date(left.dataAsOf ?? left.updatedAt).getTime();
          return rightTime - leftTime || (left.editorialPriority ?? Number.MAX_SAFE_INTEGER) - (right.editorialPriority ?? Number.MAX_SAFE_INTEGER);
        })
    : source;
  if (issues.length === 0) return <StatePanel state="empty" />;
  return (
    <ol className={`issue-list issue-list--${columns}`}>
      {issues.map((issue) => <li key={issue.id}><IssueCard issue={issue} /></li>)}
    </ol>
  );
}
