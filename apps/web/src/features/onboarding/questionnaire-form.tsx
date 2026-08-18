"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { RadioScale } from "@/components/ui/form-controls";
import { apiRequest } from "@/lib/api/client";
import type { ProfileView, QuestionnaireSubmission, QuestionnaireVersionView } from "@/lib/api/contracts";

const questions = [
  { id: "economy", label: "경제적 불평등 완화를 위해 정부가 더 적극적으로 개입해야 한다.", left: "전혀 동의하지 않음", right: "매우 동의함" },
  { id: "culture", label: "사회 제도는 새로운 생활 방식과 가치 변화를 더 빠르게 반영해야 한다.", left: "전혀 동의하지 않음", right: "매우 동의함" },
  { id: "foreign", label: "국제 문제는 국가 단독 대응보다 다자 협력을 우선해야 한다.", left: "전혀 동의하지 않음", right: "매우 동의함" },
] as const;
const schema = z.record(z.string(), z.number().int().min(1).max(5));

export function QuestionnaireForm() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [version, setVersion] = useState<QuestionnaireVersionView | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    void apiRequest<QuestionnaireVersionView[]>("/questionnaires?kind=onboarding").then((rows) => {
      if (rows[0]) setVersion(rows[0]); else setError("현재 사용할 수 있는 설문 버전이 없습니다.");
    }).catch(() => setError("현재 설문 버전을 불러오지 못했습니다."));
  }, []);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const answers = Object.fromEntries(questions.map(({ id }) => [id, Number(formData.get(id))]));
    if (!schema.safeParse(answers).success || Object.keys(answers).length !== questions.length) return setError("모든 필수 문항에 응답해 주세요.");
    if (!version) return setError("현재 설문 버전을 확인한 뒤 다시 시도해 주세요.");
    const scoredAnswers = Object.fromEntries(questions.map(({ id }, index) => [version.keys?.[index] ?? id, (answers[id] - 3) * 50]));
    const body: QuestionnaireSubmission = { questionnaire_version_id: version.id, answers: scoredAnswers };
    setBusy(true); setError("");
    try {
      await apiRequest<ProfileView>("/me/questionnaire-responses", { method: "POST", body: JSON.stringify(body) });
      router.push("/onboarding/demographics");
    } catch { setError("설문 응답을 저장하지 못했습니다. 응답은 화면에 보존되어 있습니다."); }
    finally { setBusy(false); }
  };
  return (
    <form action="/onboarding/demographics" method="get" onSubmit={submit}>
      <div className="choice-grid">{questions.map((question, questionIndex) => <fieldset className="field card card--padded" key={question.id}><legend>{questionIndex + 1}. {question.label}</legend><RadioScale name={question.id} values={[1, 2, 3, 4, 5]} required /><small className="scale-labels"><span>{question.left}</span><span>{question.right}</span></small></fieldset>)}</div>
      {error && <p role="alert" style={{ color: "var(--danger)" }}>{error}</p>}
      <div className="form-actions"><Button type="button" variant="secondary" onClick={() => router.back()}>이전</Button><Button type="submit" disabled={busy || !version}>{busy ? "응답 저장 중…" : "응답 결과 확인"}</Button></div>
    </form>
  );
}
