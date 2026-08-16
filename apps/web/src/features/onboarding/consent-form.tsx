"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { z } from "zod";
import { Button } from "@/components/ui/button";

const schema = z.object({ service: z.literal(true), privacy: z.literal(true), political: z.literal(true) });

export function ConsentForm() {
  const router = useRouter();
  const [error, setError] = useState("");
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const values = { service: formData.has("service"), privacy: formData.has("privacy"), political: formData.has("political") };
    const result = schema.safeParse(values);
    if (!result.success) return setError("필수 동의 항목을 모두 확인해 주세요.");
    router.push("/onboarding/questionnaire");
  };
  return (
    <form action="/onboarding/questionnaire" method="get" onSubmit={submit}>
      <div className="choice-grid">
        <label className="check-row"><input name="service" type="checkbox" /><span><strong>[필수] 서비스 이용약관</strong><small style={{ display: "block" }}>서비스 제공과 계정 운영에 필요한 기본 약관입니다.</small></span></label>
        <label className="check-row"><input name="privacy" type="checkbox" /><span><strong>[필수] 개인정보 처리</strong><small style={{ display: "block" }}>계정·활동 기록 처리 목적과 보관 기간을 확인합니다.</small></span></label>
        <label className="check-row"><input name="political" type="checkbox" /><span><strong>[필수·별도] 정치 민감정보 처리</strong><small style={{ display: "block" }}>설문 응답 좌표와 개인화에 사용됩니다. 철회하면 행동 프로필과 개인화가 중지되며, 서비스는 비개인화 피드로 계속 이용할 수 있습니다.</small></span></label>
      </div>
      {error && <p role="alert" style={{ color: "var(--danger)", marginTop: "1rem" }}>{error}</p>}
      <div className="form-actions"><Button type="button" variant="secondary" onClick={() => router.push("/")}>나중에 하기</Button><Button type="submit">동의하고 설문 시작</Button></div>
    </form>
  );
}
