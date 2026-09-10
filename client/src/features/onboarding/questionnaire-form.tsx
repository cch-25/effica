"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { RadioScale } from "@/components/ui/form-controls";
import { apiRequest } from "@/lib/api/client";
import { notifyProfileUpdated } from "@/lib/api/profile-sync";
import type { ProfileView, QuestionnaireSubmission, QuestionnaireVersionView } from "@/lib/api/contracts";
import { withReturnTo } from "@/lib/navigation/return-to";

type Question = { id: string; label: string; axis?: string };
const legacyLabels: Record<string, string> = {
  economic: "경제적 불평등 완화를 위해 정부가 더 적극적으로 개입해야 한다.",
  social: "사회 제도는 새로운 생활 방식과 가치 변화를 더 빠르게 반영해야 한다.",
  international: "국제 문제는 국가 단독 대응보다 다자 협력을 우선해야 한다.",
};

function questionsFrom(version: QuestionnaireVersionView | null): Question[] {
  const items = version?.schema_json?.questions;
  if (!Array.isArray(items)) return [];
  return items.flatMap((item: Record<string, unknown>) => {
    const id = String(item.id ?? "");
    const label = String(item.label ?? item.text ?? legacyLabels[id] ?? "");
    return id && label ? [{ id, label, axis: String(item.axis ?? "") }] : [];
  });
}

export function QuestionnaireForm({ returnTo }: { returnTo: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [error, setError] = useState("");
  const [version, setVersion] = useState<QuestionnaireVersionView | null>(null);
  const [busy, setBusy] = useState(false);
  const [page, setPage] = useState(0);
  const [answers, setAnswers] = useState<Record<string, number>>({});
  useEffect(() => {
    let active = true;
    void apiRequest<QuestionnaireVersionView[]>("/questionnaires?kind=onboarding").then((rows) => {
      if (!active) return;
      if (rows[0]) setVersion(rows[0]); else setError("현재 사용할 수 있는 검사 버전이 없습니다.");
    }).catch(() => { if (active) setError("검사 문항을 불러오지 못했습니다. 잠시 후 새로고침해 주세요."); });
    return () => { active = false; };
  }, []);
  const questions = useMemo(() => questionsFrom(version), [version]);
  const pageCount = Math.ceil(questions.length / 10);
  const currentQuestions = questions.slice(page * 10, (page + 1) * 10);
  const complete = (items: Question[]) => items.every(({ id }) => Number.isInteger(answers[id]) && answers[id] >= 1 && answers[id] <= 5);
  const goToPage = (next: number) => {
    setPage(next); setError("");
    document.getElementById("questionnaire-progress")?.focus();
    document.getElementById("questionnaire-progress")?.scrollIntoView({ block: "start" });
  };
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!complete(currentQuestions)) return setError("이 페이지의 모든 문항에 응답해 주세요.");
    if (page < pageCount - 1) { goToPage(page + 1); return; }
    if (!version || !questions.length || !complete(questions)) return setError("모든 문항에 응답한 뒤 결과를 확인해 주세요.");
    const body: QuestionnaireSubmission = {
      questionnaire_version_id: version.id,
      answers: Object.fromEntries(questions.map(({ id }) => [id, version.schema_json.scale ? answers[id] : (answers[id] - 3) * 50])),
    };
    setBusy(true); setError("");
    try {
      await apiRequest<ProfileView>("/me/questionnaire-responses", { method: "POST", body: JSON.stringify(body) });
      notifyProfileUpdated();
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      router.push(returnTo === "/share/new" ? returnTo : withReturnTo("/onboarding/demographics", returnTo));
    } catch { setError("응답을 저장하지 못했습니다. 입력한 답변은 유지되어 있으니 다시 시도해 주세요."); }
    finally { setBusy(false); }
  };
  return (
    <form onSubmit={submit} className="ideology-questionnaire">
      <div id="questionnaire-progress" tabIndex={-1} className="questionnaire-progress" aria-live="polite">
        <strong>{questions.length ? `${page + 1} / ${pageCount} 단계` : "문항을 불러오고 있습니다."}</strong>
        {questions.length > 0 && <span>총 {questions.length}문항 중 {Object.keys(answers).length}문항 응답</span>}
      </div>
      <p className="questionnaire-scale-help">1 전혀 동의하지 않음 / 2 동의하지 않음 / 3 보통 / 4 동의함 / 5 매우 동의함</p>
      <div className="questionnaire-items">{currentQuestions.map((question, index) => <fieldset className="field questionnaire-item" key={question.id}>
        <legend>{page * 10 + index + 1}. {question.label}</legend>
        <RadioScale name={question.id} values={[1, 2, 3, 4, 5]} required value={answers[question.id] ? String(answers[question.id]) : ""} onValueChange={(value) => setAnswers((current) => ({ ...current, [question.id]: Number(value) }))} />
        <small className="scale-labels"><span>전혀 동의하지 않음</span><span>매우 동의함</span></small>
      </fieldset>)}</div>
      {error && <p role="alert" style={{ color: "var(--danger)" }}>{error}</p>}
      <div className="form-actions">
        <Button type="button" variant="secondary" disabled={busy} onClick={() => page > 0 ? goToPage(page - 1) : router.push(withReturnTo("/onboarding/consent", returnTo))}>{page > 0 ? "이전 문항" : "동의 단계로"}</Button>
        <Button type="submit" disabled={busy || !questions.length}>{busy ? "응답 저장 중..." : page < pageCount - 1 ? "다음 문항" : "저장하고 결과 확인"}</Button>
      </div>
      <Button type="button" variant="ghost" disabled={busy} onClick={() => router.push(returnTo === "/share/new" ? returnTo : withReturnTo("/onboarding/demographics", returnTo))}>검사는 나중에 하기</Button>
    </form>
  );
}
