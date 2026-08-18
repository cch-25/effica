"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { CheckboxField } from "@/components/ui/form-controls";
import { apiRequest } from "@/lib/api/client";
import type { ConsentSubmission, ConsentView } from "@/lib/api/contracts";
import { withReturnTo } from "@/lib/navigation/return-to";

const schema = z.object({ service: z.literal(true), privacy: z.literal(true), political: z.literal(true) });

export function ConsentForm({ returnTo }: { returnTo: string }) {
  const router = useRouter();
  const [error, setError] = useState("");
  const [consents, setConsents] = useState<ConsentView[] | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    void apiRequest<ConsentView[]>("/consents").then(setConsents).catch(() => setError("현재 동의 문서 버전을 불러오지 못했습니다."));
  }, []);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const values = { service: formData.has("service"), privacy: formData.has("privacy"), political: formData.has("political") };
    const result = schema.safeParse(values);
    if (!result.success) return setError("필수 동의 항목을 모두 확인해 주세요.");
    if (!consents?.length) return setError("현재 동의 문서 버전을 확인한 뒤 다시 시도해 주세요.");
    setBusy(true); setError("");
    try {
      for (const consent of consents) {
        const body: ConsentSubmission = { consent_version_id: consent.id, granted: true };
        await apiRequest<ConsentView>("/me/consents", { method: "POST", body: JSON.stringify(body) });
      }
      router.push(withReturnTo("/onboarding/questionnaire", returnTo));
    } catch { setError("동의를 저장하지 못했습니다. 서버 상태를 확인하고 다시 시도해 주세요."); }
    finally { setBusy(false); }
  };
  return (
    <form action={withReturnTo("/onboarding/questionnaire", returnTo)} method="get" onSubmit={submit}>
      <div className="choice-grid">
        <CheckboxField name="service" label="[필수] 서비스 이용약관" description="서비스 제공과 계정 운영에 필요한 기본 약관입니다." />
        <CheckboxField name="privacy" label="[필수] 개인정보 처리" description="계정·활동 기록 처리 목적과 보관 기간을 확인합니다." />
        <CheckboxField name="political" label="[필수·별도] 정치 민감정보 처리" description="설문 응답 좌표와 개인화에 사용됩니다. 철회하면 행동 프로필과 개인화가 중지되며, 서비스는 비개인화 피드로 계속 이용할 수 있습니다." />
      </div>
      {error && <p role="alert" style={{ color: "var(--danger)", marginTop: "1rem" }}>{error}</p>}
      <div className="form-actions"><Button type="button" variant="secondary" onClick={() => router.push("/")}>나중에 하기</Button><Button type="submit" disabled={busy || !consents}>{busy ? "동의 저장 중…" : "동의하고 설문 시작"}</Button></div>
    </form>
  );
}
