"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { SelectField } from "@/components/ui/form-controls";
import { apiRequest } from "@/lib/api/client";
import type { DemographicsPatch } from "@/lib/api/contracts";

const ageOptions = ["18–24", "25–34", "35–44", "45–54", "55–64", "65+"].map((value) => ({ value, label: value }));
const genderOptions = ["여성", "남성", "논바이너리·기타"].map((value) => ({ value, label: value }));

export function DemographicsForm() {
  const router = useRouter();
  const [age, setAge] = useState("");
  const [gender, setGender] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true); setError("");
    const body: DemographicsPatch = { age_band: age || null, gender_response: gender || null };
    try {
      await apiRequest<DemographicsPatch>("/me/demographics", { method: "PATCH", body: JSON.stringify(body) });
      router.push("/");
    } catch { setError("선택 응답을 저장하지 못했습니다. 다시 시도해 주세요."); }
    finally { setBusy(false); }
  };
  return (
    <form action="/" method="get" onSubmit={submit}>
      <div className="notice">이 단계는 모두 선택입니다. 응답하지 않아도 서비스를 이용할 수 있습니다.</div>
      <SelectField className="field--spaced" id="age-band" label="연령대" value={age} options={ageOptions} placeholder="응답하지 않음" onValueChange={setAge} />
      <SelectField id="gender-response" label="성별 응답" value={gender} options={genderOptions} placeholder="응답하지 않음" onValueChange={setGender} />
      <section className="card card--padded"><p className="eyebrow">현재 응답 결과</p><h2>편향성 중립적 · 과장성 18/100</h2><p style={{ color: "var(--muted)" }}>편향성은 좌편향과 우편향 사이의 관찰값이며, 과장성은 표현 강도를 나타냅니다. 이 결과는 정치적 정체성이나 사실 여부를 확정하지 않습니다. 분석 신뢰도 보통 · 68%</p></section>
      {error && <p role="alert" style={{ color: "var(--danger)" }}>{error}</p>}
      <div className="form-actions"><Button type="button" variant="secondary" onClick={() => router.back()}>이전</Button><Button type="submit" disabled={busy}>{busy ? "저장 중…" : age || gender ? "저장하고 홈으로" : "건너뛰고 홈으로"}</Button></div>
    </form>
  );
}
