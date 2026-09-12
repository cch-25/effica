"use client";

import Link from "next/link";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/layout/page-header";
import { Button, ButtonLink } from "@/components/ui/button";
import { StatePanel } from "@/components/ui/state-panel";
import { apiRequest } from "@/lib/api/client";
import { formatBiasScore, formatPublishedDate } from "@/lib/api/formatters";
import { PerspectivePreview } from "@/features/share-cards/perspective-preview";
import { consumptionSnapshot } from "@/features/share-cards/consumption";

type ProgressView = Record<string, unknown> & { read_article_count: number; compared_issue_count: number; source_diversity_count: number };
type Activity = { id: string; read: boolean; last_activity_at: string; article: { id: string; title: string; source: string; issue_id: string | null } | null; my_vote: { x: number; sensationalism: number } | null; ai_score: { x: number; sensationalism: number | null } | null };
type ActivityPage = { items: Activity[]; next_cursor: string | null };

export default function ProgressPage() {
  const progress = useQuery({ queryKey: ["me", "progress"], queryFn: () => apiRequest<ProgressView>("/me/progress") });
  const activity = useInfiniteQuery({ queryKey: ["me", "activity"], queryFn: ({ pageParam }) => apiRequest<ActivityPage>(`/me/activity${pageParam ? `?cursor=${encodeURIComponent(pageParam)}` : ""}`), initialPageParam: null as string | null, getNextPageParam: (page) => page.next_cursor });
  if (progress.isPending) return <StatePanel state="loading" />;
  if (progress.isError) return <StatePanel state="error" onRetry={() => void progress.refetch()} />;
  const snapshot = progress.data;
  const rows = activity.data?.pages.flatMap((page) => page.items) ?? [];
  return <div className="progress-page">
    <PageHeader eyebrow="내 활동" title="읽고 비교한 기록" description="읽은 기사와 저장한 평가를 다시 확인하세요." actions={<><ButtonLink variant="secondary" href="/share/new">공유 카드 만들기</ButtonLink><ButtonLink variant="secondary" href="/efficacy">이슈 이해 자신감 기록</ButtonLink></>} />
    <p>읽은 기사 {snapshot.read_article_count}개 / 비교한 이슈 {snapshot.compared_issue_count}개 / 살펴본 출처 {snapshot.source_diversity_count}곳</p>
    <section aria-labelledby="activity-title"><h2 id="activity-title">최근 읽기와 평가</h2><p>기사 화면에서 읽기를 기록했거나 평가한 기사입니다. 같은 기사의 활동은 하나로 모았습니다.</p>
      {activity.isPending ? <p>기록을 불러오는 중입니다.</p> : activity.isError ? <StatePanel state="error" onRetry={() => void activity.refetch()} /> : rows.length ? <ul className="ux-activity-list">{rows.map((row) => <li key={row.id}><small>{formatPublishedDate(row.last_activity_at)} / {row.read ? "읽음" : "평가함"}</small><h3>{row.article ? <Link href={`/articles/${row.article.id}`}>{row.article.source}: {row.article.title}</Link> : "공개 기간이 지난 기사"}</h3><p>{row.my_vote ? `내 평가: 편향성 ${formatBiasScore(row.my_vote.x)}, 과장성 ${row.my_vote.sensationalism}` : "아직 평가하지 않았습니다."}{row.ai_score && ` / AI 분석: 편향성 ${formatBiasScore(row.ai_score.x)}, 과장성 ${row.ai_score.sensationalism ?? "미측정"}`}</p>{row.article?.issue_id && <Link href={`/issues/${row.article.issue_id}`}>이슈 비교 →</Link>}</li>)}</ul> : <p>아직 기록이 없습니다. <Link href="/">이슈를 골라 비교해 보세요.</Link></p>}
      {activity.hasNextPage && <Button variant="secondary" disabled={activity.isFetchingNextPage} onClick={() => void activity.fetchNextPage()}>이전 기록 더 보기</Button>}
    </section>
    <details><summary>뉴스 소비와 선택 설문 결과</summary><PerspectivePreview displayName="" snapshot={consumptionSnapshot(snapshot)} returnTo="/progress" compact /></details>
    <p><Link href="/onboarding/questionnaire?returnTo=%2Fprogress">내 위치를 지도에 표시하려면 정치성향 검사하기</Link></p>
  </div>;
}
