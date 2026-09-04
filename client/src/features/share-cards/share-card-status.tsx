"use client";

import { Copy, Download, ExternalLink, RefreshCw, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { apiRequest } from "@/lib/api/client";
import type { ShareCardJobAccepted, ShareCardView } from "@/lib/api/contracts";
import { Button, ButtonLink } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Toast } from "@/components/ui/toast";
import { formatPublishedDate, formatTierLabel } from "@/lib/api/formatters";

const statusLabels: Record<ShareCardView["status"], string> = { queued: "생성 대기", rendering: "생성 중", ready: "생성 완료", failed: "생성 실패", revoked: "폐기됨" };
const statusDescriptions: Partial<Record<ShareCardView["status"], string>> = {
  queued: "카드 생성을 기다리고 있습니다. 이 화면에서 상태가 자동으로 갱신됩니다.",
  rendering: "공유 이미지를 만들고 있습니다. 완료되면 공개 링크가 표시됩니다.",
  failed: "카드를 만들지 못했습니다. 다시 시도하거나 공유 요청을 폐기할 수 있습니다.",
  revoked: "이 공개 링크는 폐기되어 더 이상 열리지 않습니다.",
};

function Snapshot({ snapshot }: { snapshot: ShareCardView["snapshot"] }) {
  const labels: Record<string, string> = {
    x: "편향성",
    sensationalism: "과장성",
    confidence: "분석 신뢰도",
    tier: "활동 단계",
    credit_total: "활동 크레딧",
    created_at: "카드 생성 시각",
  };
  const entries = Object.entries(snapshot).filter(([key, value]) => key in labels && ["string", "number"].includes(typeof value));
  if (entries.length === 0) return null;
  return <dl className="admin-item__meta" aria-label="카드에 저장된 공개 정보">{entries.map(([key, value]) => {
    const displayValue = key === "confidence"
      ? `${Math.round(Number(value) * 100)}%`
      : key === "tier"
        ? formatTierLabel(String(value))
        : key === "created_at"
          ? formatPublishedDate(String(value))
          : String(value);
    return <div key={key}><dt>{labels[key]}</dt><dd>{displayValue}</dd></div>;
  })}</dl>;
}

export function ShareCardStatus({ initialCard }: { initialCard: ShareCardView }) {
  const [card, setCard] = useState(initialCard);
  const [toast, setToast] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmRevoke, setConfirmRevoke] = useState(false);
  useEffect(() => {
    if (card.status !== "queued" && card.status !== "rendering") return;
    const timer = window.setInterval(() => {
      void apiRequest<ShareCardView>(`/share-cards/${encodeURIComponent(card.id)}`).then(setCard).catch(() => setError("카드 상태를 갱신하지 못했습니다."));
    }, 2_000);
    return () => window.clearInterval(timer);
  }, [card.id, card.status]);
  const publicPath = card.public_token ? `/share/p/${encodeURIComponent(card.public_token)}` : null;
  const copyPublicLink = async () => {
    if (!publicPath) return;
    const publicUrl = new URL(publicPath, window.location.origin).toString();
    try {
      await navigator.clipboard.writeText(publicUrl);
      setToast("공개 링크를 복사했습니다.");
    } catch { setError("공개 링크를 복사하지 못했습니다."); }
  };
  const revoke = async () => {
    setBusy(true); setError("");
    try { await apiRequest<void>(`/share-cards/${encodeURIComponent(card.id)}`, { method: "DELETE" }); setCard((current) => ({ ...current, status: "revoked", public_token: null })); setConfirmRevoke(false); setToast("공유 카드를 폐기했습니다."); }
    catch { setError("공유 카드를 폐기하지 못했습니다."); }
    finally { setBusy(false); }
  };
  const retry = async () => {
    setBusy(true); setError("");
    try {
      await apiRequest<ShareCardJobAccepted>(`/share-cards/${encodeURIComponent(card.id)}/retry`, { method: "POST" });
      setCard((current) => ({ ...current, status: "queued", etag: null }));
      setToast("공유 카드 생성을 다시 시작했습니다.");
    } catch { setError("공유 카드 생성을 다시 시작하지 못했습니다."); }
    finally { setBusy(false); }
  };
  const tone = card.status === "ready" ? "positive" : card.status === "failed" || card.status === "revoked" ? "danger" : "warning";
  return <>
    <section className="card card--padded share-status-card">
      <div className="issue-card__top"><Badge tone={tone}>{statusLabels[card.status]}</Badge></div>
      {card.status === "queued" || card.status === "rendering" ? <p className="notice" role="status" aria-live="polite">{statusDescriptions[card.status]}</p> : card.status === "failed" ? <><p className="notice" role="alert">{statusDescriptions.failed}</p><div className="page-header__actions"><Button disabled={busy} onClick={retry}><RefreshCw size={16} aria-hidden="true" /> 생성 다시 시도</Button><Button variant="danger" disabled={busy} onClick={() => setConfirmRevoke(true)}><Trash2 size={16} aria-hidden="true" /> 카드 폐기</Button></div></> : card.status === "revoked" ? <p className="notice">{statusDescriptions.revoked}</p> : <><Snapshot snapshot={card.snapshot} /><div className="page-header__actions">{card.public_token && <><ButtonLink variant="secondary" href={publicPath ?? "/"} target="_blank" rel="noreferrer"><ExternalLink size={16} aria-hidden="true" /> 공개 페이지 열기</ButtonLink><Button variant="secondary" onClick={() => void copyPublicLink()}><Copy size={16} aria-hidden="true" /> 공개 링크 복사</Button><ButtonLinkDownload token={card.public_token} /></>}<Button variant="danger" disabled={busy} onClick={() => setConfirmRevoke(true)}><Trash2 size={16} aria-hidden="true" /> 카드 폐기</Button></div></>}
      {confirmRevoke && card.status !== "revoked" ? <div className="notice" role="alert"><div><strong>이 공유 카드를 폐기할까요?</strong><p>폐기하면 현재 공개 링크가 즉시 중단되며 되돌릴 수 없습니다.</p><div className="form-actions"><Button variant="secondary" onClick={() => setConfirmRevoke(false)} disabled={busy}>취소</Button><Button variant="danger" onClick={() => void revoke()} disabled={busy}>{busy ? "폐기 중..." : "폐기 확인"}</Button></div></div></div> : null}
      {error && <p role="alert" style={{ color: "var(--danger)" }}>{error}</p>}
    </section>
    {toast && <Toast message={toast} />}
  </>;
}

function ButtonLinkDownload({ token }: { token: string }) {
  return <a className="button button--primary" href={`/api/v1/public/share/${encodeURIComponent(token)}/image`} download><Download size={16} aria-hidden="true" /> PNG 다운로드</a>;
}
