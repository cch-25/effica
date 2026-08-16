"use client";

import { IssueCard } from "./issue-card";
import { useIssuesQuery } from "@/lib/api/queries";
import type { Issue } from "@/lib/api/types";

export function IssueGrid({ fallback, columns = 2 }: { fallback: Issue[]; columns?: 2 | 3 }) {
  const query = useIssuesQuery();
  const issues = query.data?.items ?? fallback;
  return <div className={`grid grid--${columns}`}>{issues.map((issue) => <IssueCard key={issue.id} issue={issue} />)}</div>;
}
