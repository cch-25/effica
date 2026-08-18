"use client";

import { Filter, RotateCcw } from "lucide-react";
import { useMemo, useState } from "react";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Drawer } from "@/components/ui/drawer";
import { CheckboxField, SelectField } from "@/components/ui/form-controls";
import { useIssuesQuery } from "@/lib/api/queries";
import type { Issue } from "@/lib/api/types";
import { IssueCard } from "./issue-card";
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

export function IssuesBrowser({ fallback }: { fallback: Issue[] }) {
  const query = useIssuesQuery();
  const [filterReferenceTime] = useState(Date.now);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [topics, setTopics] = useState<string[]>([]);
  const [period, setPeriod] = useState<Period>("all");

  const issues = useMemo(() => {
    const fallbackById = new Map((isMockMode() ? fallback : []).map((issue) => [issue.id, issue]));
    const source = query.data?.items ?? (isMockMode() ? fallback : []);
    return source.map((issue) => ({
      ...issue,
      topic: issue.topic === "일반" ? fallbackById.get(issue.id)?.topic ?? issue.topic : issue.topic,
    }));
  }, [fallback, query.data?.items]);

  const availableTopics = useMemo(() => [...new Set(issues.map((issue) => issue.topic))].sort((a, b) => a.localeCompare(b, "ko")), [issues]);
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
  const resetFilters = () => {
    setTopics([]);
    setPeriod("all");
  };

  if (query.isPending && !isMockMode()) return <StatePanel state="loading" />;
  if (query.isError && !isMockMode()) return <StatePanel state="error" onRetry={() => void query.refetch()} />;

  return (
    <>
      <PageHeader
        eyebrow="Issues / 02"
        title="오늘의 이슈를 관점별로"
        description="기사가 충분히 모인 이슈만 균형 묶음으로 표시합니다. 조건을 충족하지 못한 이슈는 준비 중 상태를 숨기지 않습니다."
        actions={<Button variant="secondary" aria-expanded={drawerOpen} onClick={() => setDrawerOpen(true)}><Filter size={16} /> 주제·기간{activeFilterCount > 0 ? ` ${activeFilterCount}` : ""}</Button>}
      />

      <div className="issue-filter-status" aria-live="polite">
        <span><strong>{visibleIssues.length}</strong>개 이슈</span>
        <span>{topics.length ? topics.join(" · ") : "모든 주제"}</span>
        <span>{periodOptions.find((option) => option.value === period)?.label}</span>
        {activeFilterCount > 0 && <Button variant="ghost" onClick={resetFilters}><RotateCcw size={14} /> 필터 초기화</Button>}
      </div>

      {visibleIssues.length > 0 ? (
        <div className="grid grid--2">{visibleIssues.map((issue) => <IssueCard key={issue.id} issue={issue} />)}</div>
      ) : (
        <section className="issue-filter-empty">
          <p className="eyebrow">No matched issue</p>
          <h2>조건에 맞는 이슈가 없습니다.</h2>
          <p>주제나 기간을 넓혀 다시 확인해 주세요.</p>
          <Button variant="secondary" onClick={resetFilters}><RotateCcw size={14} /> 모든 이슈 보기</Button>
        </section>
      )}

      <Drawer open={drawerOpen} title="주제·기간 필터" onClose={() => setDrawerOpen(false)}>
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
          <Button onClick={() => setDrawerOpen(false)}>{visibleIssues.length}개 이슈 보기</Button>
        </div>
      </Drawer>
    </>
  );
}
