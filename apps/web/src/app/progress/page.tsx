"use client";

import { ArrowUpRight, BookOpenCheck } from "lucide-react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button, ButtonLink } from "@/components/ui/button";
import { StatePanel } from "@/components/ui/state-panel";
import { apiRequest } from "@/lib/api/client";

type ProgressView = { credit_total: number; level: number; tier: string; policy_version: string };
type CreditPage = {
  items: Array<{ event_type: string; created_at: string; delta: number; policy_version: string }>;
  next_cursor: string | null;
};

function eventLabel(eventType: string): string {
  if (eventType.toUpperCase().includes("READ")) return "원문 읽기 복귀 확인";
  if (eventType.toUpperCase().includes("REVERSAL")) return "크레딧 reversal";
  return eventType;
}

export default function ProgressPage() {
  const progress = useQuery({ queryKey: ["me", "progress"], queryFn: () => apiRequest<ProgressView>("/me/progress") });
  const credits = useInfiniteQuery({
    queryKey: ["me", "credits"],
    queryFn: ({ pageParam }) => apiRequest<CreditPage>(`/me/credits${pageParam ? `?cursor=${encodeURIComponent(pageParam)}` : ""}`),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
  });
  if (progress.isPending || credits.isPending) return <StatePanel state="loading" />;
  if (progress.isError || credits.isError) return <StatePanel state="error" onRetry={() => { void progress.refetch(); void credits.refetch(); }} />;
  const snapshot = progress.data;
  const rows = credits.data?.pages.flatMap((page) => page.items) ?? [];
  return (
    <>
      <PageHeader eyebrow={`My activity / ${snapshot.policy_version}`} title="읽고 비교한 기록" description="활동 크레딧은 검증된 비교·복귀 활동의 기록이며 정치적 정답이나 우열을 뜻하지 않습니다." actions={<ButtonLink variant="secondary" href="/efficacy">효능감 추이 <ArrowUpRight size={15} /></ButtonLink>} />
      <div className="grid grid--4">
        <section className="card metric"><small>누적 크레딧</small><strong>{snapshot.credit_total}</strong><span className="metric__delta">ledger snapshot</span></section>
        <section className="card metric"><small>현재 레벨</small><strong>Lv. {snapshot.level}</strong><span className="metric__delta">100 크레딧 단위</span></section>
        <section className="card metric"><small>활동 티어</small><strong>{snapshot.tier}</strong><span className="metric__delta">credit snapshot</span></section>
        <section className="card metric"><small>불러온 기록</small><strong>{rows.length}</strong><span className="metric__delta">immutable ledger</span></section>
      </div>
      <div className="section-head"><h2>크레딧 이력</h2><Badge>immutable ledger</Badge></div>
      {rows.length === 0 ? <StatePanel state="empty" /> : (
        <>
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>활동</th><th>기록 시각</th><th>변동</th><th>정책</th></tr></thead>
              <tbody>
                {rows.map((row, index) => (
                  <tr key={`${row.event_type}-${row.created_at}-${index}`}>
                    <td><BookOpenCheck size={15} /> {eventLabel(row.event_type)}</td>
                    <td>{row.created_at}</td>
                    <td>{row.delta > 0 ? `+${row.delta}` : row.delta}</td>
                    <td>{row.policy_version}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {credits.hasNextPage && (
            <div className="form-actions">
              <Button variant="secondary" onClick={() => void credits.fetchNextPage()} disabled={credits.isFetchingNextPage}>
                {credits.isFetchingNextPage ? "불러오는 중…" : "이전 기록 더 보기"}
              </Button>
            </div>
          )}
        </>
      )}
    </>
  );
}
