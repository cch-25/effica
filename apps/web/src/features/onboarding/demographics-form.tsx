"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { SelectField } from "@/components/ui/form-controls";

const ageOptions = ["18–24", "25–34", "35–44", "45–54", "55–64", "65+"].map((value) => ({ value, label: value }));
const genderOptions = ["여성", "남성", "논바이너리·기타"].map((value) => ({ value, label: value }));

export function DemographicsForm() {
  const router = useRouter();
  const [age, setAge] = useState("");
  const [gender, setGender] = useState("");
  const submit = (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); router.push("/"); };
  return (
    <form action="/" method="get" onSubmit={submit}>
      <div className="notice">이 단계는 모두 선택입니다. 응답하지 않아도 서비스를 이용할 수 있습니다.</div>
      <SelectField className="field--spaced" id="age-band" label="연령대" value={age} options={ageOptions} placeholder="응답하지 않음" onValueChange={setAge} />
      <SelectField id="gender-response" label="성별 응답" value={gender} options={genderOptions} placeholder="응답하지 않음" onValueChange={setGender} />
      <section className="card card--padded"><p className="eyebrow">현재 응답 결과</p><h2>경제 −20 · 사회문화 +18 · 국가·대외 −12</h2><p style={{ color: "var(--muted)" }}>이 결과는 현재 설문 응답을 정규화한 관찰값이며, 당신의 정치적 정체성을 확정하거나 평가하지 않습니다. 분석 신뢰도 보통 · 68%</p></section>
      <div className="form-actions"><Button type="button" variant="secondary" onClick={() => router.back()}>이전</Button><Button type="submit">{age || gender ? "저장하고 홈으로" : "건너뛰고 홈으로"}</Button></div>
    </form>
  );
}
