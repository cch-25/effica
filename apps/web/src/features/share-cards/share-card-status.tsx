"use client";

import { Download, Share2, Trash2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { StatePanel } from "@/components/ui/state-panel";
import { Toast } from "@/components/ui/toast";
import type { ShareCardStatus as Status } from "./model";

export function ShareCardStatus({ initialStatus = "ready" }: { initialStatus?: Status }) {
  const [status, setStatus] = useState<Status>(initialStatus); const [toast, setToast] = useState("");
  const share = async () => { if (navigator.share) await navigator.share({ title: "나의 관점 카드", url: location.href }); else { await navigator.clipboard.writeText(location.href); setToast("공개 링크를 복사했습니다."); } };
  return <><section className="card card--padded"><div className="issue-card__top"><Badge tone={status === "ready" ? "positive" : status === "failed" || status === "revoked" ? "danger" : "warning"}>{status}</Badge><span>card-01</span></div>{status === "queued" || status === "rendering" ? <StatePanel state="processing" /> : status === "failed" ? <StatePanel state="error" /> : status === "revoked" ? <StatePanel state="unauthorized" /> : <><div className="share-preview" style={{ maxWidth: 560, margin: "1.5rem auto" }}><p>MY PERSPECTIVE / 2026</p><h2>김사이</h2><div className="share-preview__orbit"><span /><span /><span /></div><dl><div><dt>경제</dt><dd>+4</dd></div><div><dt>사회문화</dt><dd>+18</dd></div><div><dt>국가·대외</dt><dd>−12</dd></div></dl><small>현재 응답 결과 · confidence 68% · 탐색가 tier</small></div><div className="page-header__actions"><Button onClick={() => setToast("PNG 다운로드를 시작했습니다.")}><Download size={16} /> PNG 다운로드</Button><Button variant="secondary" onClick={share}><Share2 size={16} /> 공유</Button><Button variant="danger" onClick={() => setStatus("revoked")}><Trash2 size={16} /> 즉시 폐기</Button></div></>}</section>{toast && <Toast message={toast} />}</>;
}
