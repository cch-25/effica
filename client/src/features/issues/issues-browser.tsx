"use client";

import Link from "next/link";
import { useState } from "react";
import { useIssuesQuery } from "@/lib/api/queries";
import type { Issue } from "@/lib/api/types";
import { isMockMode } from "@/lib/api/mode";
import { StatePanel } from "@/components/ui/state-panel";
import { Button } from "@/components/ui/button";
import { compareIssueImportance, isSupportedIssue } from "./issue-selection";

export function IssuesBrowser({ fallback }: { fallback: Issue[] }) {
  const query = useIssuesQuery(250);
  const [topic, setTopic] = useState("");
  const issues = (query.data?.items ?? (isMockMode() ? fallback : [])).filter(isSupportedIssue).sort(compareIssueImportance);
  const topics = [...new Set(issues.map((issue) => issue.topic))];
  const visible = issues.filter((issue) => !topic || issue.topic === topic);
  const articleCount = new Set(visible.flatMap((issue) => issue.articleIds)).size;
  if (query.isPending && !isMockMode()) return <StatePanel state="loading" />;
  if (query.isError && !isMockMode()) return <StatePanel state="error" onRetry={() => void query.refetch()} />;
  return <div className="issues-page ux-issue-index">
    <header className="page-header"><div><h1>오늘의 이슈</h1><p>이슈를 선택해 여러 언론사의 사실과 관점을 비교하세요.</p></div><p aria-live="polite">{visible.length}개 이슈 / {articleCount}개 기사</p></header>
    {topics.length > 1 && <nav className="article-categories" aria-label="이슈 주제">{["", ...topics].map((item) => <Button key={item} variant="ghost" aria-pressed={item === topic} onClick={() => setTopic(item)}>{item || "전체"}</Button>)}</nav>}
    {visible.length ? <ol className="ux-issue-list">{visible.map((issue) => <li key={issue.id}><Link href={`/issues/${issue.id}`}><div><small>{issue.coverageGroupTitle && issue.coverageGroupTitle !== issue.title ? `${issue.coverageGroupTitle} / 세부 이슈` : issue.topic}{issue.kind === "TOPIC" ? " / 주제별 기사" : ""}</small><h2>{issue.title}</h2></div><span>{issue.articleIds.length}개 기사 / {issue.sourceCount}개 출처<strong>{issue.kind === "TOPIC" ? "기사 살펴보기" : "보도 비교하기"} →</strong></span></Link></li>)}</ol> : <p>현재 표시할 이슈가 없습니다.</p>}
    {query.hasNextPage && <Button variant="secondary" disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>이슈 더 보기</Button>}
  </div>;
}
