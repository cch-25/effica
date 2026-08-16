"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";

export function DemographicsForm() {
  const router = useRouter();
  const [age, setAge] = useState("");
  const [gender, setGender] = useState("");
  const submit = (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); router.push("/"); };
  return (
    <form action="/" method="get" onSubmit={submit}>
      <div className="notice">이 단계는 모두 선택입니다. 응답하지 않아도 서비스를 이용할 수 있습니다.</div>
      <div className="field" style={{ marginTop: "1.2rem" }}><label htmlFor="age-band">연령대</label><select className="select" id="age-band" value={age} onChange={(event) => setAge(event.target.value)}><option value="">응답하지 않음</option><option>18–24</option><option>25–34</option><option>35–44</option><option>45–54</option><option>55–64</option><option>65+</option></select></div>
      <div className="field"><label htmlFor="gender-response">성별 응답</label><select className="select" id="gender-response" value={gender} onChange={(event) => setGender(event.target.value)}><option value="">응답하지 않음</option><option>여성</option><option>남성</option><option>논바이너리·기타</option></select></div>
      <section className="card card--padded"><p className="eyebrow">현재 응답 결과</p><h2>경제 −20 · 사회문화 +18 · 국가·대외 −12</h2><p style={{ color: "var(--muted)" }}>이 결과는 현재 설문 응답을 정규화한 관찰값이며, 당신의 정치적 정체성을 확정하거나 평가하지 않습니다. 분석 신뢰도 보통 · 68%</p></section>
      <div className="form-actions"><Button type="button" variant="secondary" onClick={() => router.back()}>이전</Button><Button type="submit">{age || gender ? "저장하고 홈으로" : "건너뛰고 홈으로"}</Button></div>
    </form>
  );
}
