"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { TextField } from "@/components/ui/form-controls";
import { Toast } from "@/components/ui/toast";
import { apiRequest, ApiError } from "@/lib/api/client";
import type { ConsentSubmission, ConsentView, DeleteAccountRequest, JobAccepted } from "@/lib/api/contracts";

type ExportStatus = {
  job_id: string;
  status: string;
  download_ready: boolean;
  download_url: string | null;
  expires_at: string | null;
  failure_code: string | null;
};
const waiting = (status?: string) => status === "PENDING" || status === "LEASED";
function exportMessage(job: ExportStatus): string {
  if (job.download_ready) return "내 데이터 파일이 준비되었습니다. 아래에서 내려받을 수 있습니다.";
  if (waiting(job.status)) return "내 데이터를 파일로 준비하고 있습니다. 완료되면 이 화면에 다운로드 버튼이 표시됩니다.";
  if (job.status === "SUCCEEDED") return "이전에 준비한 파일의 다운로드 기간이 지났거나 파일을 사용할 수 없습니다. 다시 요청해 주세요.";
  if (job.status === "CANCELLED") return "데이터 내보내기가 취소되었습니다. 필요하면 다시 요청해 주세요.";
  return "내 데이터 파일을 준비하지 못했습니다. 다시 요청해 주세요.";
}

export function PrivacyActions() {
  const [dialog, setDialog] = useState<"withdraw" | "delete" | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [status, setStatus] = useState("");
  const [statusTitle, setStatusTitle] = useState("완료");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const consentQuery = useQuery({ queryKey: ["me", "consents"], queryFn: () => apiRequest<ConsentView[]>("/consents") });
  const exportQuery = useQuery({
    queryKey: ["me", "export"],
    queryFn: async () => {
      try { return await apiRequest<ExportStatus>("/me/export"); }
      catch (cause) { if (cause instanceof ApiError && cause.status === 404) return null; throw cause; }
    },
    retry: false,
    refetchInterval: (query) => waiting(query.state.data?.status) ? 2_000 : false,
    refetchOnWindowFocus: "always",
  });
  const sensitive = consentQuery.data?.find((consent) => consent.sensitive);
  const withdraw = async () => {
    if (!sensitive) { setError("철회할 민감정보 동의 버전을 찾지 못했습니다."); return; }
    setBusy(true); setError("");
    const body: ConsentSubmission = { consent_version_id: sensitive.id, granted: false };
    try {
      await apiRequest<ConsentView>("/me/consents", { method: "POST", body: JSON.stringify(body) });
      setStatusTitle("완료");
      setStatus("정치 민감정보 동의가 철회되어 개인화와 행동 프로필이 중지되었습니다.");
      setDialog(null); await consentQuery.refetch();
    } catch { setError("동의를 철회하지 못했습니다. 현재 상태는 변경되지 않았습니다."); }
    finally { setBusy(false); }
  };
  const requestExport = async () => {
    setBusy(true); setError("");
    try {
      const job = await apiRequest<JobAccepted>("/me/export", { method: "POST" });
      if (job.status === "DEAD" || job.status === "FAILED" || job.status === "CANCELLED") {
        setError("내 데이터 파일을 준비하지 못했습니다. 다시 요청해 주세요.");
      } else {
        setStatusTitle("요청 접수");
        setStatus("내 데이터 파일을 요청했습니다. 준비 상태는 이 화면에서 확인할 수 있습니다.");
      }
      await exportQuery.refetch();
    } catch { setError("데이터 내보내기 작업을 접수하지 못했습니다."); }
    finally { setBusy(false); }
  };
  const requestDeletion = async () => {
    const body: DeleteAccountRequest = { confirmation: "DELETE MY ACCOUNT" };
    if (confirmation !== body.confirmation) { setError("확인 문자열을 정확히 입력해 주세요."); return; }
    setBusy(true); setError("");
    try {
      const job = await apiRequest<JobAccepted>("/me", { method: "DELETE", body: JSON.stringify(body) });
      if (job.status === "DEAD" || job.status === "FAILED") { setError("계정 삭제를 처리하지 못했습니다. 잠시 후 다시 시도해 주세요."); return; }
      setStatusTitle("요청 접수");
      setStatus("계정 삭제 요청을 접수했습니다. 처리 상태에 따라 계정 이용이 중단됩니다.");
      setDialog(null);
    } catch { setError("계정 삭제 작업을 접수하지 못했습니다."); }
    finally { setBusy(false); }
  };

  return <>
    <section className="card card--padded">
      <div className="privacy-action"><div><strong>정치 민감정보 별도 동의</strong><p>{sensitive ? `${sensitive.granted ? "활성" : "철회됨"}, ${sensitive.version}` : "상태 확인 중"}</p></div><Button variant="secondary" disabled={busy || !sensitive?.granted} onClick={() => setDialog("withdraw")}>동의 철회</Button></div>
      <div className="privacy-action"><div><strong>내 데이터 내보내기</strong><p>내 계정 정보와 활동 기록을 하나의 파일로 내려받을 수 있습니다. 파일 준비에는 잠시 시간이 걸릴 수 있습니다.</p>
        {exportQuery.data && <div className="export-status" role={waiting(exportQuery.data.status) || exportQuery.data.download_ready ? "status" : "alert"} aria-live="polite">
          <p>{exportMessage(exportQuery.data)}</p>
          {exportQuery.data.download_ready && exportQuery.data.download_url?.startsWith("/api/v1/me/export/") && <a className="button button--secondary" href={exportQuery.data.download_url} download>내 데이터 다운로드</a>}
          {exportQuery.data.download_ready && exportQuery.data.expires_at && <p>다운로드 가능 기간: {new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Seoul" }).format(new Date(exportQuery.data.expires_at))} (한국 시간)까지</p>}
        </div>}
        {exportQuery.isError && <p role="alert">내보내기 상태를 확인하지 못했습니다. <Button variant="ghost" onClick={() => void exportQuery.refetch()}>다시 확인</Button></p>}
      </div><Button variant="secondary" disabled={busy || waiting(exportQuery.data?.status)} onClick={requestExport}>{waiting(exportQuery.data?.status) ? "파일 준비 중" : exportQuery.data ? "새 파일 요청" : "내보내기 요청"}</Button></div>
      <div className="privacy-action"><div><strong>계정 삭제</strong><p>세션과 공유 토큰은 즉시 폐기되고 법적 보존 조건을 확인한 뒤 개인 데이터가 파기 또는 비식별화됩니다.</p></div><Button variant="danger" disabled={busy} onClick={() => { setConfirmation(""); setDialog("delete"); }}>계정 삭제 요청</Button></div>
      {(error || consentQuery.isError) && <p role="alert" style={{ color: "var(--danger)" }}>{error || "현재 동의 상태를 불러오지 못했습니다."}</p>}
    </section>
    <Dialog open={dialog !== null} onClose={() => setDialog(null)} title={dialog === "delete" ? "계정을 삭제할까요?" : "별도 동의를 철회할까요?"}>
      {dialog === "delete" ? <><p>삭제 작업을 시작하려면 <strong>DELETE MY ACCOUNT</strong>를 입력해 주세요.</p><TextField id="delete-confirmation" label="확인 문자열" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></> : <p>철회 즉시 행동 프로필과 개인화가 중지됩니다. 비개인화 균형 피드는 계속 이용할 수 있습니다.</p>}
      <div className="form-actions"><Button variant="secondary" onClick={() => setDialog(null)}>취소</Button><Button variant={dialog === "delete" ? "danger" : "primary"} disabled={busy} onClick={dialog === "delete" ? requestDeletion : withdraw}>확인</Button></div>
    </Dialog>
    {status && <Toast message={status} title={statusTitle} />}
  </>;
}
