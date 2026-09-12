"use client";

import { useState } from "react";
import { ApiError } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { ButtonLink } from "@/components/ui/button";
import { Toast } from "@/components/ui/toast";
import { voteSchema, type VoteInput as Vote } from "./model";
import {
  useDeleteVoteMutation,
  useMyVoteQuery,
  useVoteAggregateQuery,
  useVoteMutation,
  useArticleQuery,
} from "@/lib/api/queries";
import { formatBiasScore, formatSensationalismScore } from "@/lib/api/formatters";

type Choice = { value: number; label: string; tone?: "blue" | "red" };

const BIAS_CHOICES: Choice[] = [
  { value: -100, label: "매우 좌편향", tone: "blue" },
  { value: -67, label: "좌편향", tone: "blue" },
  { value: -33, label: "약간 좌편향", tone: "blue" },
  { value: 0, label: "중립" },
  { value: 33, label: "약간 우편향", tone: "red" },
  { value: 67, label: "우편향", tone: "red" },
  { value: 100, label: "매우 우편향", tone: "red" },
];

const SENSATIONALISM_CHOICES: Choice[] = [
  { value: 0, label: "매우 낮음" },
  { value: 17, label: "낮음" },
  { value: 33, label: "약간 낮음" },
  { value: 50, label: "보통" },
  { value: 67, label: "약간 높음" },
  { value: 83, label: "높음" },
  { value: 100, label: "매우 높음" },
];

function ChoiceScale({ legend, value, choices, onChange }: { legend: string; value: number; choices: Choice[]; onChange: (value: number) => void }) {
  return (
    <fieldset className="choice-scale">
      <legend>{legend}</legend>
      <div className="choice-scale__grid">
        {choices.map((choice) => {
          const selected = value === choice.value;
          return (
            <Button
              variant="secondary"
              className="choice-button"
              key={choice.value}
              aria-label={choice.label}
              aria-pressed={selected}
              data-selected={selected ? "" : undefined}
              data-tone={choice.tone}
              onClick={() => onChange(choice.value)}
            >
              <span>{choice.label}</span>
            </Button>
          );
        })}
      </div>
    </fieldset>
  );
}

export function VoteForm({ articleId }: { articleId: string }) {
  const myVote = useMyVoteQuery(articleId);
  const guest = myVote.error instanceof ApiError && myVote.error.status === 401;
  if (guest) {
    return (
      <section className="card card--padded">
        <p className="eyebrow">독자 평가</p><h2>내 관점을 기록해 보세요.</h2>
        <p style={{ color: "var(--muted)" }}>기사와 AI 분석은 로그인 없이 볼 수 있습니다. 평가는 회원 기록이므로 로그인 후 저장할 수 있습니다.</p>
        <ButtonLink href={`/login?returnTo=${encodeURIComponent(`/articles/${articleId}`)}`}>로그인 후 평가하기</ButtonLink>
      </section>
    );
  }
  if (myVote.isPending) {
    return <section className="card card--padded" aria-live="polite">내 독자 평가를 확인하는 중입니다.</section>;
  }
  return <VoteEditor articleId={articleId} initialVote={myVote.data ?? null} />;
}

function VoteEditor({
  articleId,
  initialVote,
}: {
  articleId: string;
  initialVote: Vote | null;
}) {
  const [vote, setVote] = useState<Vote>(
    initialVote ? { x: initialVote.x, y: initialVote.y, z: initialVote.z, sensationalism: initialVote.sensationalism } : { x: 0, y: 0, z: 0, sensationalism: 0 },
  );
  const article = useArticleQuery(articleId);
  const [savedVote, setSavedVote] = useState(initialVote);
  const [hasVote, setHasVote] = useState(initialVote !== null);
  const [message, setMessage] = useState("");
  const [messageTitle, setMessageTitle] = useState("완료");
  const [noticeVersion, setNoticeVersion] = useState(0);
  const aggregate = useVoteAggregateQuery(articleId);
  const saveVote = useVoteMutation(articleId);
  const deleteVote = useDeleteVoteMutation(articleId);
  const busy = saveVote.isPending || deleteVote.isPending;
  const aggregatePending = aggregate.isFetching || aggregate.data?.status === "pending";
  const update = (key: "x" | "sensationalism", value: number) => setVote((current) => ({ ...current, [key]: value }));
  const submit = async () => {
    if (!voteSchema.safeParse(vote).success) return setMessage("각 점수의 허용 범위를 확인해 주세요.");
    try {
      const saved = await saveVote.mutateAsync(vote);
      setHasVote(true);
      setSavedVote(saved);
      setMessageTitle("완료");
      setNoticeVersion((value) => value + 1);
      setMessage(saved.save_status === "updated" || (saved.save_status == null && saved.revision > 1)
        ? "수정사항이 반영되었습니다."
        : "평가가 저장되었습니다. 아래에서 AI 분석과 내 평가를 비교해 보세요.");
    } catch { setMessageTitle("저장 실패"); setNoticeVersion((value) => value + 1); setMessage("독자 평가를 저장하지 못했습니다. 기존 평가는 유지됩니다."); }
  };
  const remove = async () => {
    try {
      await deleteVote.mutateAsync();
      setHasVote(false);
      setSavedVote(null);
      setMessageTitle("완료");
      setNoticeVersion((value) => value + 1);
      setVote({ x: 0, y: 0, z: 0, sensationalism: 0 });
      setMessage("현재 독자 평가를 삭제했습니다. 이전 수정 내용은 이력으로 보존됩니다.");
    } catch { setMessageTitle("삭제 실패"); setNoticeVersion((value) => value + 1); setMessage("독자 평가를 삭제하지 못했습니다. 기존 평가는 유지됩니다."); }
  };
  return (
    <section className="card card--padded">
      <p className="eyebrow">독자 평가</p><h2>이 기사를 어떻게 읽었나요?</h2>
      <ChoiceScale legend="편향성 (좌편향 ↔ 우편향)" value={vote.x} choices={BIAS_CHOICES} onChange={(value) => update("x", value)} />
      <ChoiceScale legend="과장성 (낮음 ↔ 높음)" value={vote.sensationalism} choices={SENSATIONALISM_CHOICES} onChange={(value) => update("sensationalism", value)} />
      <div className="notice">기사의 표현과 관점을 평가해 주세요. 이 평가는 내 정치성향 검사 결과를 바꾸지 않습니다. 독자 평가는 별도로 집계되며 공식 AI 점수를 즉시 교체하지 않습니다.</div>
      <div className="form-actions"><Button variant="ghost" onClick={() => void remove()} disabled={busy || !hasVote}>내 평가 삭제</Button><Button onClick={() => void submit()} disabled={busy}>독자 평가 저장</Button></div>
      {savedVote && <p className="vote-feedback" role="status">저장한 내 평가: 편향성 {formatBiasScore(savedVote.x)}, 과장성 {savedVote.sensationalism}.{article.data?.analysisStatus === "READY" && <> AI 분석: 편향성 {formatBiasScore(article.data.x)}, 과장성 {formatSensationalismScore(article.data.sensationalism)}.</>}</p>}
      <div className="reader-aggregate" aria-live="polite">
        <strong>독자 평가 집계</strong>
        {aggregatePending && <p>집계 반영 중입니다. 표시된 수치가 있으면 최근 집계 기준입니다.</p>}
        {aggregate.data?.qualified_count && !aggregate.data.small_segments_suppressed ? (
          <p>편향성 {aggregate.data.qualified.x === null ? "미측정" : formatBiasScore(aggregate.data.qualified.x)}, 과장성 {formatSensationalismScore(aggregate.data.qualified.sensationalism)}</p>
        ) : !aggregatePending && !aggregate.isError ? <p>{aggregate.data?.qualified_count ? `독자 평균 공개까지 ${Math.max(0, 5 - (aggregate.data?.qualified_count ?? 0))}명의 평가가 더 필요합니다.` : "독자 평균은 5명부터 공개됩니다. 내 평가는 위에서 바로 확인할 수 있습니다."}</p> : null}
        {aggregate.isError && <p>독자 집계 기준을 불러오지 못했습니다.</p>}
        {aggregate.data?.small_segments_suppressed && <small>작은 집단의 세부 결과는 공개하지 않습니다.</small>}
      </div>
      {message && <Toast key={noticeVersion} message={message} title={messageTitle} />}
    </section>
  );
}
