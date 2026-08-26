"use client";

import { ArrowUpRight, BookOpenCheck, Share2, ShieldCheck } from "lucide-react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button, ButtonLink } from "@/components/ui/button";
import { StatePanel } from "@/components/ui/state-panel";
import { apiRequest } from "@/lib/api/client";

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
      <PageHeader eyebrow={`My activity / ${snapshot.policy_version}`} title="읽고 비교한 기록" description="활동 크레딧은 검증된 비교·복귀 활동의 기록이며 정치적 정답이나 우열을 뜻하지 않습니다." actions={<><ButtonLink variant="secondary" href="/share/new"><Share2 size={15} /> 공유 카드</ButtonLink><ButtonLink variant="secondary" href="/settings/privacy"><ShieldCheck size={15} /> 개인정보</ButtonLink><ButtonLink variant="secondary" href="/efficacy">효능감 추이 <ArrowUpRight size={15} /></ButtonLink></>} />
      <div className="grid grid--4">
        <section className="card metric"><small>읽은 기사</small><strong>{snapshot.read_article_count}</strong><span className="metric__delta">복귀 자격 확인 기준</span></section>
        <section className="card metric"><small>비교·평가한 사건</small><strong>{snapshot.compared_issue_count}</strong><span className="metric__delta">실제 활동 연결 기준</span></section>
        <section className="card metric"><small>출처 다양성</small><strong>{snapshot.source_diversity_count}</strong><span className="metric__delta">서로 다른 출처 수</span></section>
        <section className="card metric"><small>누적 크레딧</small><strong>{snapshot.credit_total}</strong><span className="metric__delta">Lv. {snapshot.level} · {snapshot.tier}</span></section>
      </div>
      <div className="section-head"><h2>관점 기록</h2><Badge>자기보고와 행동을 분리</Badge></div>
      <div className="grid grid--2">
        <section className="card card--padded"><p className="eyebrow">자기보고 관점</p>{snapshot.self_reported_profile ? <><strong>x {snapshot.self_reported_profile.x} · y {snapshot.self_reported_profile.y} · z {snapshot.self_reported_profile.z}</strong><p>설문 응답 confidence {Math.round(snapshot.self_reported_profile.confidence * 100)}%</p></> : <><h3>기록을 더 쌓아 주세요.</h3><p>자기보고 설문을 완료하면 이곳에 별도로 표시합니다.</p></>}</section>
        <section className="card card--padded"><p className="eyebrow">행동 기반 관점</p>{snapshot.behavioral_profile ? <><strong>편향성 {snapshot.behavioral_profile.x} · 과장성 {snapshot.behavioral_profile.sensationalism ?? "미측정"}</strong><p>읽기·평가 활동 confidence {Math.round(snapshot.behavioral_profile.confidence * 100)}%</p></> : <><h3>기록을 더 쌓아 주세요.</h3><p>원문 읽기와 독자 평가가 쌓이면 임의 좌표 대신 계산된 결과를 표시합니다.</p></>}</section>
      </div>
      <div className="section-head"><h2>크레딧 이력</h2><div><span style={{ marginRight: ".6rem" }}>불러온 기록</span><Badge>{rows.length}개 · immutable ledger</Badge></div></div>
      {rows.length === 0 ? <StatePanel state="empty" /> : (
        <>
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>활동</th><th>기록 시각</th><th>변동</th><th>정책</th></tr></thead>
              <tbody>
                {rows.map((row, index) => (
                  <tr key={`${row.event_type}-${row.created_at}-${index}`}>
                    <td data-label="활동"><BookOpenCheck size={15} /> {eventLabel(row.event_type)}</td>
                    <td data-label="기록 시각">{row.created_at}</td>
                    <td data-label="변동">{row.delta > 0 ? `+${row.delta}` : row.delta}</td>
                    <td data-label="정책">{row.policy_version}</td>
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
