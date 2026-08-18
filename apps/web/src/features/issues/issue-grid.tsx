"use client";

import { IssueCard } from "./issue-card";
import { useIssuesQuery } from "@/lib/api/queries";
import type { Issue } from "@/lib/api/types";
import { isMockMode } from "@/lib/api/mode";
import { StatePanel } from "@/components/ui/state-panel";

export function IssueGrid({ fallback, columns = 2 }: { fallback: Issue[]; columns?: 2 | 3 }) {
  const query = useIssuesQuery();
  if (query.isPending && !isMockMode()) return <StatePanel state="loading" />;
  if (query.isError && !isMockMode()) return <StatePanel state="error" onRetry={() => void query.refetch()} />;
  const issues = query.data?.items ?? (isMockMode() ? fallback : []);
  if (issues.length === 0) return <StatePanel state="empty" />;
  return <div className={`grid grid--${columns}`}>{issues.map((issue) => <IssueCard key={issue.id} issue={issue} />)}</div>;
}
