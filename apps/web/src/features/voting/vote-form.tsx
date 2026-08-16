"use client";

import { useState } from "react";
import { apiRequest } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Toast } from "@/components/ui/toast";
import { voteSchema, type VoteInput as Vote } from "./model";

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
          const displayedValue = choice.value > 0 ? `+${choice.value}` : String(choice.value);
          return (
            <Button
              variant="secondary"
              className="choice-button"
              key={choice.value}
              aria-label={`${choice.label} ${displayedValue}`}
              aria-pressed={selected}
              data-selected={selected ? "" : undefined}
              data-tone={choice.tone}
              onClick={() => onChange(choice.value)}
            >
              <span>{choice.label}</span>
              <small>{displayedValue}</small>
            </Button>
          );
        })}
      </div>
    </fieldset>
  );
}

export function VoteForm({ articleId }: { articleId: string }) {
  const [vote, setVote] = useState<Vote>({ x: 0, y: 0, z: 0, sensationalism: 0 });
  const [message, setMessage] = useState("");
  const update = (key: "x" | "sensationalism", value: number) => setVote((current) => ({ ...current, [key]: value }));
  const submit = async () => {
    if (!voteSchema.safeParse(vote).success) return setMessage("각 점수의 허용 범위를 확인해 주세요.");
    await apiRequest(`/articles/${articleId}/vote`, { method: "PUT", body: JSON.stringify(vote) });
    setMessage("투표 revision 2가 저장되었습니다.");
  };
  const remove = async () => { setVote({ x: 0, y: 0, z: 0, sensationalism: 0 }); setMessage("활성 투표가 삭제되었습니다. 이전 revision은 이력으로 보존됩니다."); };
  return (
    <section className="card card--padded">
      <p className="eyebrow">독자 평가</p><h2>이 기사를 어떻게 읽었나요?</h2>
      <ChoiceScale legend="편향성 (좌편향 ↔ 우편향)" value={vote.x} choices={BIAS_CHOICES} onChange={(value) => update("x", value)} />
      <ChoiceScale legend="과장성 (낮음 ↔ 높음)" value={vote.sensationalism} choices={SENSATIONALISM_CHOICES} onChange={(value) => update("sensationalism", value)} />
      <div className="notice">독자 투표는 집계 구성요소 중 하나이며 공식 점수를 즉시 교체하지 않습니다.</div>
      <div className="form-actions"><Button variant="ghost" onClick={remove}>내 투표 삭제</Button><Button onClick={submit}>투표 저장·수정</Button></div>
      {message && <Toast message={message} />}
    </section>
  );
}
