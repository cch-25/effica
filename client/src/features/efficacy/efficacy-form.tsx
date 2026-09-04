"use client";

import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Toast } from "@/components/ui/toast";
import { Slider } from "@/components/ui/slider";
import { apiRequest } from "@/lib/api/client";
import type { EfficacySubmission, EfficacyView, QuestionnaireVersionView } from "@/lib/api/contracts";

const EFFICACY_COPY: Record<string, string> = {
  baseline: "복잡한 정치와 정책 이슈의 핵심을 스스로 파악할 수 있나요?",
  current: "서로 다른 주장과 근거를 비교해 내 판단을 내릴 수 있나요?",
  confidence: "정치와 정책 이슈를 이해할 수 있다는 자신감이 어느 정도인가요?",
};

function keysFrom(version: QuestionnaireVersionView | null): string[] {
  const schemaQuestions = Array.isArray(version?.schema_json?.questions)
    ? (version.schema_json.questions as Array<{ id?: string }>)
    : [];
  const fromSchema = schemaQuestions.map((item) => item.id).filter((id): id is string => Boolean(id));
  return fromSchema.length ? fromSchema : version?.keys ?? ["confidence"];
}

function likertToScore(value: number): number {
  return Math.round(((value - 1) / 4) * 100);
}

export function EfficacyForm() {
  const queryClient = useQueryClient();
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const [version, setVersion] = useState<QuestionnaireVersionView | null>(null);
  const [saved, setSaved] = useState<EfficacyView | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const keys = useMemo(() => keysFrom(version), [version]);
  useEffect(() => {
    void apiRequest<QuestionnaireVersionView[]>("/questionnaires?kind=efficacy").then((rows) => {
      if (rows[0]) setVersion(rows[0]); else setError("현재 응답 가능한 후속 설문이 없습니다.");
    }).catch(() => setError("후속 설문 버전을 불러오지 못했습니다."));
  }, []);
  const submit = async () => {
    if (!version) return;
    const body: EfficacySubmission = {
      questionnaire_version_id: version.id,
      answers: Object.fromEntries(keys.map((key) => [key, likertToScore(answers[key] ?? 3)])),
    };
    setBusy(true); setError("");
    try {
      const response = await apiRequest<EfficacyView>("/me/efficacy-responses", { method: "POST", body: JSON.stringify(body) });
      setSaved(response);
      queryClient.setQueryData<{ baseline: number | null; responses: Array<{ normalized_score: number; submitted_at?: string }>; due_survey: boolean }>(["me", "efficacy"], (current) => current ? {
        ...current,
        responses: [...current.responses, { normalized_score: response.normalized_score, submitted_at: new Date().toISOString() }],
        due_survey: response.due_survey,
      } : current);
      await queryClient.invalidateQueries({ queryKey: ["me", "efficacy"], refetchType: "none" });
    }
    catch { setError("후속 설문을 저장하지 못했습니다."); }
    finally { setBusy(false); }
  };
  return (
    <section className="card card--padded">
      <p className="eyebrow">현재 응답 / {version?.version ?? "버전 확인 중"}</p>
      {keys.map((key) => (
        <div key={key}>
          <h2>{EFFICACY_COPY[key] ?? "정치 이슈를 이해하고 판단할 수 있나요?"}</h2>
          <Slider id={`efficacy-${key}`} label="1 전혀 그렇지 않다, 5 매우 그렇다" min={1} max={5} value={answers[key] ?? 3} onChange={(value) => setAnswers((current) => ({ ...current, [key]: value }))} />
        </div>
      ))}
      <Button onClick={() => void submit()} disabled={busy || !version}>{busy ? "저장 중..." : "이번 측정 저장"}</Button>
      {error && <p role="alert" style={{ color: "var(--danger)" }}>{error}</p>}
      {saved && <Toast message={`이번 측정을 100점 기준 ${saved.normalized_score}점으로 저장했습니다.`} />}
    </section>
  );
}
