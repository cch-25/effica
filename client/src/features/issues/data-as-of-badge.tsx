"use client";

import { Badge } from "@/components/ui/badge";
import { formatDataAsOf } from "@/lib/api/formatters";
import { isMockMode } from "@/lib/api/mode";
import { useIssuesQuery } from "@/lib/api/queries";
import type { Issue } from "@/lib/api/types";

export function DataAsOfBadge({ fallback }: { fallback: Issue[] }) {
  const query = useIssuesQuery();
  const issues = query.data?.items ?? (isMockMode() ? fallback : []);
  const featured = issues
    .filter((issue) => issue.kind === "EVENT" && issue.analysisStatus === "READY" && issue.dataAsOf)
    .sort((left, right) => (right.dataAsOf ?? "").localeCompare(left.dataAsOf ?? ""));
  const issue = featured[0];
  if (!issue?.dataAsOf) return <Badge tone="warning">데이터 기준일 확인 중</Badge>;
  const prefix = isMockMode() ? "데모 " : "";
  return (
    <Badge tone={issue.freshnessStatus === "UPDATE_NEEDED" ? "warning" : "positive"}>
      {prefix}{formatDataAsOf(issue.dataAsOf)}{issue.freshnessStatus === "UPDATE_NEEDED" ? ", 업데이트 필요" : ""}
    </Badge>
  );
}
