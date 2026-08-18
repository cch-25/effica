"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { SelectField } from "@/components/ui/form-controls";
import { apiRequest } from "@/lib/api/client";
import type { DemographicsPatch } from "@/lib/api/contracts";

const ageOptions = [
  { value: "18-24", label: "18-24" },
  { value: "25-34", label: "25-34" },
  { value: "35-44", label: "35-44" },
  { value: "45-54", label: "45-54" },
  { value: "55-64", label: "55-64" },
  { value: "65+", label: "65+" },
];
const genderOptions = [
  { value: "FEMALE", label: "여성" },
  { value: "MALE", label: "남성" },
  { value: "NONBINARY", label: "논바이너리·기타" },
  { value: "PREFER_NOT_TO_SAY", label: "응답하지 않음" },
];

export function DemographicsForm({ returnTo }: { returnTo: string }) {
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
      router.push(returnTo || "/");
    } catch { setError("선택 응답을 저장하지 못했습니다. 다시 시도해 주세요."); }
    finally { setBusy(false); }
  };
  return (
    <form action={returnTo || "/"} method="get" onSubmit={submit}>
      <div className="notice">이 단계는 모두 선택입니다. 응답하지 않아도 서비스를 이용할 수 있습니다.</div>
      <SelectField className="field--spaced" id="age-band" label="연령대" value={age} options={ageOptions} placeholder="응답하지 않음" onValueChange={setAge} />
      <SelectField id="gender-response" label="성별 응답" value={gender} options={genderOptions} placeholder="응답하지 않음" onValueChange={setGender} />
      {error && <p role="alert" style={{ color: "var(--danger)" }}>{error}</p>}
      <div className="form-actions"><Button type="button" variant="secondary" onClick={() => router.back()}>이전</Button><Button type="submit" disabled={busy}>{busy ? "저장 중…" : age || gender ? (returnTo === "/" ? "저장하고 홈으로" : "저장하고 계속하기") : (returnTo === "/" ? "건너뛰고 홈으로" : "건너뛰고 계속하기")}</Button></div>
    </form>
  );
}
