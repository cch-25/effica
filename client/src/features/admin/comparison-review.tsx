"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest, ApiError, createIdempotencyKey } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/schema";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { TextareaField } from "@/components/ui/form-controls";
import { useIssueArticlesQuery } from "@/lib/api/queries";

type Preview = components["schemas"]["IssueComparisonReviewPreview"];

export function ComparisonReview({ issueId, title, canApprove }: { issueId: string; title: string; canApprove: boolean }) {
  const [open, setOpen] = useState(false);
  return <><Button variant="secondary" onClick={() => setOpen(true)}>비교 분석 검토</Button><Dialog open={open} onClose={() => setOpen(false)} title={title} description="원문과 공통 사실, 기사별 관점을 확인한 후 공개를 승인하세요.">{open && <ReviewContent issueId={issueId} canApprove={canApprove} />}</Dialog></>;
}

function ReviewContent({ issueId, canApprove }: { issueId: string; canApprove: boolean }) {
  const cache = useQueryClient();
  const query = useQuery({ queryKey: ["admin", "comparison", issueId], queryFn: () => apiRequest<Preview>(`/admin/issues/${issueId}/comparison`), retry: false });
  const articles = useIssueArticlesQuery(issueId);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [stale, setStale] = useState(false);
  const [editing, setEditing] = useState(false);
  const [excluded, setExcluded] = useState<string[]>([]);
  const snapshot = query.data;
  const approve = async () => {
    if (!snapshot || !reason.trim()) return;
    setBusy(true); setMessage("");
    try {
      await apiRequest(`/admin/issues/${issueId}/comparison`, { method: "POST", headers: { "If-Match": snapshot.snapshot_id, "Idempotency-Key": createIdempotencyKey() }, body: JSON.stringify({ reason: reason.trim(), excluded_fact_ids: excluded }) });
      await query.refetch();
      await cache.invalidateQueries({ queryKey: ["issue", issueId] });
      setEditing(false);
      setMessage("비교 분석을 공개했습니다.");
    } catch (error) {
      const conflict = error instanceof ApiError && [409, 412, 428].includes(error.status);
      setStale(conflict);
      setMessage(conflict ? "검토 중 분석이 변경되었습니다. 최신 내용을 다시 확인해 주세요." : error instanceof Error ? error.message : "승인하지 못했습니다.");
    } finally { setBusy(false); }
  };
  if (query.isPending) return <p role="status">분석을 불러오는 중입니다.</p>;
  if (query.isError) return <div role="status"><p>{query.error instanceof ApiError && query.error.status === 404 ? "아직 검토할 비교 분석이 없습니다." : "비교 분석을 불러오지 못했습니다."}</p><Button onClick={() => void query.refetch()}>다시 불러오기</Button></div>;
  if (!snapshot) return null;
  const reviewing = !snapshot.reviewed_at || editing;
  const titleFor = (id: string) => articles.data?.items.find((article) => article.id === id);
  return <div className="comparison-review">
    <p>{snapshot.reviewed_at ? "공개 승인됨" : "승인 대기"} / 생성 상태 {snapshot.status}</p>
    {snapshot.reviewed_at && canApprove && !editing && <Button variant="secondary" onClick={() => { setEditing(true); setExcluded([]); setReason(""); setMessage(""); }}>공개 항목 다시 검토</Button>}
    <h3>공통 사실과 근거 기사</h3>
    {reviewing && canApprove && <p>두 기사 이상에서 확인되지 않는 항목은 공개에서 제외하세요. 생성 원본과 제외 사유는 보존됩니다.</p>}
    <ul>{snapshot.common_facts.map((fact) => <li key={fact.id}><p>{fact.text}</p>{fact.article_ids.map((id) => <p key={id}><Link href={`/articles/${id}`} target="_blank">{titleFor(id)?.source ?? id}: {titleFor(id)?.title ?? "기사 분석"}</Link></p>)}<small>{fact.evidence_refs?.join(" / ")}</small>{reviewing && canApprove && <label className="review-exclusion"><input type="checkbox" checked={excluded.includes(fact.id)} onChange={(event) => setExcluded((current) => event.target.checked ? [...current, fact.id] : current.filter((id) => id !== fact.id))} />이 항목은 공개에서 제외</label>}</li>)}</ul>
    <h3>분석 차원</h3><p>{snapshot.dimensions.map((dimension) => dimension.label).join(" / ")}</p>
    {Object.entries(snapshot.article_frames).map(([id, frame]) => <section key={id}><h3>{titleFor(id)?.source ?? id}</h3><Link href={`/articles/${id}`} target="_blank">{titleFor(id)?.title ?? "기사 분석 열기"}</Link>{titleFor(id)?.originalUrl && <p><a href={titleFor(id)!.originalUrl} target="_blank" rel="noreferrer">언론사 원문 확인</a></p>}<p>{frame.headline_frame}</p><p>{frame.emphasis?.join(" / ")}</p><p>{frame.omissions_note}</p><small>{frame.evidence_refs?.join(" / ")}</small></section>)}
    <p>분석 신뢰도 {Math.round(snapshot.confidence * 100)}%</p>
    {reviewing && canApprove && <><TextareaField id={`review-reason-${issueId}`} label="검토 및 승인 사유" value={reason} onChange={(event) => setReason(event.target.value)} /><Button disabled={busy || stale || !reason.trim() || snapshot.status !== "SUCCEEDED"} onClick={() => void approve()}>{busy ? "승인 중" : "검토 완료 및 공개 승인"}</Button></>}
    {!canApprove && <p>공개 승인에는 관리자 권한이 필요합니다.</p>}
    {stale && <Button onClick={async () => { await query.refetch(); setStale(false); setReason(""); setExcluded([]); setMessage(""); }}>최신 분석 다시 검토</Button>}
    {message && <p role="status">{message}</p>}
    {snapshot.reviewed_at && <Link href={`/issues/${issueId}`} target="_blank">공개 비교 화면 확인</Link>}
  </div>;
}
