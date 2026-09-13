"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { INITIAL_STATE, rankingExample, weightedScore, type AlgorithmMode } from "./algo-model";
import type { createAlgorithmScene } from "./algo-scene";
import styles from "./algo-infographic.module.css";

const CHAPTERS = [
  { id: "fetch", name: "원문 수집", title: "주소 5개. 원문은 몇 개?", subtitle: "언론사에 직접 요청한 뒤, 허용 출처와 충분한 본문만 통과시킵니다." },
  { id: "evidence", name: "근거 추출", title: "이름을 가리고, 문장을 남깁니다.", subtitle: "판단에 사용한 문장을 원문 속 정확한 위치와 연결합니다." },
  { id: "weights", name: "점수 합산", title: "네 신호를 하나의 관점으로.", subtitle: "입력에 비중을 곱하고 더하면, 최종 관점 좌표가 됩니다." },
  { id: "coordinates", name: "좌표 생성", title: "세 값이 한 점이 됩니다.", subtitle: "가로는 관점, 높이는 선정성, 깊이는 분석 신뢰도입니다." },
  { id: "ranking", name: "추천 배열", title: "높은 점수 다음에는, 다른 시각.", subtitle: "한 기사를 고를 때마다 반복을 계산하고 다음 순서를 바꿉니다." },
] as const;

export function AlgoInfographic() {
  const [state, setState] = useState(INITIAL_STATE);
  const [status, setStatus] = useState<"loading" | "ready" | "fallback">("loading");
  const [rotating, setRotating] = useState(false);
  const host = useRef<HTMLDivElement>(null);
  const runtime = useRef<ReturnType<typeof createAlgorithmScene> | null>(null);
  const latest = useRef(state);
  const active = CHAPTERS.findIndex(chapter => chapter.id === state.mode);
  const chapter = CHAPTERS[active];
  const changeMode = (mode: AlgorithmMode) => { setState(current => ({ ...current, mode, step: 0 })); setRotating(false); runtime.current?.setInteractive(false); };
  useEffect(() => { latest.current = state; runtime.current?.update(state); }, [state]);
  useEffect(() => {
    const node = host.current;
    if (!node) return;
    let cancelled = false;
    const lost = (event: Event) => { event.preventDefault(); setStatus("fallback"); };
    node.addEventListener("webglcontextlost", lost, true);
    void import("./algo-scene").then(({ createAlgorithmScene }) => {
      if (cancelled) return;
      runtime.current = createAlgorithmScene(node, latest.current);
      setStatus("ready");
    }).catch(() => { if (!cancelled) setStatus("fallback"); });
    return () => { cancelled = true; node.removeEventListener("webglcontextlost", lost, true); runtime.current?.dispose(); runtime.current = null; };
  }, []);

  const result = state.mode === "fetch" ? ["5개 주소 발견", "허용 출처 4곳", "본문 검증 통과 3편", "독립 매체 3곳 → 이슈 구성"][state.step]
    : state.mode === "evidence" ? ["원문 입력", "매체와 기자 정보 가림", "근거 24자 → [21, 45)"][state.step]
    : state.mode === "weights" ? `x = ${weightedScore(state.model)}`
    : state.mode === "coordinates" ? `x ${state.x} / s ${state.s} / C ${(state.c / 100).toFixed(2)}`
    : `${rankingExample(state.diverse).selected.map(item => item.id).join(" → ")}${state.diverse ? " / C 제외" : ""}`;
  return <article className={styles.page}>
    <header className={styles.heading}><div><p>EFFICA / INSIDE THE ALGORITHM</p><h1>뉴스가 비교가 되는 과정</h1></div><span>직접 움직여 이해하는 알고리즘</span></header>
    <nav className={styles.chapters} aria-label="알고리즘 단계">
      {CHAPTERS.map((item, i) => <Button key={item.id} variant="ghost" aria-pressed={item.id === state.mode} onClick={() => changeMode(item.id)}><span>0{i + 1}</span>{item.name}</Button>)}
    </nav>
    <section className={styles.experiment} aria-labelledby="experiment-title">
      <header className={styles.experimentHeading}><div><h2 id="experiment-title">{chapter.title}</h2><p>{chapter.subtitle}</p></div><span className={styles.demoLabel}>설명용 가상 데이터</span></header>
      <div className={styles.stage}>
        <div ref={host} className={styles.canvas} role="img" aria-label={`${chapter.title} ${result}`} data-status={status} />
        {status !== "ready" && <div className={styles.fallback}><strong>{status === "loading" ? "3D 계산 장면 준비 중" : "이 환경에서는 3D를 표시할 수 없습니다."}</strong><p>{result}</p></div>}
        <div className={styles.stageTools}><span>THREE.JS / {state.mode.toUpperCase()}</span><div><Button variant="ghost" disabled={status !== "ready"} aria-pressed={rotating} onClick={() => { runtime.current?.setInteractive(!rotating); setRotating(!rotating); }}>회전 {rotating ? "켜짐" : "꺼짐"}</Button><Button variant="ghost" disabled={status !== "ready"} onClick={() => runtime.current?.resetView()}>시점 초기화</Button></div></div>
      </div>
      <div className={styles.console}>
        <div className={styles.action}>
          {state.mode === "fetch" && <Button onClick={() => setState(current => ({ ...current, step: (current.step + 1) % 4 }))}>{["출처 확인", "원문 요청 + 검증", "이슈로 묶기", "다시 수집하기"][state.step]}<span aria-hidden="true">→</span></Button>}
          {state.mode === "evidence" && <Button onClick={() => setState(current => ({ ...current, step: (current.step + 1) % 3 }))}>{["출처 가리기", "근거 추출하기", "원문으로 되돌리기"][state.step]}<span aria-hidden="true">→</span></Button>}
          {state.mode === "weights" && <Range label="모델 판단" min={-100} max={100} value={state.model} change={model => setState(current => ({ ...current, model }))} />}
          {state.mode === "coordinates" && <div className={styles.coordinateInputs}><Range label="관점 x" min={-100} max={100} value={state.x} change={x => setState(current => ({ ...current, x }))} /><Range label="선정성 s" min={0} max={100} value={state.s} change={s => setState(current => ({ ...current, s }))} /><Range label="신뢰도 C (%)" min={0} max={100} value={state.c} change={c => setState(current => ({ ...current, c }))} /></div>}
          {state.mode === "ranking" && <Button aria-pressed={state.diverse} onClick={() => setState(current => ({ ...current, diverse: !current.diverse }))}>다양성 제약 {state.diverse ? "켜짐" : "꺼짐"}<span aria-hidden="true">↔</span></Button>}
        </div>
        <output className={styles.readout} aria-live="polite">{result}</output>
      </div>
      <div className={styles.caption}><p>{state.mode === "fetch" ? ["검색 요약은 주소를 찾는 힌트입니다. 아직 기사 본문이 아닙니다.", "미승인 출처는 요청 전에 멈춥니다.", "HTTP 응답에서 본문을 추출합니다. 84자 응답은 본문 200자 기준에서 탈락합니다.", "같은 논쟁을 다룬 원문 3편. 중복 매체 없이 비교를 구성합니다."][state.step]
        : state.mode === "evidence" ? "문장은 가상 예시입니다. 근거 범위 [21, 45)는 실제 예시 글자 수로 계산합니다."
        : state.mode === "weights" ? "설명용 비중: 모델 60%, 상대 프레임 20%, 독자 평가 15%, 출처 사전값 5%."
        : state.mode === "coordinates" ? "각 축을 바꿔 보세요. 점과 바닥 투영이 해당 수치로 이동합니다."
        : state.diverse ? "A 다음에 같은 매체 B를 건너뜁니다. A와 이슈가 겹치는 C는 제외합니다." : "반복에 따른 감점은 유지하며 연속 매체와 중복 이슈의 선택 제한만 해제합니다."}</p><Button variant="ghost" onClick={() => changeMode(CHAPTERS[(active + 1) % CHAPTERS.length].id)}>{active === 4 ? "처음으로" : "다음 과정"}<span aria-hidden="true">→</span></Button></div>
      <details className={styles.details} key={state.mode}><summary>계산식과 적용 기준</summary><TechnicalNote mode={state.mode} /></details>
    </section>
    <footer className={styles.footer}><p>관점 ≠ 정답 / 선정성 ≠ 품질 / 분석 신뢰도 ≠ 진실 확률</p><Link href="/issues">실제 이슈 비교하기 →</Link></footer>
  </article>;
}

function Range({ label, min, max, value, change }: { label: string; min: number; max: number; value: number; change: (n: number) => void }) {
  return <label className={styles.range}><span>{label}<strong>{value}</strong></span><input type="range" aria-label={label} min={min} max={max} value={value} onChange={event => change(Number(event.target.value))} /></label>;
}
function TechnicalNote({ mode }: { mode: AlgorithmMode }) {
  if (mode === "fetch") return <p>최근 3일 우선, 최대 7일의 실제 검색 URL을 확인합니다. robots와 이용 조건이 승인된 출처에 HTTP 요청 후 HTML에서 제목, 본문, 발행 시각을 추출합니다. 이동 주소도 재검증합니다. 이슈 비교에는 같은 논쟁을 다루는 독립 매체 3곳 이상이 필요하며 일반 기사 수집은 별도입니다.</p>;
  if (mode === "evidence") return <p>매체명과 URL, 기자 정보를 가리고 최대 2만 자를 분석합니다. JSON 구조와 원문 버전별 인용 위치를 검증합니다. 공통 사실은 최소 2개 기사의 근거가 필요합니다. 출처 사전값은 이후 점수 결합에 별도로 사용될 수 있습니다.</p>;
  if (mode === "weights") return <><p>x = clip(round(Σwₖxₖ / Σwₖ), −100, 100). 가중치는 버전별 설정입니다. s는 모델 선정성을 반올림하고 0~100으로 제한합니다.</p><p>C = clip(.45c_model + .25q_evidence + .15min(v/20,1) + .10min(n/20,1) + g, 0, 1). v는 평가 수, n은 출처 표본 수입니다. 모델 신뢰도가 양수일 때 g = .05(1−min(spread/100,1)), 그 외에는 0입니다.</p></>;
  if (mode === "coordinates") return <p>x ∈ [−100,100], s ∈ [0,100], C ∈ [0,1]. 그래프 깊이는 C × 100입니다. 조작값은 설명용이며 실제 기사 점수는 바뀌지 않습니다.</p>;
  return <><p>F = .30R + .14e^(−h/168) + .24Q + .12C + .20/(1+n_source) + .08/(1+n_issue) + P(d). 현재 공개 피드는 R=0, Q=C입니다. n은 앞서 선택된 기사 수입니다.</p><p>이 예시의 관점 보너스는 모두 .18입니다. 실제로는 정규화된 관점과 선정성 거리 d가 .02 &lt; d ≤ .65일 때 .18, 그 외에는 .04(1−d)입니다. 프로필이 없으면 .05입니다.</p></>;
}
