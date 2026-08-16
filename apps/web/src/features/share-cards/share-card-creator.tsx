"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { z } from "zod";
import { apiRequest } from "@/lib/api/client";
import { Button } from "@/components/ui/button";

const schema = z.object({ template: z.enum(["orbit", "editorial"]), displayName: z.string().max(40), confirmed: z.literal(true) });

export function ShareCardCreator() {
  const router = useRouter(); const [template, setTemplate] = useState<"orbit"|"editorial">("orbit"); const [displayName, setDisplayName] = useState("김사이"); const [confirmed, setConfirmed] = useState(false); const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const create = async () => { const parsed = schema.safeParse({ template, displayName, confirmed }); if (!parsed.success) return setError("정치 좌표 공개 확인에 동의해야 카드를 만들 수 있습니다."); setBusy(true); setError(""); try { const result = await apiRequest<{ id: string }>("/share-cards", { method: "POST", body: JSON.stringify({ template, display_name: displayName || undefined, political_data_publication_confirmed: true }) }); router.push(`/share/${result.id}`); } catch { setError("공유 카드 생성 요청을 처리하지 못했습니다. 입력은 보존되었습니다."); } finally { setBusy(false); } };
  return <div className="grid grid--2"><section className="card card--padded"><div className="field"><label htmlFor="template">템플릿</label><select id="template" className="select" value={template} onChange={(event) => setTemplate(event.target.value as typeof template)}><option value="orbit">궤도</option><option value="editorial">에디토리얼</option></select></div><div className="field"><label htmlFor="display-name">표시 이름 (선택)</label><input id="display-name" className="input" maxLength={40} value={displayName} onChange={(event) => setDisplayName(event.target.value)} /><small>이메일·실명·설문 원응답은 포함하지 않습니다.</small></div><label className="check-row"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /><span><strong>내 정치 좌표가 공개된다는 점을 확인했습니다.</strong><small style={{ display: "block" }}>생성된 공개 링크는 누구나 볼 수 있습니다. 카드는 언제든 즉시 폐기할 수 있습니다.</small></span></label>{error && <p role="alert" style={{ color: "var(--danger)" }}>{error}</p>}<Button style={{ marginTop: "1rem", width: "100%" }} onClick={create} disabled={busy}>{busy ? "생성 요청 중…" : "공유 카드 생성"}</Button></section><section className={`share-preview share-preview--${template}`}><p>MY PERSPECTIVE / 2026</p><h2>{displayName || "표시 이름 없음"}</h2><div className="share-preview__orbit"><span /><span /><span /></div><dl><div><dt>경제</dt><dd>+4</dd></div><div><dt>사회문화</dt><dd>+18</dd></div><div><dt>국가·대외</dt><dd>−12</dd></div></dl><small>현재 응답 결과 · confidence 68% · 탐색가 tier</small></section></div>;
}
