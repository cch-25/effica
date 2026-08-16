"use client";

import { Filter, LockKeyhole, MoreHorizontal, RefreshCcw, Search } from "lucide-react";
import { useRef, useState } from "react";
import type { Role } from "@/lib/api/types";
import type { AdminAction, AdminConfig } from "./config";
import { canPerform } from "@/lib/auth/permissions";
import { createIdempotencyKey } from "@/lib/api/client";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Dialog } from "@/components/ui/dialog";
import { StatePanel } from "@/components/ui/state-panel";
import { Toast } from "@/components/ui/toast";

export function AdminResourcePage({ config, role }: { config: AdminConfig; role: Role }) {
  const [pending, setPending] = useState<{ action: AdminAction; itemId: string; key: string } | null>(null);
  const [reason, setReason] = useState(""); const [toast, setToast] = useState(""); const [conflict, setConflict] = useState(false); const conflictSeen = useRef(false);
  const open = (action: AdminAction, itemId: string) => { setReason(""); setConflict(false); setPending({ action, itemId, key: createIdempotencyKey() }); };
  const confirm = () => {
    if (!pending || !reason.trim()) return;
    if (pending.action.conflict && !conflictSeen.current) { conflictSeen.current = true; setConflict(true); return; }
    setToast(`${pending.action.label} 요청이 접수되었습니다. Key ${pending.key.slice(0,8)}…`); setPending(null);
  };
  return <><PageHeader eyebrow={config.eyebrow} title={config.title} description={config.description} actions={<><Badge tone="info">role: {role}</Badge><Button variant="secondary"><RefreshCcw size={16} /> 새로고침</Button></>} />
    <div className="admin-toolbar"><div className="admin-toolbar__filters"><label className="field" style={{ margin: 0 }}><span className="eyebrow" style={{ position: "absolute", clipPath: "inset(50%)" }}>검색</span><div style={{ position: "relative" }}><Search size={16} style={{ position: "absolute", left: 12, top: 13 }} /><input className="input" placeholder="이름·ID 검색" style={{ paddingLeft: 36 }} /></div></label><Button variant="secondary"><Filter size={16} /> 상태 필터</Button></div></div>
    <section className="card">{config.items.map((item) => <article className="admin-item" key={item.id}><div><div className="news-card__meta"><Badge tone={item.status.includes("FAIL") || item.status === "BLOCKED" ? "danger" : item.status.includes("ACTIVE") || item.status.includes("SUCCESS") || item.status === "HEALTHY" ? "positive" : "warning"}>{item.status}</Badge><span>{item.id}</span></div><h3>{item.title}</h3><p>{item.subtitle}</p></div><div className="admin-item__meta">{item.metadata.map((entry) => <div key={entry.label}><small>{entry.label}</small><strong>{entry.value}</strong></div>)}</div><div className="admin-item__actions">{config.actions.map((action) => <Button key={action.label} variant={action.destructive ? "danger" : "secondary"} disabled={!canPerform(role, action.level)} title={!canPerform(role, action.level) ? `${action.level} 권한이 필요합니다` : undefined} onClick={() => open(action, item.id)}>{!canPerform(role, action.level) && <LockKeyhole size={14} />}{action.label}</Button>)}{config.actions.length === 0 && <Button variant="ghost" aria-label={`${item.title} 상세`}><MoreHorizontal size={17} /></Button>}</div></article>)}</section>
    <Dialog open={pending !== null} onClose={() => setPending(null)} title={`${pending?.action.label ?? "변경"} 확인`}><p>대상 <strong>{pending?.itemId}</strong>에 변경을 적용합니다. 동일 사용자 동작 동안 아래 Idempotency-Key를 재사용합니다.</p><code style={{ display: "block", overflowWrap: "anywhere" }}>{pending?.key}</code>{conflict && <div style={{ marginTop: "1rem" }}><StatePanel state="conflict" /><Button variant="secondary" style={{ marginTop: ".7rem" }} onClick={() => setConflict(false)}>최신 데이터 불러와 재검토</Button></div>}<div className="field" style={{ marginTop: "1rem" }}><label htmlFor="admin-reason">변경 사유 (필수)</label><textarea id="admin-reason" className="textarea" value={reason} onChange={(event) => setReason(event.target.value)} /></div><div className="form-actions"><Button variant="secondary" onClick={() => setPending(null)}>취소</Button><Button variant={pending?.action.destructive ? "danger" : "primary"} disabled={!reason.trim() || conflict} onClick={confirm}>사유와 함께 실행</Button></div></Dialog>{toast && <Toast message={toast} />}</>;
}
