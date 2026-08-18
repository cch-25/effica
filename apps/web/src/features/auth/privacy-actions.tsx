"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { TextField } from "@/components/ui/form-controls";
import { Toast } from "@/components/ui/toast";
import { apiRequest } from "@/lib/api/client";
import type { ConsentSubmission, ConsentView, DeleteAccountRequest, JobAccepted } from "@/lib/api/contracts";

export function PrivacyActions() {
  const [dialog, setDialog] = useState<"withdraw" | "delete" | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const consentQuery = useQuery({ queryKey: ["me", "consents"], queryFn: () => apiRequest<ConsentView[]>("/consents") });
  const sensitive = consentQuery.data?.find((consent) => consent.sensitive);
  const withdraw = async () => {
    if (!sensitive) { setError("철회할 민감정보 동의 버전을 찾지 못했습니다."); return; }
    setBusy(true); setError("");
    const body: ConsentSubmission = { consent_version_id: sensitive.id, granted: false };
    try {
      await apiRequest<ConsentView>("/me/consents", { method: "POST", body: JSON.stringify(body) });
      setStatus("정치 민감정보 동의가 철회되어 개인화와 행동 프로필이 중지되었습니다.");
      setDialog(null); await consentQuery.refetch();
    } catch { setError("동의를 철회하지 못했습니다. 현재 상태는 변경되지 않았습니다."); }
    finally { setBusy(false); }
  };
  const requestExport = async () => {
    setBusy(true); setError("");
    try {
      const job = await apiRequest<JobAccepted>("/me/export", { method: "POST" });
      setStatus(`데이터 내보내기 작업 ${job.job_id}이 ${job.status} 상태로 접수되었습니다.`);
    } catch { setError("데이터 내보내기 작업을 접수하지 못했습니다."); }
    finally { setBusy(false); }
  };
  const requestDeletion = async () => {
    const body: DeleteAccountRequest = { confirmation: "DELETE MY ACCOUNT" };
    if (confirmation !== body.confirmation) { setError("확인 문자열을 정확히 입력해 주세요."); return; }
    setBusy(true); setError("");
    try {
      const job = await apiRequest<JobAccepted>("/me", { method: "DELETE", body: JSON.stringify(body) });
      setStatus(`계정 삭제 작업 ${job.job_id}이 ${job.status} 상태로 접수되었습니다.`);
      setDialog(null);
    } catch { setError("계정 삭제 작업을 접수하지 못했습니다."); }
    finally { setBusy(false); }
  };

  return <>
    <section className="card card--padded">
      <div className="privacy-action"><div><strong>정치 민감정보 별도 동의</strong><p>{sensitive ? `${sensitive.granted ? "활성" : "철회됨"} · ${sensitive.version}` : "상태 확인 중"}</p></div><Button variant="secondary" disabled={busy || !sensitive?.granted} onClick={() => setDialog("withdraw")}>동의 철회</Button></div>
      <div className="privacy-action"><div><strong>내 데이터 내보내기</strong><p>JSON 아카이브를 비동기 작업으로 준비합니다.</p></div><Button variant="secondary" disabled={busy} onClick={requestExport}>내보내기 요청</Button></div>
      <div className="privacy-action"><div><strong>계정 삭제</strong><p>세션·공유 토큰은 즉시 폐기되고 법적 보존 조건을 확인한 뒤 개인 데이터가 파기 또는 비식별화됩니다.</p></div><Button variant="danger" disabled={busy} onClick={() => { setConfirmation(""); setDialog("delete"); }}>계정 삭제 요청</Button></div>
      {(error || consentQuery.isError) && <p role="alert" style={{ color: "var(--danger)" }}>{error || "현재 동의 상태를 불러오지 못했습니다."}</p>}
    </section>
    <Dialog open={dialog !== null} onClose={() => setDialog(null)} title={dialog === "delete" ? "계정을 삭제할까요?" : "별도 동의를 철회할까요?"}>
      {dialog === "delete" ? <><p>삭제 작업을 시작하려면 <strong>DELETE MY ACCOUNT</strong>를 입력해 주세요.</p><TextField id="delete-confirmation" label="확인 문자열" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></> : <p>철회 즉시 행동 프로필과 개인화가 중지됩니다. 비개인화 균형 피드는 계속 이용할 수 있습니다.</p>}
      <div className="form-actions"><Button variant="secondary" onClick={() => setDialog(null)}>취소</Button><Button variant={dialog === "delete" ? "danger" : "primary"} disabled={busy} onClick={dialog === "delete" ? requestDeletion : withdraw}>확인</Button></div>
    </Dialog>
    {status && <Toast message={status} />}
  </>;
}
