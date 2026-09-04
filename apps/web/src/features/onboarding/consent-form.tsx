"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { CheckboxField } from "@/components/ui/form-controls";
import { apiRequest } from "@/lib/api/client";
import type { ConsentSubmission, ConsentView } from "@/lib/api/contracts";
import { withReturnTo } from "@/lib/navigation/return-to";

function consentCopy(consent: ConsentView): { label: string; description: string } {
  if (consent.purpose === "SERVICE") return {
    label: "[필수] 서비스 이용 및 개인정보 처리",
    description: "서비스 제공, 계정 운영, 활동 기록 처리에 필요한 기본 동의입니다.",
  };
  if (consent.purpose === "POLITICAL_PROFILE") return {
    label: "[필수 별도] 정치 민감정보 처리",
    description: "설문 응답과 개인화에 사용합니다. 철회하면 개인화가 중지되며 비개인화 피드는 계속 이용할 수 있습니다.",
  };
  return { label: "[필수] 추가 정보 처리", description: "현재 서비스 이용에 필요한 정보 처리 목적과 범위를 확인합니다." };
}

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
    if (!consents?.length) return setError("현재 동의 문서 버전을 확인한 뒤 다시 시도해 주세요.");
    if (consents.some((consent) => !formData.has(consent.id))) return setError("필수 동의 항목을 모두 확인해 주세요.");
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
        {consents?.map((consent) => {
          const copy = consentCopy(consent);
          return <CheckboxField key={consent.id} name={consent.id} label={copy.label} description={copy.description} />;
        })}
      </div>
      {error && <p role="alert" style={{ color: "var(--danger)", marginTop: "1rem" }}>{error}</p>}
      <div className="form-actions"><Button type="button" variant="secondary" onClick={() => router.push(returnTo)}>동의하지 않고 이전 화면으로</Button><Button type="submit" disabled={busy || !consents}>{busy ? "동의 저장 중..." : "동의하고 관점 설문으로"}</Button></div>
    </form>
  );
}
