"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { z } from "zod";
import { Button } from "@/components/ui/button";

const questions = [
  { id: "economy", label: "경제적 불평등 완화를 위해 정부가 더 적극적으로 개입해야 한다.", left: "전혀 동의하지 않음", right: "매우 동의함" },
  { id: "culture", label: "사회 제도는 새로운 생활 방식과 가치 변화를 더 빠르게 반영해야 한다.", left: "전혀 동의하지 않음", right: "매우 동의함" },
  { id: "foreign", label: "국제 문제는 국가 단독 대응보다 다자 협력을 우선해야 한다.", left: "전혀 동의하지 않음", right: "매우 동의함" },
] as const;
const schema = z.record(z.string(), z.number().int().min(1).max(5));

export function QuestionnaireForm() {
  const router = useRouter();
  const [error, setError] = useState("");
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const answers = Object.fromEntries(questions.map(({ id }) => [id, Number(formData.get(id))]));
    if (!schema.safeParse(answers).success || Object.keys(answers).length !== questions.length) return setError("모든 필수 문항에 응답해 주세요.");
    router.push("/onboarding/demographics");
  };
  return (
    <form action="/onboarding/demographics" method="get" onSubmit={submit}>
      <div className="choice-grid">{questions.map((question, questionIndex) => <fieldset className="field card card--padded" key={question.id}><legend>{questionIndex + 1}. {question.label}</legend><div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: ".35rem", marginTop: ".75rem" }}>{[1,2,3,4,5].map((value) => <label className="radio-row" style={{ display: "grid", justifyItems: "center", padding: ".55rem" }} key={value}><input type="radio" name={question.id} value={value} /><span>{value}</span></label>)}</div><small style={{ display: "flex", justifyContent: "space-between" }}><span>{question.left}</span><span>{question.right}</span></small></fieldset>)}</div>
      {error && <p role="alert" style={{ color: "var(--danger)" }}>{error}</p>}
      <div className="form-actions"><Button type="button" variant="secondary" onClick={() => router.back()}>이전</Button><Button type="submit">응답 결과 확인</Button></div>
    </form>
  );
}
