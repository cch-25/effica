"use client";

import { useState } from "react";
import { apiRequest } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Toast } from "@/components/ui/toast";
import { AXIS_META } from "@/lib/api/formatters";
import { voteSchema, type VoteInput as Vote } from "./model";

export function VoteForm({ articleId }: { articleId: string }) {
  const [vote, setVote] = useState<Vote>({ x: 0, y: 0, z: 0, sensationalism: 0 });
  const [message, setMessage] = useState("");
  const update = (key: keyof Vote, value: number) => setVote({ ...vote, [key]: value });
  const submit = async () => {
    if (!voteSchema.safeParse(vote).success) return setMessage("각 점수의 허용 범위를 확인해 주세요.");
    await apiRequest(`/articles/${articleId}/vote`, { method: "PUT", body: JSON.stringify(vote) });
    setMessage("투표 revision 2가 저장되었습니다.");
  };
  const remove = async () => { setVote({ x: 0, y: 0, z: 0, sensationalism: 0 }); setMessage("활성 투표가 삭제되었습니다. 이전 revision은 이력으로 보존됩니다."); };
  return (
    <section className="card card--padded">
      <p className="eyebrow">Your assessment</p><h2>이 기사를 어떻게 읽었나요?</h2>
      {(Object.keys(AXIS_META) as Array<keyof typeof AXIS_META>).map((key) => <div className="slider-field" key={key}><label htmlFor={`vote-${key}`}>{AXIS_META[key].short} <small>({AXIS_META[key].negative} ↔ {AXIS_META[key].positive})</small></label><input id={`vote-${key}`} type="range" min="-100" max="100" value={vote[key]} onChange={(event) => update(key, Number(event.target.value))} /><input aria-label={`${AXIS_META[key].short} 숫자 입력`} type="number" min="-100" max="100" value={vote[key]} onChange={(event) => update(key, Number(event.target.value))} /></div>)}
      <div className="slider-field"><label htmlFor="vote-sensationalism">과장성 <small>(낮음 0 ↔ 높음 100)</small></label><input id="vote-sensationalism" type="range" min="0" max="100" value={vote.sensationalism} onChange={(event) => update("sensationalism", Number(event.target.value))} /><input aria-label="과장성 숫자 입력" type="number" min="0" max="100" value={vote.sensationalism} onChange={(event) => update("sensationalism", Number(event.target.value))} /></div>
      <div className="notice">독자 투표는 집계 구성요소 중 하나이며 공식 점수를 즉시 교체하지 않습니다.</div>
      <div className="form-actions"><Button variant="ghost" onClick={remove}>내 투표 삭제</Button><Button onClick={submit}>투표 저장·수정</Button></div>
      {message && <Toast message={message} />}
    </section>
  );
}
