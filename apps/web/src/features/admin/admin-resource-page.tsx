"use client";

import { Filter, LockKeyhole, MoreHorizontal, RefreshCcw, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { Role } from "@/lib/api/types";
import { adminConfigs, type AdminAction } from "./config";
import { canPerform } from "@/lib/auth/permissions";
import { ApiError, apiRequest, createIdempotencyKey } from "@/lib/api/client";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Dialog } from "@/components/ui/dialog";
import { StatePanel } from "@/components/ui/state-panel";
import { Toast } from "@/components/ui/toast";
import { TextField, TextareaField } from "@/components/ui/form-controls";

type PageResponse = { items: Array<Record<string, unknown>>; next_cursor?: string | null };
type Pending = { action: AdminAction; item: Record<string, unknown>; key: string };

function itemId(item: Record<string, unknown>): string { return String(item.id ?? item.job_id ?? item.recommendation_id ?? "unknown"); }
function itemTitle(item: Record<string, unknown>): string { return String(item.title ?? item.name ?? item.action ?? item.job_type ?? itemId(item)); }
function itemStatus(item: Record<string, unknown>): string { return String(item.status ?? item.state ?? "UNKNOWN"); }
function primitiveMetadata(item: Record<string, unknown>) { return Object.entries(item).filter(([key, value]) => !["id", "title", "name", "status", "state"].includes(key) && ["string", "number", "boolean"].includes(typeof value)).slice(0, 4); }

export function AdminResourcePage({ configKey, role }: { configKey: string; role: Role }) {
  const config = adminConfigs[configKey];
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["admin", config.listPath], queryFn: async () => {
    const response = await apiRequest<unknown>(config.listPath);
    if (Array.isArray(response)) return { items: response as Array<Record<string, unknown>> } satisfies PageResponse;
    if (response && typeof response === "object" && "items" in response && Array.isArray((response as PageResponse).items)) return response as PageResponse;
    return { items: response && typeof response === "object" ? [response as Record<string, unknown>] : [] } satisfies PageResponse;
  } });
  const [pending, setPending] = useState<Pending | null>(null);
  const [reason, setReason] = useState("");
  const [valuesText, setValuesText] = useState("{}");
  const [toast, setToast] = useState("");
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState(false);
  const items = useMemo(() => (query.data?.items ?? []).filter((item) => JSON.stringify(item).toLowerCase().includes(search.toLowerCase())), [query.data?.items, search]);
  const open = (action: AdminAction, item: Record<string, unknown>) => { setReason(""); setError(""); setConflict(false); setValuesText(JSON.stringify(action.defaultValues ?? {}, null, 2)); setPending({ action, item, key: createIdempotencyKey() }); };
  const confirm = async () => {
    if (!pending || !reason.trim()) return;
    let values: Record<string, unknown>;
    try { values = JSON.parse(valuesText) as Record<string, unknown>; }
    catch { setError("변경 값은 올바른 JSON 객체여야 합니다."); return; }
    setBusy(true); setError(""); setConflict(false);
    try {
      const headers = new Headers({ "Idempotency-Key": createIdempotencyKey() });
      if (pending.action.ifMatch) {
        const versionSource = pending.action.ifMatchPath ? await apiRequest<Record<string, unknown>>(pending.action.ifMatchPath) : pending.item;
        headers.set("If-Match", String(versionSource.etag ?? versionSource.version ?? versionSource.revision ?? ""));
      }
      await apiRequest(pending.action.path(itemId(pending.item)), { method: pending.action.method, headers, body: JSON.stringify(pending.action.body(reason, values)) });
      await queryClient.invalidateQueries({ queryKey: ["admin", config.listPath] });
      setToast(`${pending.action.label} 요청이 서버에 반영되었습니다. Key ${pending.key.slice(0, 8)}…`);
      setPending(null);
    } catch (requestError) {
      if (requestError instanceof ApiError && (requestError.status === 409 || requestError.status === 428)) setConflict(true);
      setError(requestError instanceof Error ? requestError.message : "관리자 요청을 처리하지 못했습니다.");
    } finally { setBusy(false); }
  };

  return <>
    <PageHeader eyebrow={config.eyebrow} title={config.title} description={config.description} actions={<><Badge tone="info">role: {role}</Badge><Button variant="secondary" onClick={() => void query.refetch()}><RefreshCcw size={16} /> 새로고침</Button></>} />
    <div className="admin-toolbar"><div className="admin-toolbar__filters"><div className="search-field"><Search size={14} aria-hidden="true" /><TextField label="검색" className="field--search" placeholder="이름·ID 검색" value={search} onChange={(event) => setSearch(event.target.value)} /></div><Button variant="secondary" disabled><Filter size={16} /> 서버 상태</Button></div></div>
    {query.isPending ? <StatePanel state="loading" /> : query.isError ? <StatePanel state="error" onRetry={() => void query.refetch()} /> : items.length === 0 ? <StatePanel state="empty" /> : <section className="card">{items.map((item) => <article className="admin-item" key={itemId(item)}><div><div className="news-card__meta"><Badge tone={itemStatus(item).includes("FAIL") || itemStatus(item) === "BLOCKED" ? "danger" : itemStatus(item).includes("ACTIVE") || itemStatus(item).includes("SUCCESS") ? "positive" : "warning"}>{itemStatus(item)}</Badge><span>{itemId(item)}</span></div><h3>{itemTitle(item)}</h3></div><div className="admin-item__meta">{primitiveMetadata(item).map(([label, value]) => <div key={label}><small>{label}</small><strong>{String(value)}</strong></div>)}</div><div className="admin-item__actions">{config.actions.map((action) => <Button key={action.label} variant={action.destructive ? "danger" : "secondary"} disabled={!canPerform(role, action.level)} title={!canPerform(role, action.level) ? `${action.level} 권한이 필요합니다` : undefined} onClick={() => open(action, item)}>{!canPerform(role, action.level) && <LockKeyhole size={14} />}{action.label}</Button>)}{config.actions.length === 0 && <Button variant="ghost" aria-label={`${itemTitle(item)} 상세`} disabled><MoreHorizontal size={17} /></Button>}</div></article>)}</section>}
    <Dialog open={pending !== null} onClose={() => setPending(null)} title={`${pending?.action.label ?? "변경"} 확인`}><p>대상 <strong>{pending ? itemId(pending.item) : ""}</strong>에 서버 변경을 적용합니다.</p><code style={{ display: "block", overflowWrap: "anywhere" }}>{pending?.key}</code>{pending?.action.needsValues && <TextareaField id="admin-values" className="field--spaced" label="변경 값 (JSON)" value={valuesText} onChange={(event) => setValuesText(event.target.value)} />}<TextareaField id="admin-reason" className="field--spaced" label="변경 사유 (필수)" value={reason} onChange={(event) => setReason(event.target.value)} />{conflict && <StatePanel state="conflict" onRetry={() => void query.refetch()} />}{error && <p role="alert" style={{ color: "var(--danger)" }}>{error}</p>}<div className="form-actions"><Button variant="secondary" onClick={() => setPending(null)}>취소</Button><Button variant={pending?.action.destructive ? "danger" : "primary"} disabled={!reason.trim() || busy} onClick={confirm}>{busy ? "실행 중…" : "사유와 함께 실행"}</Button></div></Dialog>
    {toast && <Toast message={toast} />}
  </>;
}
