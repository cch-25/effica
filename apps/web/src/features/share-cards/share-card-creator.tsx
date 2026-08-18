"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { z } from "zod";
import { apiRequest } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { CheckboxField, SelectField, TextField } from "@/components/ui/form-controls";
import { PerspectivePreview } from "./perspective-preview";
import type { ShareCardCreate, ShareCardJobAccepted } from "@/lib/api/contracts";

const templateOptions = [{ value: "orbit", label: "스펙트럼형" }, { value: "editorial", label: "편집형" }];

const schema = z.object({ template: z.enum(["orbit", "editorial"]), displayName: z.string().max(40), confirmed: z.literal(true) });

export function ShareCardCreator() {
  const router = useRouter(); const [template, setTemplate] = useState<"orbit"|"editorial">("orbit"); const [displayName, setDisplayName] = useState("김사이"); const [confirmed, setConfirmed] = useState(false); const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const create = async () => { const parsed = schema.safeParse({ template, displayName, confirmed }); if (!parsed.success) return setError("편향성과 과장성 점수 공개 확인에 동의해야 카드를 만들 수 있습니다."); setBusy(true); setError(""); try { const body: ShareCardCreate = { template, display_name: displayName || undefined, political_data_publication_confirmed: true }; const result = await apiRequest<ShareCardJobAccepted>("/share-cards", { method: "POST", body: JSON.stringify(body) }); router.push(`/share/${result.share_card_id}`); } catch { setError("공유 카드 생성 요청을 처리하지 못했습니다. 입력은 보존되었습니다."); } finally { setBusy(false); } };
  return <div className="grid grid--2"><section className="card card--padded"><SelectField id="template" label="템플릿" value={template} options={templateOptions} onValueChange={(value) => setTemplate(value as typeof template)} /><TextField id="display-name" label="표시 이름 (선택)" maxLength={40} value={displayName} onChange={(event) => setDisplayName(event.target.value)} description="이메일·실명·설문 원응답은 포함하지 않습니다." /><CheckboxField checked={confirmed} onCheckedChange={setConfirmed} label="내 편향성과 과장성 점수가 공개된다는 점을 확인했습니다." description="생성된 공개 링크는 누구나 볼 수 있습니다. 카드는 언제든 즉시 폐기할 수 있습니다." />{error && <p role="alert" style={{ color: "var(--danger)" }}>{error}</p>}<Button style={{ marginTop: "1rem", width: "100%" }} onClick={create} disabled={busy}>{busy ? "생성 요청 중…" : "공유 카드 생성"}</Button></section><PerspectivePreview displayName={displayName} template={template} /></div>;
}
