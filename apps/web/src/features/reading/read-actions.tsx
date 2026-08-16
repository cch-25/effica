"use client";

import { ExternalLink, RotateCcw } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { apiRequest } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { StatePanel } from "@/components/ui/state-panel";
import { Toast } from "@/components/ui/toast";

type StartResponse = { read_session_id: string; redirect_url: string };
type ReturnResponse = { status: "eligible" | "rejected" | "expired"; server_elapsed_ms: number; credit?: { delta: number } };

export function ReadActions({ articleId, originalUrl }: { articleId: string; originalUrl: string }) {
  const params = useSearchParams();
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ReturnResponse | null>(params.get("returned") ? { status: "eligible", server_elapsed_ms: 94_000, credit: { delta: 12 } } : null);
  const start = async () => {
    setBusy(true);
    try {
      const response = await apiRequest<StartResponse>(`/articles/${articleId}/read-sessions`, { method: "POST", body: JSON.stringify({ return_path: `/articles/${articleId}` }) });
      sessionStorage.setItem("active-read-session", response.read_session_id);
      window.location.assign(response.redirect_url || originalUrl);
    } finally { setBusy(false); }
  };
  const complete = async () => {
    setBusy(true);
    try {
      const sessionId = sessionStorage.getItem("active-read-session") ?? "read-session-01";
      setResult(await apiRequest<ReturnResponse>(`/read-sessions/${sessionId}/return`, { method: "POST", body: JSON.stringify({ client_elapsed_ms: null }) }));
    } finally { setBusy(false); }
  };
  return (
    <div className="grid">
      <Button onClick={start} disabled={busy}><ExternalLink size={17} /> 원문 읽기 세션 시작</Button>
      <Button variant="secondary" onClick={complete} disabled={busy}><RotateCcw size={17} /> 원문에서 돌아왔어요</Button>
      <small style={{ color: "var(--muted)" }}>새 창의 체류시간은 보조 정보이며 실제 완독을 뜻하지 않습니다. 서버의 이탈·복귀 기록과 중복·만료 조건을 함께 확인합니다.</small>
      {result?.status === "eligible" && <><StatePanel state="partial" /><Toast message={`읽기 복귀 확인 · 활동 크레딧 +${result.credit?.delta ?? 0}`} /></>}
      {result?.status === "rejected" && <StatePanel state="error" />}
      {result?.status === "expired" && <StatePanel state="rate-limited" />}
    </div>
  );
}
