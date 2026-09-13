"use client";

import { AnalysisReadinessNotice } from "@/features/articles/analysis-readiness-notice";

import { ArrowRight, ChevronDown, ChevronUp, Filter, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { ContentTypeIndicator, ContentTypeLine } from "@/components/ui/content-type-indicator";
import { Drawer } from "@/components/ui/drawer";
import { CheckboxField, SelectField } from "@/components/ui/form-controls";
import { useIssueArticleCollectionsQuery, useIssuesQuery } from "@/lib/api/queries";
import type { Article, Issue } from "@/lib/api/types";
import { isMockMode } from "@/lib/api/mode";
import { StatePanel } from "@/components/ui/state-panel";
import { compareIssueImportance, isFeaturedIssue, isSupportedIssue, issueTopics } from "./issue-selection";

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

const collapsedTopicLength = 6;

function isSubstantiveEventIssue(issue: Issue): boolean {
  return isFeaturedIssue(issue) && issue.analysisStatus === "READY";
}

function topicOrder(left: string, right: string): number {
  return issueTopics.findIndex((topic) => topic === left) - issueTopics.findIndex((topic) => topic === right);
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
  issueOrdinals,
  expanded,
  onToggle,
}: {
  id: string;
  topic: string;
  issues: Issue[];
  collectionIssueIds: string[];
  issueOrdinals: ReadonlyMap<string, number>;
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
                  <small><ContentTypeLine kind="issue" issueOrdinal={issueOrdinals.get(row.issue.id)}>{isSubstantiveEventIssue(row.issue) ? "비교 가능" : "분석 준비 중"}</ContentTypeLine></small>
                  <strong>{row.issue.title}</strong>
                </span>
                <IssueCounts issue={row.issue} />
              </Link>
            ) : (
              <Link className="topic-issue-row topic-article-row" href={`/articles/${row.article.id}`}>
                <span className="topic-issue-row__copy">
                  <small><ContentTypeIndicator kind="article" /></small>
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
    })).filter(isSupportedIssue);
  }, [fallback, query.data?.items]);

  const availableTopics = issueTopics;
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
    () => visibleIssues.filter(isSubstantiveEventIssue).sort(compareIssueImportance),
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
  const issueOrdinals = useMemo(() => {
    const orderedIds = [...featuredIssues, ...topicGroups.flatMap((group) => group.issues)].map((issue) => issue.id);
    const uniqueIds = [...new Set(orderedIds)];
    return new Map(uniqueIds.map((id, index) => [id, index]));
  }, [featuredIssues, topicGroups]);
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
    <div className="issues-page">
      <PageHeader
        eyebrow="이슈 찾기"
        title="오늘의 이슈"
        description="같은 이슈, 다른 보도. 여러 언론사의 근거와 관점을 비교하세요."
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
              <p className="issue-group__description">기사 3개 이상, 출처 3곳 이상을 확보하고 최신 분석을 마친 이슈입니다.</p>
              {featuredIssues.length > 0 ? <ul className="issue-rank-list">
                {featuredIssues.map((issue) => (
                  <li key={issue.id}>
                    <Link className="issue-rank-row" href={`/issues/${issue.id}`}>
                      <span className="issue-rank-row__copy">
                        <small><ContentTypeLine kind="issue" issueOrdinal={issueOrdinals.get(issue.id)}>{issue.topic}</ContentTypeLine></small>
                        <strong>{issue.title}</strong>
                        {issue.summary ? <span>{issue.summary}</span> : null}
                      </span>
                      <span className="issue-rank-row__meta"><IssueCounts issue={issue} /><span className="issue-rank-row__action">보도 비교하기 <ArrowRight size={16} aria-hidden="true" /></span></span>
                    </Link>
                  </li>
                ))}
              </ul> : activeFilterCount > 0 ? <p className="issue-ranking__empty">선택한 주제와 기간에 비교 준비를 마친 주요 이슈가 없습니다.</p> : <AnalysisReadinessNotice />}
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
              <p className="issue-group__description">주제별 이슈와 관련 기사입니다. 분석 준비 중인 자료도 볼 수 있습니다.</p>
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
                      issueOrdinals={issueOrdinals}
                      expanded={expanded}
                      onToggle={() => toggleTopic(group.topic)}
                    />
                  );
                })}
              </div>
            </section>
          ) : null}
        </div>
      ) : activeFilterCount === 0 ? <AnalysisReadinessNotice /> : (
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
    </div>
  );
}
