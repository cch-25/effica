"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { apiRequest } from "@/lib/api/client";
import { Button } from "@/components/ui/button";

export type Readiness = { status: string; reason: string; checked_at: string; next_eligible_at: string | null; refresh_interval_seconds?: number };

const reasons: Record<string, { title: string; description: string }> = {
  ANALYSIS_AVAILABLE: { title: "분석 결과가 준비되었습니다.", description: "공개 기준을 충족한 분석을 확인할 수 있습니다." },
  ANALYSIS_RUNNING: { title: "AI가 이 기사를 분석하고 있습니다.", description: "분석과 공개 기준 확인이 끝나면 결과가 표시됩니다." },
  QUEUED_FOR_ANALYSIS: { title: "분석 순서를 기다리고 있습니다.", description: "기사 확보 상태와 처리 순서에 따라 걸리는 시간이 달라집니다." },
  DAILY_SELECTION_DEFERRED: { title: "다음 분석 기회를 기다리고 있습니다.", description: "하루 분석 대상과 처리량 제한에 따라 대기 중입니다. 재개 가능 시각은 완료 예정 시각이 아닙니다." },
  CONTENT_NOT_ELIGIBLE: { title: "아직 분석 조건을 충족하지 못했습니다.", description: "본문 분량이나 기사 상태 등 분석에 필요한 조건이 부족합니다. 원문과 다른 보도를 함께 확인해 주세요." },
  SOURCE_CONTENT_UNAVAILABLE: { title: "분석할 본문을 확보하지 못했습니다.", description: "원문 제공 상태를 확인해야 하므로 분석 완료 시각을 안내하기 어렵습니다." },
  NOT_SELECTED_FOR_DAILY_ANALYSIS: { title: "분석 예약 상태를 확인하고 있습니다.", description: "발행한 이슈의 모든 기사를 분석 대상으로 처리합니다. 아직 분석 작업이 확인되지 않았으며, 원문은 바로 읽을 수 있습니다." },
  ANALYSIS_RESULT_UNAVAILABLE: { title: "공개할 수 있는 분석 결과가 없습니다.", description: "분석 실패나 공개 기준 미충족 등으로 결과를 제공하지 못하고 있습니다. 확인되지 않은 점수는 표시하지 않습니다." },
  CURRENT_EVENT_AVAILABLE: { title: "비교할 수 있는 이슈가 준비되어 있습니다.", description: "같은 사건에 대한 보도가 충분히 모이고 분석 조건을 충족하면 순차적으로 공개합니다." },
  EVENT_ANALYSIS_IN_PROGRESS: { title: "확보한 보도의 분석을 준비하고 있습니다.", description: "언론사 3곳 이상의 원문을 확보한 이슈는 이미 읽을 수 있습니다. 기사 분석과 보도 비교는 준비가 끝나면 공개합니다." },
  EVENT_CANDIDATE_NEEDS_MORE_SOURCES: { title: "같은 사건을 다룬 다른 출처의 보도가 더 필요합니다.", description: "최근 7일 안의 유효한 원문을 서로 다른 언론사 3곳 이상에서 확보해야 이슈를 발행합니다." },
  NO_ELIGIBLE_EVENT: { title: "아직 주요 이슈 공개 조건을 충족한 사건이 없습니다.", description: "정치와 정책 쟁점을 다룬 최근 원문을 언론사 3곳 이상에서 확보하면 발행합니다. 기사 분석은 별도로 진행합니다." },
};

export function AnalysisReadinessNotice({ articleId }: { articleId?: string }) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["analysis-readiness", articleId ?? "overall"],
    queryFn: () => apiRequest<Readiness>(articleId ? `/articles/${encodeURIComponent(articleId)}/analysis-status` : "/analysis-status"),
    staleTime: 20_000,
    refetchInterval: 30_000,
    retry: false,
  });
  const available = query.data?.status === "READY";
  const publishedIssue = !articleId && query.data?.reason === "EVENT_ANALYSIS_IN_PROGRESS";
  useEffect(() => {
    if (!available && !publishedIssue) return;
    void queryClient.invalidateQueries({ queryKey: articleId ? ["article", articleId] : ["issues"] });
    if (!articleId) void queryClient.invalidateQueries({ queryKey: ["feed"] });
  }, [articleId, available, publishedIssue, queryClient]);
  if (query.isPending) return <p role="status">분석 준비 상태를 확인하고 있습니다.</p>;
  if (query.isError || !query.data) return <div className="analysis-readiness" role="status"><p>현재 분석 준비 상태를 확인하지 못했습니다. 완료 시각은 확인 후 안내할 수 있습니다.</p><Button variant="ghost" onClick={() => void query.refetch()}>상태 다시 확인</Button></div>;
  const content = reasons[query.data.reason] ?? { title: "분석 상태를 확인 중입니다.", description: "현재 완료 시각을 안내하기 어렵습니다." };
  const next = query.data.next_eligible_at ? new Date(query.data.next_eligible_at) : null;
  return <div className="analysis-readiness" role="status" aria-live="polite">
    <strong>{content.title}</strong><p>{content.description}</p>
    {!articleId && <p>하루 한 번 최근 3~7일의 정치와 정책 쟁점을 먼저 선정하고, 각 이슈를 다룬 서로 다른 언론사의 보도를 수집합니다. 출처 3곳 이상을 확보한 이슈를 소개하며, 보도 비교는 분석 준비가 끝나면 공개합니다.</p>}
    {next && Number.isFinite(next.getTime()) && <p>다음 처리 가능 시각: <time dateTime={next.toISOString()}>{new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Seoul" }).format(next)}</time> (한국 시간). 이 시각에 완료되는 것은 아닙니다.</p>}
    <small>상태는 30초마다 다시 확인합니다. 완료 시각은 원문 확보와 분석 상황에 따라 달라집니다.</small>
  </div>;
}
