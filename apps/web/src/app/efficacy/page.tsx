"use client";

import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/layout/page-header";
import { StatePanel } from "@/components/ui/state-panel";
import { EfficacyForm } from "@/features/efficacy/efficacy-form";
import { apiRequest } from "@/lib/api/client";

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
      <PageHeader eyebrow="Political efficacy" title="이해한다는 감각의 변화" description="반복 설문의 개인 추이입니다. 변화는 상관관계이며 서비스 사용의 인과 효과로 표현하지 않습니다." />
      <div className="grid grid--3">
        <section className="card metric"><small>기준선</small><strong>{history.baseline ?? "—"}</strong><span>{history.responses[0]?.submitted_at ?? "아직 없음"}</span></section>
        <section className="card metric"><small>최근 측정</small><strong>{latest?.normalized_score ?? "—"}</strong><span>{latest?.submitted_at ?? "아직 없음"}</span></section>
        <section className="card metric"><small>개인 변화</small><strong>{delta == null ? "—" : `${delta > 0 ? "+" : ""}${delta}`}</strong><span>normalized score</span></section>
      </div>
      <div style={{ marginTop: "1rem" }}><EfficacyForm /></div>
    </>
  );
}
