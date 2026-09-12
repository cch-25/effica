"use client";

import { ArrowLeft } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/layout/page-header";
import { StatePanel } from "@/components/ui/state-panel";
import { ButtonLink } from "@/components/ui/button";
import { EfficacyForm } from "@/features/efficacy/efficacy-form";
import { apiRequest } from "@/lib/api/client";
import { formatPublishedDate } from "@/lib/api/formatters";

type EfficacyHistory = {
  baseline: number | null;
  responses: Array<{ normalized_score: number; submitted_at?: string }>;
  due_survey: boolean;
};

export default function EfficacyPage() {
  const query = useQuery({ queryKey: ["me", "efficacy"], queryFn: () => apiRequest<EfficacyHistory>("/me/efficacy") });
  if (query.isPending) return <StatePanel state="loading" />;
  if (query.isError) return <StatePanel state="error" onRetry={() => void query.refetch()} />;
  const history = query.data;
  const latest = history.responses.at(-1);
  const delta = latest && history.baseline != null ? latest.normalized_score - history.baseline : null;
  return (
    <>
      <PageHeader eyebrow="내 활동" title="정치 이슈 이해 자신감 변화" description="반복 설문으로 기록한 개인 변화입니다. 이 변화만으로 서비스 사용 효과를 판단하지 않습니다." actions={<ButtonLink variant="secondary" href="/progress"><ArrowLeft size={15} aria-hidden="true" /> 내 활동으로 돌아가기</ButtonLink>} />
      <div className="grid grid--3">
        <section className="card metric"><small>첫 측정</small><strong>{history.baseline ?? "없음"}</strong><span>{history.responses[0]?.submitted_at ? formatPublishedDate(history.responses[0].submitted_at) : "아직 없음"}</span></section>
        <section className="card metric"><small>최근 측정</small><strong>{latest?.normalized_score ?? "없음"}</strong><span>{latest?.submitted_at ? formatPublishedDate(latest.submitted_at) : "아직 없음"}</span></section>
        <section className="card metric"><small>첫 측정 대비</small><strong>{delta == null ? "없음" : `${delta > 0 ? "+" : ""}${delta}`}</strong><span>100점 기준 변화</span></section>
      </div>
      <div style={{ marginTop: "1rem" }}>{history.due_survey ? <EfficacyForm /> : <p className="notice">이번 측정을 완료했습니다. 다음 측정은 30일 후에 가능합니다.</p>}</div>
    </>
  );
}
