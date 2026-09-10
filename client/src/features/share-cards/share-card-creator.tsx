"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { apiRequest } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { CheckboxField, SelectField, TextField } from "@/components/ui/form-controls";
import { PerspectivePreview } from "./perspective-preview";
import { consumptionSnapshot } from "./consumption";
import type { ShareCardCreate, ShareCardJobAccepted } from "@/lib/api/contracts";

const templateOptions = [{ value: "orbit", label: "자료 지면" }, { value: "editorial", label: "독자 기록지" }];
const schema = z.object({ template: z.enum(["orbit", "editorial"]), displayName: z.string().max(40), confirmed: z.literal(true) });

export function ShareCardCreator() {
  const router = useRouter();
  const [template, setTemplate] = useState<"orbit" | "editorial">("orbit");
  const [displayName, setDisplayName] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const progress = useQuery({
    queryKey: ["me", "progress"],
    queryFn: () => apiRequest<Record<string, unknown>>("/me/progress"),
    staleTime: 0,
    refetchOnWindowFocus: "always",
  });
  const snapshot = consumptionSnapshot(progress.data);
  const create = async () => {
    if (!snapshot) return setError("뉴스 소비 기록을 확인한 뒤 다시 시도해 주세요.");
    if (!schema.safeParse({ template, displayName, confirmed }).success) return setError("공개되는 정보를 확인하고 동의해 주세요.");
    setBusy(true); setError("");
    try {
      const body: ShareCardCreate = { template, display_name: displayName || undefined, political_data_publication_confirmed: true };
      const result = await apiRequest<ShareCardJobAccepted>("/share-cards", { method: "POST", body: JSON.stringify(body) });
      router.push(`/share/${result.share_card_id}`);
    } catch { setError("공유 카드 생성 요청을 처리하지 못했습니다. 입력한 내용은 유지됩니다."); }
    finally { setBusy(false); }
  };
  return <div className="grid grid--2 share-creator">
    <section className="card card--padded share-creator__form">
      <SelectField id="template" label="카드 모양" value={template} options={templateOptions} onValueChange={(value) => setTemplate(value as typeof template)} />
      <TextField id="display-name" label="표시 이름 (선택)" maxLength={40} value={displayName} onChange={(event) => setDisplayName(event.target.value)} description="입력한 이름만 표시합니다. 이메일과 설문 답변 원문은 공개하지 않습니다." />
      <CheckboxField checked={confirmed} onCheckedChange={setConfirmed} label="내 뉴스 소비 성향과 검사 결과가 공개된다는 점을 확인했습니다." description="다양성 점수와 검사 실시 여부, 검사한 경우 3차원 이념 위치가 포함됩니다. 공개 링크는 누구나 볼 수 있으며 카드는 언제든 폐기할 수 있습니다." />
      {(error || progress.isError) && <p role="alert" style={{ color: "var(--danger)" }}>{error || "내 기록을 불러오지 못했습니다."}</p>}
      {progress.isError && <Button variant="secondary" onClick={() => void progress.refetch()}>내 기록 다시 불러오기</Button>}
      <Button style={{ marginTop: "1rem", width: "100%" }} onClick={create} disabled={busy || progress.isPending || !snapshot}>{busy ? "카드 만드는 중..." : progress.isPending ? "내 기록 확인 중..." : "공유 카드 만들기"}</Button>
    </section>
    <PerspectivePreview displayName={displayName} template={template} snapshot={snapshot} />
  </div>;
}
