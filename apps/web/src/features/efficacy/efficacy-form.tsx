"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Toast } from "@/components/ui/toast";
import { Slider } from "@/components/ui/slider";

export function EfficacyForm() {
  const [answer, setAnswer] = useState(3); const [saved, setSaved] = useState(false);
  return <section className="card card--padded"><p className="eyebrow">Follow-up · efficacy-v2</p><h2>정치와 정책 이슈를 이해할 수 있다는 자신감이 어느 정도인가요?</h2><Slider id="efficacy" label="전혀 그렇지 않다 1 — 매우 그렇다 5" min={1} max={5} value={answer} onChange={setAnswer} /><Button onClick={() => setSaved(true)}>후속 설문 저장</Button>{saved && <Toast message={`정규화 점수 ${answer * 20}점이 저장되었습니다.`} />}</section>;
}
