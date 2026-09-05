"use client";

import { ArrowUpRight, BookOpenCheck, Share2, ShieldCheck } from "lucide-react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button, ButtonLink } from "@/components/ui/button";
import { StatePanel } from "@/components/ui/state-panel";
import { apiRequest } from "@/lib/api/client";
import { formatBiasScore, formatTierLabel } from "@/lib/api/formatters";

type Coordinate = { x: number; y: number; z: number; sensationalism: number | null; confidence: number };
type ProgressView = {
  credit_total: number;
  level: number;
  tier: string;
  policy_version: string;
  read_article_count: number;
  compared_issue_count: number;
  source_diversity_count: number;
  self_reported_profile: Coordinate | null;
  behavioral_profile: Coordinate | null;
};
type CreditPage = {
  items: Array<{ event_type: string; created_at: string; delta: number; policy_version: string }>;
  next_cursor: string | null;
};

function eventLabel(eventType: string): string {
  const normalized = eventType.toUpperCase();
  if (normalized === "QUALIFIED_READ" || normalized === "READ_RETURN") return "원문 읽기 복귀 확인";
  if (normalized === "REVERSAL") return "크레딧 지급 취소";
  if (normalized === "COMPARE") return "이슈 비교";
  return "기타 활동";
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
    <div className="progress-page">
      <PageHeader eyebrow="내 활동 기록" title="읽고 비교한 기록" description="활동 크레딧은 확인된 읽기와 비교 활동의 기록이며 정치적 정답이나 우열을 뜻하지 않습니다." actions={<><ButtonLink variant="secondary" href="/share/new"><Share2 size={15} aria-hidden="true" /> 공유 카드 만들기</ButtonLink><ButtonLink variant="secondary" href="/settings/privacy"><ShieldCheck size={15} aria-hidden="true" /> 개인정보 관리</ButtonLink><ButtonLink variant="secondary" href="/efficacy">정치 이슈 이해 자신감 변화 <ArrowUpRight size={15} aria-hidden="true" /></ButtonLink></>} />
      <div className="grid grid--4 progress-metrics">
        <section className="card metric"><small>읽은 기사</small><strong>{snapshot.read_article_count}</strong><span className="metric__delta">복귀 자격 확인 기준</span></section>
        <section className="card metric"><small>비교하고 평가한 이슈</small><strong>{snapshot.compared_issue_count}</strong><span className="metric__delta">실제 활동 연결 기준</span></section>
        <section className="card metric"><small>출처 다양성</small><strong>{snapshot.source_diversity_count}</strong><span className="metric__delta">서로 다른 출처 수</span></section>
        <section className="card metric"><small>누적 크레딧</small><strong>{snapshot.credit_total}</strong><span className="metric__delta">레벨 {snapshot.level}, {formatTierLabel(snapshot.tier)}</span></section>
      </div>
      <div className="section-head"><h2>관점 기록</h2><Badge>자기보고와 행동을 분리</Badge></div>
      <div className="grid grid--2 progress-profiles">
        <section className="card card--padded"><p className="eyebrow">자기보고 관점</p>{snapshot.self_reported_profile ? <><strong>편향성 {formatBiasScore(snapshot.self_reported_profile.x)}</strong><p>과장성은 설문에서 측정하지 않으며, 응답 신뢰도는 {Math.round(snapshot.self_reported_profile.confidence * 100)}%입니다.</p></> : <><h3>기록을 더 쌓아 주세요.</h3><p>자기보고 설문을 완료하면 이곳에 별도로 표시합니다.</p></>}</section>
        <section className="card card--padded"><p className="eyebrow">행동 기반 관점</p>{snapshot.behavioral_profile ? <><strong>편향성 {formatBiasScore(snapshot.behavioral_profile.x)}, 과장성 {snapshot.behavioral_profile.sensationalism ?? "미측정"}</strong><p>읽기와 평가 활동 신뢰도 {Math.round(snapshot.behavioral_profile.confidence * 100)}%</p></> : <><h3>기록을 더 쌓아 주세요.</h3><p>원문 읽기와 독자 평가가 쌓이면 계산된 관점 결과를 표시합니다.</p></>}</section>
      </div>
      <div className="section-head"><h2>크레딧 변경 내역</h2><div><span style={{ marginRight: ".6rem" }}>불러온 기록</span><Badge>{rows.length}개</Badge></div></div>
      {rows.length === 0 ? <StatePanel state="empty" /> : (
        <>
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>활동</th><th>기록 시각</th><th>크레딧 변동</th></tr></thead>
              <tbody>
                {rows.map((row, index) => (
                  <tr key={`${row.event_type}-${row.created_at}-${index}`}>
                    <td data-label="활동"><span className="progress-event"><BookOpenCheck size={15} aria-hidden="true" />{eventLabel(row.event_type)}</span></td>
                    <td data-label="기록 시각">{row.created_at}</td>
                    <td data-label="크레딧 변동">{row.delta > 0 ? `+${row.delta}` : row.delta}</td>
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
    </div>
  );
}
