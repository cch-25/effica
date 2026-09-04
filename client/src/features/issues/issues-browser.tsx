"use client";

import { ChevronDown, ChevronUp, Filter, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Drawer } from "@/components/ui/drawer";
import { CheckboxField, SelectField } from "@/components/ui/form-controls";
import { useIssueArticleCollectionsQuery, useIssuesQuery } from "@/lib/api/queries";
import type { Article, Issue } from "@/lib/api/types";
import { isMockMode } from "@/lib/api/mode";
import { StatePanel } from "@/components/ui/state-panel";

type Period = "all" | "day" | "week" | "month";

const periodOptions = [
  { value: "all", label: "전체 기간" },
  { value: "day", label: "최근 24시간" },
  { value: "week", label: "최근 7일" },
  { value: "month", label: "최근 30일" },
];

const periodInMilliseconds: Record<Exclude<Period, "all">, number> = {
  day: 24 * 60 * 60 * 1000,
  week: 7 * 24 * 60 * 60 * 1000,
  month: 30 * 24 * 60 * 60 * 1000,
};

const preferredTopicOrder = ["정치", "사회", "경제", "국제", "산업", "문화", "스포츠", "기타"];
const collapsedTopicLength = 6;
const genericTopicTitles = new Set(["정치", "사회", "경제", "국제", "산업", "문화", "스포츠", "기타", "과학", "기술"]);
const genericTopicSummary = /분야의 최신 한국어 원문 기사 모음/;

function isSubstantiveEventIssue(issue: Issue): boolean {
  return issue.kind === "EVENT"
    && issue.analysisStatus === "READY"
    && issue.freshnessStatus === "CURRENT"
    && issue.articleIds.length >= 3
    && issue.sourceCount >= 3
    && issue.summary.trim().length > 0
    && !genericTopicTitles.has(issue.title.trim())
    && !genericTopicSummary.test(issue.summary);
}

function compareIssueImportance(left: Issue, right: Issue): number {
  const leftReady = left.analysisStatus === "READY" ? 1 : 0;
  const rightReady = right.analysisStatus === "READY" ? 1 : 0;
  const leftCurrent = left.freshnessStatus === "CURRENT" ? 1 : 0;
  const rightCurrent = right.freshnessStatus === "CURRENT" ? 1 : 0;
  const leftPriority = left.editorialPriority ?? Number.MAX_SAFE_INTEGER;
  const rightPriority = right.editorialPriority ?? Number.MAX_SAFE_INTEGER;

  return rightReady - leftReady
    || leftPriority - rightPriority
    || right.sourceCount - left.sourceCount
    || right.articleIds.length - left.articleIds.length
    || rightCurrent - leftCurrent
    || new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime()
    || left.id.localeCompare(right.id);
}

function topicOrder(left: string, right: string): number {
  const leftIndex = preferredTopicOrder.indexOf(left);
  const rightIndex = preferredTopicOrder.indexOf(right);
  if (leftIndex >= 0 || rightIndex >= 0) {
    return (leftIndex < 0 ? preferredTopicOrder.length : leftIndex)
      - (rightIndex < 0 ? preferredTopicOrder.length : rightIndex);
  }
  return left.localeCompare(right, "ko");
}

function IssueCounts({ issue }: { issue: Issue }) {
  return <span>{issue.articleIds.length}개 기사, {issue.sourceCount}개 출처</span>;
}

function ArticleDate({ article }: { article: Article }) {
  const value = new Date(article.publishedAt);
  const label = Number.isFinite(value.getTime())
    ? new Intl.DateTimeFormat("ko-KR", { month: "2-digit", day: "2-digit" }).format(value)
    : "날짜 확인 중";
  return <span>{article.source}, {label}</span>;
}

function TopicSection({
  id,
  topic,
  issues,
  collectionIssueIds,
  expanded,
  onToggle,
}: {
  id: string;
  topic: string;
  issues: Issue[];
  collectionIssueIds: string[];
  expanded: boolean;
  onToggle: () => void;
}) {
  const collection = useIssueArticleCollectionsQuery(collectionIssueIds);
  const rows = [
    ...issues.map((issue) => ({ kind: "issue" as const, id: issue.id, issue })),
    ...collection.items.map((article) => ({ kind: "article" as const, id: article.id, article })),
  ];
  const displayedRows = expanded ? rows : rows.slice(0, collapsedTopicLength);

  return (
    <section className="topic-section" id={id} aria-labelledby={`${id}-title`}>
      <header className="topic-section__head">
        <h3 id={`${id}-title`}>{topic}</h3>
        <span>{issues.length}개 이슈, {collection.items.length}개 기사</span>
      </header>
      <ul className="topic-issue-list">
        {displayedRows.map((row) => (
          <li key={`${row.kind}-${row.id}`}>
            {row.kind === "issue" ? (
              <Link className="topic-issue-row" href={`/issues/${row.issue.id}`}>
                <span className="topic-issue-row__copy">
                  <small>이슈</small>
                  <strong>{row.issue.title}</strong>
                  {row.issue.summary ? <span>{row.issue.summary}</span> : null}
                </span>
                <IssueCounts issue={row.issue} />
              </Link>
            ) : (
              <Link className="topic-issue-row topic-article-row" href={`/articles/${row.article.id}`}>
                <span className="topic-issue-row__copy">
                  <small>기사</small>
                  <strong>{row.article.title}</strong>
                  {row.article.dek ? <span>{row.article.dek}</span> : null}
                </span>
                <ArticleDate article={row.article} />
              </Link>
            )}
          </li>
        ))}
      </ul>
      {collection.isPending ? <p className="topic-section__state">최신 기사를 불러오고 있습니다.</p> : null}
      {collection.isError ? <p className="topic-section__state">최신 기사 목록을 불러오지 못했습니다.</p> : null}
      {!collection.isPending && rows.length === 0 ? <p className="topic-section__state">현재 검증 중인 기사와 이슈가 없습니다.</p> : null}
      {rows.length > collapsedTopicLength ? (
        <Button className="topic-section__toggle" variant="ghost" aria-expanded={expanded} onClick={onToggle}>
          {expanded ? <><ChevronUp size={15} /> 접기</> : <><ChevronDown size={15} /> {rows.length - collapsedTopicLength}개 더 보기</>}
        </Button>
      ) : null}
    </section>
  );
}

export function IssuesBrowser({ fallback }: { fallback: Issue[] }) {
  const query = useIssuesQuery(250);
  const [filterReferenceTime] = useState(Date.now);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [topics, setTopics] = useState<string[]>([]);
  const [period, setPeriod] = useState<Period>("all");
  const [expandedTopics, setExpandedTopics] = useState<string[]>([]);

  const issues = useMemo(() => {
    const fallbackById = new Map((isMockMode() ? fallback : []).map((issue) => [issue.id, issue]));
    const source = query.data?.items ?? (isMockMode() ? fallback : []);
    return source.map((issue) => ({
      ...issue,
      topic: issue.topic === "일반" ? fallbackById.get(issue.id)?.topic ?? issue.topic : issue.topic,
    }));
  }, [fallback, query.data?.items]);

  const availableTopics = useMemo(() => [...new Set(issues.map((issue) => issue.topic))].sort(topicOrder), [issues]);
  const visibleIssues = useMemo(() => {
    const cutoff = period === "all" ? null : filterReferenceTime - periodInMilliseconds[period];
    return issues.filter((issue) => {
      const matchesTopic = topics.length === 0 || topics.includes(issue.topic);
      const updatedAt = new Date(issue.updatedAt).getTime();
      const matchesPeriod = cutoff === null || (Number.isFinite(updatedAt) && updatedAt >= cutoff);
      return matchesTopic && matchesPeriod;
    });
  }, [filterReferenceTime, issues, period, topics]);

  const activeFilterCount = topics.length + (period === "all" ? 0 : 1);
  const visibleEventCount = visibleIssues.filter((issue) => issue.kind === "EVENT").length;
  const featuredIssues = useMemo(
    () => visibleIssues.filter(isSubstantiveEventIssue).sort(compareIssueImportance).slice(0, 10),
    [visibleIssues],
  );
  const topicGroups = useMemo(() => {
    const grouped = new Map<string, Issue[]>();
    for (const issue of visibleIssues) {
      const group = grouped.get(issue.topic) ?? [];
      group.push(issue);
      grouped.set(issue.topic, group);
    }
    return [...grouped.entries()]
      .sort(([left], [right]) => topicOrder(left, right))
      .map(([topic, groupedIssues], index) => ({
        id: `issue-topic-${index}`,
        topic,
        issues: groupedIssues.filter((issue) => issue.kind === "EVENT").sort(compareIssueImportance),
        collectionIssueIds: groupedIssues.filter((issue) => issue.kind === "TOPIC").map((issue) => issue.id),
      }));
  }, [visibleIssues]);
  const resetFilters = () => {
    setTopics([]);
    setPeriod("all");
  };
  const toggleTopic = (topic: string) => {
    setExpandedTopics((current) => current.includes(topic)
      ? current.filter((value) => value !== topic)
      : [...current, topic]);
  };

  if (query.isPending && !isMockMode()) return <StatePanel state="loading" />;
  if (query.isError && !isMockMode()) return <StatePanel state="error" onRetry={() => void query.refetch()} />;

  return (
    <>
      <PageHeader
        eyebrow="이슈 찾기"
        title="오늘의 이슈"
        description="바로 비교할 수 있는 이슈를 먼저 확인하고, 필요한 주제의 전체 이슈와 기사를 이어서 찾아보세요."
        actions={<Button variant="secondary" aria-expanded={drawerOpen} onClick={() => setDrawerOpen(true)}><Filter size={16} /> 주제와 기간{activeFilterCount > 0 ? ` ${activeFilterCount}` : ""}</Button>}
      />

      <div className="issue-filter-status" aria-live="polite">
        <span><strong>{visibleEventCount}</strong>개 이슈</span>
        {topicGroups.length > 0 ? <span><strong>{topicGroups.length}</strong>개 대주제</span> : null}
        <span>{topics.length ? topics.join(", ") : "모든 주제"}</span>
        <span>{periodOptions.find((option) => option.value === period)?.label}</span>
        {activeFilterCount > 0 && <Button variant="ghost" onClick={resetFilters}><RotateCcw size={14} /> 필터 초기화</Button>}
      </div>

      {visibleIssues.length > 0 ? (
        <div className="issue-groups">
          <section className="issue-group issue-ranking" aria-labelledby="featured-issues-title">
              <header className="issue-group__head">
                <div>
                  <p className="eyebrow">비교 준비 완료</p>
                  <h2 id="featured-issues-title">지금 비교할 수 있는 주요 이슈</h2>
                </div>
                <span>{featuredIssues.length}개 준비</span>
              </header>
              <p className="issue-group__description">기사 3개 이상, 출처 3곳 이상, 최신 AI 분석 기준을 모두 충족한 실제 사건을 최대 10개까지 표시합니다.</p>
              {featuredIssues.length > 0 ? <ul className="issue-rank-list">
                {featuredIssues.map((issue) => (
                  <li key={issue.id}>
                    <Link className="issue-rank-row" href={`/issues/${issue.id}`}>
                      <span className="issue-rank-row__number">비교</span>
                      <span className="issue-rank-row__copy">
                        <small>{issue.topic}</small>
                        <strong>{issue.title}</strong>
                        {issue.summary ? <span>{issue.summary}</span> : null}
                      </span>
                      <span className="issue-rank-row__meta"><IssueCounts issue={issue} /></span>
                    </Link>
                  </li>
                ))}
              </ul> : <p className="issue-ranking__empty">현재 기준을 충족한 주요 이슈를 검증하고 있습니다.</p>}
            </section>
          {topicGroups.length > 0 ? (
            <section className="issue-group topic-directory" aria-labelledby="topic-issues-title">
              <header className="issue-group__head">
                <div>
                  <p className="eyebrow">전체 자료</p>
                  <h2 id="topic-issues-title">주제별 전체 찾아보기</h2>
                </div>
                <span>{topicGroups.length}개 주제</span>
              </header>
              <p className="issue-group__description">위의 비교 가능 이슈를 포함한 전체 사건을 주제 맥락에서 다시 찾고, 주제별 최신 기사도 함께 확인할 수 있습니다.</p>
              <nav className="topic-directory__nav" aria-label="대주제 바로가기">
                {topicGroups.map((group) => <a key={group.topic} href={`#${group.id}`}><strong>{group.topic}</strong><span>{group.issues.length ? `${group.issues.length} 이슈` : "최신 기사"}</span></a>)}
              </nav>
              <div className="topic-directory__groups">
                {topicGroups.map((group) => {
                  const expanded = expandedTopics.includes(group.topic);
                  return (
                    <TopicSection
                      key={group.topic}
                      id={group.id}
                      topic={group.topic}
                      issues={group.issues}
                      collectionIssueIds={group.collectionIssueIds}
                      expanded={expanded}
                      onToggle={() => toggleTopic(group.topic)}
                    />
                  );
                })}
              </div>
            </section>
          ) : null}
        </div>
      ) : (
        <section className="issue-filter-empty">
          <p className="eyebrow">No matched issue</p>
          <h2>조건에 맞는 이슈가 없습니다.</h2>
          <p>주제나 기간을 넓혀 다시 확인해 주세요.</p>
          <Button variant="secondary" onClick={resetFilters}><RotateCcw size={14} /> 모든 이슈 보기</Button>
        </section>
      )}
      {query.hasNextPage && <div className="form-actions"><Button variant="secondary" onClick={() => void query.fetchNextPage()} disabled={query.isFetchingNextPage}>{query.isFetchingNextPage ? "불러오는 중…" : "더 보기"}</Button></div>}

      <Drawer open={drawerOpen} title="주제와 기간 필터" onClose={() => setDrawerOpen(false)}>
        <fieldset className="issue-filter-group">
          <legend>주제</legend>
          <p>하나 이상 선택하면 해당 주제만 표시합니다.</p>
          <div className="issue-filter-topics">
            {availableTopics.map((topic) => (
              <CheckboxField
                key={topic}
                checked={topics.includes(topic)}
                onCheckedChange={(checked) => setTopics((current) => checked ? [...current, topic] : current.filter((value) => value !== topic))}
                label={topic}
              />
            ))}
          </div>
        </fieldset>
        <div className="issue-filter-group">
          <SelectField id="issue-period" label="기간" value={period} options={periodOptions} onValueChange={(value) => setPeriod(value as Period)} />
        </div>
        <div className="issue-filter-actions">
          <Button variant="ghost" onClick={resetFilters}><RotateCcw size={14} /> 초기화</Button>
          <Button onClick={() => setDrawerOpen(false)}>
            {visibleEventCount}개 이슈{topicGroups.length > 0 ? `, ${topicGroups.length}개 대주제` : ""} 보기
          </Button>
        </div>
      </Drawer>
    </>
  );
}
