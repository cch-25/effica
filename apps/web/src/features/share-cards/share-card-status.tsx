"use client";

import { Download, Share2, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { apiRequest } from "@/lib/api/client";
import type { ShareCardView } from "@/lib/api/contracts";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { StatePanel } from "@/components/ui/state-panel";
import { Toast } from "@/components/ui/toast";

const statusLabels: Record<ShareCardView["status"], string> = { queued: "생성 대기", rendering: "생성 중", ready: "생성 완료", failed: "생성 실패", revoked: "폐기됨" };

function Snapshot({ snapshot }: { snapshot: ShareCardView["snapshot"] }) {
  const entries = Object.entries(snapshot).filter(([, value]) => ["string", "number", "boolean"].includes(typeof value));
  if (entries.length === 0) return null;
  return <dl className="admin-item__meta" aria-label="공유 카드 스냅샷">{entries.map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>)}</dl>;
}

export function ShareCardStatus({ initialCard }: { initialCard: ShareCardView }) {
  const [card, setCard] = useState(initialCard);
  const [toast, setToast] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (card.status !== "queued" && card.status !== "rendering") return;
    const timer = window.setInterval(() => {
      void apiRequest<ShareCardView>(`/share-cards/${encodeURIComponent(card.id)}`).then(setCard).catch(() => setError("카드 상태를 갱신하지 못했습니다."));
    }, 2_000);
    return () => window.clearInterval(timer);
  }, [card.id, card.status]);
  const publicPath = card.public_token ? `/share/p/${encodeURIComponent(card.public_token)}` : null;
  const share = async () => {
    if (!publicPath) return;
    const publicUrl = new URL(publicPath, window.location.origin).toString();
    if (navigator.share) await navigator.share({ title: "나의 관점 카드", url: publicUrl });
    else { await navigator.clipboard.writeText(publicUrl); setToast("공개 링크를 복사했습니다."); }
  };
  const revoke = async () => {
    setBusy(true); setError("");
    try { await apiRequest<void>(`/share-cards/${encodeURIComponent(card.id)}`, { method: "DELETE" }); setCard((current) => ({ ...current, status: "revoked", public_token: null })); setToast("공유 카드를 폐기했습니다."); }
    catch { setError("공유 카드를 폐기하지 못했습니다."); }
    finally { setBusy(false); }
  };
  const tone = card.status === "ready" ? "positive" : card.status === "failed" || card.status === "revoked" ? "danger" : "warning";
  return <>
    <section className="card card--padded">
      <div className="issue-card__top"><Badge tone={tone}>{statusLabels[card.status]}</Badge><span>{card.id}</span></div>
      {card.status === "queued" || card.status === "rendering" ? <StatePanel state="processing" /> : card.status === "failed" ? <StatePanel state="error" /> : card.status === "revoked" ? <StatePanel state="unauthorized" /> : <><Snapshot snapshot={card.snapshot} /><div className="page-header__actions">{card.public_token && <><ButtonLinkDownload token={card.public_token} /><Button variant="secondary" onClick={share}><Share2 size={16} /> 공유</Button></>}<Button variant="danger" disabled={busy} onClick={revoke}><Trash2 size={16} /> 즉시 폐기</Button></div></>}
      {error && <p role="alert" style={{ color: "var(--danger)" }}>{error}</p>}
    </section>
    {toast && <Toast message={toast} />}
  </>;
}

function ButtonLinkDownload({ token }: { token: string }) {
  return <a className="button button--primary" href={`/api/v1/public/share/${encodeURIComponent(token)}/image`} download><Download size={16} /> PNG 다운로드</a>;
}
