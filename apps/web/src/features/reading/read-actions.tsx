"use client";

import { ExternalLink, RotateCcw } from "lucide-react";
import { useState } from "react";
import { apiRequest } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { StatePanel } from "@/components/ui/state-panel";
import { Toast } from "@/components/ui/toast";
import type { ReadResult, ReadSessionView } from "@/lib/api/contracts";

export function ReadActions({ articleId, originalUrl }: { articleId: string; originalUrl: string }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ReadResult | null>(null);
  const [error, setError] = useState("");
  const storageKey = `active-read-session:${articleId}`;
  const start = async () => {
    setBusy(true); setError("");
    try {
      const response = await apiRequest<ReadSessionView>(`/articles/${articleId}/read-sessions`, { method: "POST", body: JSON.stringify({ return_path: `/articles/${articleId}` }) });
      sessionStorage.setItem(storageKey, response.read_session_id);
      window.location.assign(response.redirect_url || originalUrl);
    } catch { setError("읽기 세션을 시작하지 못했습니다."); }
    finally { setBusy(false); }
  };
  const complete = async () => {
    setBusy(true); setError("");
    try {
      const sessionId = sessionStorage.getItem(storageKey);
      if (!sessionId) { setError("이 기사에서 시작한 읽기 세션이 없습니다."); return; }
      const returned = await apiRequest<ReadResult>(`/read-sessions/${encodeURIComponent(sessionId)}/return`, { method: "POST", body: JSON.stringify({ client_elapsed_ms: null }) });
      setResult(returned);
      sessionStorage.removeItem(storageKey);
    } catch { setError("읽기 복귀를 확인하지 못했습니다."); }
    finally { setBusy(false); }
  };
  return (
    <div className="grid">
      <Button onClick={start} disabled={busy}><ExternalLink size={17} /> 원문 읽기 세션 시작</Button>
      <Button variant="secondary" onClick={complete} disabled={busy}><RotateCcw size={17} /> 원문에서 돌아왔어요</Button>
      <small style={{ color: "var(--muted)" }}>새 창의 체류시간은 보조 정보이며 실제 완독을 뜻하지 않습니다. 서버의 이탈·복귀 기록과 중복·만료 조건을 함께 확인합니다.</small>
      {error && <p role="alert" style={{ color: "var(--danger)" }}>{error}</p>}
      {result?.status === "eligible" && <><StatePanel state="partial" /><Toast message={`읽기 복귀 확인 · 활동 크레딧 +${result.credit_delta}`} /></>}
      {result?.status === "rejected" && <StatePanel state="error" />}
      {result?.status === "expired" && <StatePanel state="rate-limited" />}
    </div>
  );
}
