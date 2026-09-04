"use client";

import { Switch } from "@base-ui/react/switch";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { LockKeyhole, PauseCircle, PlayCircle, RefreshCcw } from "lucide-react";
import { useState } from "react";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { TextareaField } from "@/components/ui/form-controls";
import { StatePanel } from "@/components/ui/state-panel";
import { Toast } from "@/components/ui/toast";
import { ApiError, apiRequest, createIdempotencyKey } from "@/lib/api/client";
import type { Role } from "@/lib/api/types";

type LLMUsage = {
  enabled: boolean;
  status: "RUNNING" | "STOPPED";
  version: number;
  cancelled_jobs: number;
  updated_by: string | null;
  updated_at: string | null;
};

const path = "/admin/runtime/llm-usage";

export function RuntimeControlPage({ role }: { role: Role }) {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["admin", path], queryFn: () => apiRequest<LLMUsage>(path) });
  const [desired, setDesired] = useState<boolean | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const canChange = role === "admin";
  const state = query.data;

  const requestChange = (next: boolean) => {
    if (!state || !canChange || next === state.enabled) return;
    setDesired(next);
    setReason("");
    setError("");
  };

  const confirm = async () => {
    if (desired === null || !state || !reason.trim()) return;
    setBusy(true);
    setError("");
    try {
      const headers = new Headers({
        "Idempotency-Key": createIdempotencyKey(),
        "If-Match": String(state.version),
      });
      const updated = await apiRequest<LLMUsage>(path, {
        method: "PUT",
        headers,
        body: JSON.stringify({ enabled: desired, reason: reason.trim() }),
      });
      queryClient.setQueryData(["admin", path], updated);
      setToast(updated.enabled ? "백그라운드 실행을 시작했습니다." : `전체 실행을 중지했습니다. 취소한 작업 ${updated.cancelled_jobs}건`);
      setDesired(null);
    } catch (requestError) {
      if (requestError instanceof ApiError && requestError.status === 409) {
        await query.refetch();
        setError("상태가 먼저 변경되었습니다. 최신 상태를 확인한 뒤 다시 시도해 주세요.");
      } else {
        setError(requestError instanceof Error ? requestError.message : "실행 상태를 변경하지 못했습니다.");
      }
    } finally {
      setBusy(false);
    }
  };

  return <>
    <PageHeader
      eyebrow="Runtime control"
      title="LLM 사용"
      description="끄면 수집 스케줄과 모든 백그라운드 작업이 멈추며 대기 중인 작업도 취소됩니다."
      actions={<><Badge tone="info">role: {role}</Badge><Button variant="secondary" onClick={() => void query.refetch()}><RefreshCcw size={16} /> 새로고침</Button></>}
    />
    {query.isPending ? <StatePanel state="loading" /> : query.isError || !state ? <StatePanel state="error" onRetry={() => void query.refetch()} /> : (
      <section className={`runtime-control runtime-control--${state.enabled ? "running" : "stopped"}`} aria-live="polite">
        <div className="runtime-control__state">
          {state.enabled ? <PlayCircle size={20} aria-hidden="true" /> : <PauseCircle size={20} aria-hidden="true" />}
          <div>
            <span className="runtime-control__eyebrow">현재 상태</span>
            <strong>{state.status}</strong>
            <p>{state.enabled ? "수집과 분석 작업을 실행할 수 있습니다." : "새 작업을 실행하지 않습니다. 직접 켜기 전까지 이 상태가 유지됩니다."}</p>
          </div>
        </div>
        <div className="runtime-control__meta">
          <span>설정 버전 {state.version}</span>
          <span>{state.updated_at ? `최근 변경 ${new Date(state.updated_at).toLocaleString("ko-KR")}` : "아직 변경 기록이 없습니다."}</span>
        </div>
        <label className="runtime-switch-label">
          <span><strong>LLM 사용</strong><small>{canChange ? "관리자 전용 전체 실행 스위치" : "ADMIN 권한이 필요합니다."}</small></span>
          {!canChange && <LockKeyhole size={15} aria-hidden="true" />}
          <Switch.Root className="runtime-switch" checked={state.enabled} disabled={!canChange || busy} onCheckedChange={requestChange} aria-label="LLM 사용">
            <Switch.Thumb className="runtime-switch__thumb" />
          </Switch.Root>
        </label>
      </section>
    )}
    <Dialog
      open={desired !== null}
      onClose={() => { if (!busy) setDesired(null); }}
      title={desired ? "백그라운드 실행 시작" : "전체 실행 중지"}
      description={desired ? "수집과 분석 작업이 다시 실행됩니다." : "실행 중인 작업과 대기 중인 작업을 모두 중지합니다."}
    >
      <TextareaField id="llm-usage-reason" label="변경 사유 (필수)" value={reason} onChange={(event) => setReason(event.target.value)} />
      {error && <p className="runtime-control__error" role="alert">{error}</p>}
      <div className="form-actions"><Button variant="secondary" disabled={busy} onClick={() => setDesired(null)}>취소</Button><Button variant={desired ? "primary" : "danger"} disabled={!reason.trim() || busy} onClick={confirm}>{busy ? "반영 중..." : desired ? "실행 시작" : "전체 중지"}</Button></div>
    </Dialog>
    {toast && <Toast message={toast} />}
  </>;
}
