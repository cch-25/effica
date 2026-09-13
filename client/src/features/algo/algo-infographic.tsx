"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { AUTO_INTERVAL_MS, SLIDER_TRANSITION_MS, INITIAL_STATE, advanceAlgorithm, interpolateAlgorithm, rankingExample, weightedScore, type AlgorithmMode, type AlgorithmState } from "./algo-model";
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
  return <article className={styles.page}>
    <header className={styles.heading}>
      <p>EFFICA / INSIDE THE ALGORITHM</p>
      <h1>뉴스가 비교가 되는 과정</h1>
      <p className={styles.intro}>원문을 찾고, 근거를 남기고, 다른 관점을 연결합니다.<br />다섯 번의 계산을 수식과 3D로 따라가 보세요.</p>
      <ol className={styles.journey}>{CHAPTERS.map((chapter, index) => <li key={chapter.id}><span>0{index + 1}</span>{chapter.name}</li>)}</ol>
      <a className={styles.startLink} href="#algo-fetch">첫 번째 과정부터 살펴보기 ↓</a>
    </header>
    {CHAPTERS.map((chapter, index) => <AlgorithmChapter key={chapter.id} chapter={chapter} index={index} />)}
    <footer className={styles.footer}><div><h2>이제, 같은 뉴스를 다르게 읽어보세요.</h2><p>관점 ≠ 정답 / 선정성 ≠ 품질 / 분석 신뢰도 ≠ 진실 확률</p></div><Link href="/issues">실제 이슈 비교하기 →</Link></footer>
  </article>;
}

function AlgorithmChapter({ chapter, index }: { chapter: typeof CHAPTERS[number]; index: number }) {
  const [state, setState] = useState<AlgorithmState>({ ...INITIAL_STATE, mode: chapter.id });
  const [status, setStatus] = useState<"loading" | "ready" | "fallback">("loading");
  const [rotating, setRotating] = useState(true);
  const [autoplay, setAutoplay] = useState(true);
  const [inView, setInView] = useState(false);
  const host = useRef<HTMLDivElement>(null);
  const runtime = useRef<ReturnType<typeof createAlgorithmScene> | null>(null);
  const latest = useRef(state);
  const latestRotation = useRef(true);
  const animation = useRef<number | null>(null);
  const interact = (update: (current: AlgorithmState) => AlgorithmState) => {
    if (animation.current !== null) cancelAnimationFrame(animation.current);
    animation.current = null;
    setAutoplay(false); setState(update);
  };
  useEffect(() => {
    const node = host.current;
    if (!node) return;
    const observer = new IntersectionObserver(([entry]) => setInView(entry.isIntersecting), { threshold: .2 });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!autoplay || !inView || status !== "ready") return;
    const interval = window.setInterval(() => {
      if (document.hidden) return;
      const from = latest.current;
      const to = advanceAlgorithm(from);
      if ((from.mode !== "weights" && from.mode !== "coordinates") || matchMedia("(prefers-reduced-motion: reduce)").matches) {
        setState(to); return;
      }
      if (animation.current !== null) cancelAnimationFrame(animation.current);
      const started = performance.now();
      const tick = (now: number) => {
        if (document.hidden) { animation.current = null; return; }
        const progress = Math.min((now - started) / SLIDER_TRANSITION_MS, 1);
        setState(interpolateAlgorithm(from, to, progress));
        animation.current = progress < 1 ? requestAnimationFrame(tick) : null;
      };
      animation.current = requestAnimationFrame(tick);
    }, AUTO_INTERVAL_MS);
    return () => {
      window.clearInterval(interval);
      if (animation.current !== null) cancelAnimationFrame(animation.current);
      animation.current = null;
    };
  }, [autoplay, inView, status]);
  useEffect(() => { latest.current = state; runtime.current?.update(state); }, [state]);
  useEffect(() => { latestRotation.current = rotating; runtime.current?.setInteractive(rotating); }, [rotating]);
  useEffect(() => {
    const node = host.current;
    if (!node) return;
    let generation = 0;
    let active = false;
    const release = () => {
      active = false; generation++;
      runtime.current?.dispose(); runtime.current = null;
    };
    const lost = (event: Event) => { event.preventDefault(); if (active) setStatus("fallback"); };
    node.addEventListener("webglcontextlost", lost, true);
    const observer = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) { release(); setStatus("loading"); return; }
      if (active) return;
      active = true;
      const token = ++generation;
      void import("./algo-scene").then(({ createAlgorithmScene }) => {
        if (!active || token !== generation) return;
        runtime.current = createAlgorithmScene(node, latest.current);
        runtime.current.setInteractive(latestRotation.current);
        setStatus("ready");
      }).catch(() => { if (active && token === generation) setStatus("fallback"); });
    }, { rootMargin: "450px 0px" });
    observer.observe(node);
    return () => { observer.disconnect(); node.removeEventListener("webglcontextlost", lost, true); release(); };
  }, []);

  const result = state.mode === "fetch" ? ["5개 주소 발견", "허용 출처 4곳", "본문 검증 통과 3편", "독립 매체 3곳 → 이슈 구성"][state.step]
    : state.mode === "evidence" ? ["원문 입력", "매체와 기자 정보 가림", "근거 24자 → [21, 45)"][state.step]
    : state.mode === "weights" ? `x = ${weightedScore(state.model)}`
    : state.mode === "coordinates" ? `x ${state.x} / s ${state.s} / C ${(state.c / 100).toFixed(2)}`
    : `${rankingExample(state.diverse).selected.map(item => item.id).join(" → ")}${state.diverse ? " / C 제외" : ""}`;
  return <section id={`algo-${chapter.id}`} className={styles.experiment} aria-labelledby={`algo-${chapter.id}-title`}>
      <header className={styles.experimentHeading}><div><span className={styles.chapterLabel}>0{index + 1} / {chapter.name}</span><h2 id={`algo-${chapter.id}-title`}>{chapter.title}</h2><p>{chapter.subtitle}</p></div><span className={styles.demoLabel}>설명용 가상 데이터</span></header>
      <Formula state={state} />
      <div className={styles.console}>
        <div className={styles.action}>
          {state.mode === "fetch" && <Button onClick={() => interact(advanceAlgorithm)}>{["출처 확인", "원문 요청 + 검증", "이슈로 묶기", "다시 수집하기"][state.step]}<span aria-hidden="true">→</span></Button>}
          {state.mode === "evidence" && <Button onClick={() => interact(advanceAlgorithm)}>{["출처 가리기", "근거 추출하기", "원문으로 되돌리기"][state.step]}<span aria-hidden="true">→</span></Button>}
          {state.mode === "weights" && <Range label="모델 판단" min={-100} max={100} value={state.model} change={model => interact(current => ({ ...current, model }))} />}
          {state.mode === "coordinates" && <div className={styles.coordinateInputs}><Range label="관점 x" min={-100} max={100} value={state.x} change={x => interact(current => ({ ...current, x }))} /><Range label="선정성 s" min={0} max={100} value={state.s} change={s => interact(current => ({ ...current, s }))} /><Range label="신뢰도 C (%)" min={0} max={100} value={state.c} change={c => interact(current => ({ ...current, c }))} /></div>}
          {state.mode === "ranking" && <Button aria-pressed={state.diverse} onClick={() => interact(advanceAlgorithm)}>다양성 제약 {state.diverse ? "켜짐" : "꺼짐"}<span aria-hidden="true">↔</span></Button>}
        </div>
        <output className={styles.readout} aria-live={autoplay ? "off" : "polite"}>{result}</output>
      </div>
      <div className={styles.stage}>
        <div className={styles.stageTools}><span>THREE.JS / {state.mode.toUpperCase()}</span><div><Button variant="ghost" aria-pressed={autoplay} onClick={() => setAutoplay(value => !value)}>{autoplay ? "자동 재생 일시정지" : "자동 재생 시작"}</Button><Button variant="ghost" disabled={status !== "ready"} aria-pressed={rotating} onClick={() => setRotating(value => !value)}>회전 {rotating ? "켜짐" : "꺼짐"}</Button><Button variant="ghost" disabled={status !== "ready"} onClick={() => runtime.current?.resetView()}>시점 초기화</Button></div></div>
        <div ref={host} className={styles.canvas} role="img" aria-label={`${chapter.title} ${result}`} data-status={status} />
        {status !== "ready" && <div className={styles.fallback}><strong>{status === "loading" ? "3D 계산 장면 준비 중" : "이 환경에서는 3D를 표시할 수 없습니다."}</strong><p>{result}</p></div>}
      </div>
      <div className={styles.caption}><p>{state.mode === "fetch" ? ["검색 요약은 주소를 찾는 힌트입니다. 아직 기사 본문이 아닙니다.", "미승인 출처는 요청 전에 멈춥니다.", "HTTP 응답에서 본문을 추출합니다. 84자 응답은 본문 200자 기준에서 탈락합니다.", "같은 논쟁을 다룬 원문 3편. 중복 매체 없이 비교를 구성합니다."][state.step]
        : state.mode === "evidence" ? "문장은 가상 예시입니다. 근거 범위 [21, 45)는 실제 예시 글자 수로 계산합니다."
        : state.mode === "weights" ? "설명용 비중: 모델 60%, 상대 프레임 20%, 독자 평가 15%, 출처 사전값 5%."
        : state.mode === "coordinates" ? "각 축을 바꿔 보세요. 점과 바닥 투영이 해당 수치로 이동합니다."
        : state.diverse ? "A 다음에 같은 매체 B를 건너뜁니다. A와 이슈가 겹치는 C는 제외합니다." : "반복에 따른 감점은 유지하며 연속 매체와 중복 이슈의 선택 제한만 해제합니다."}</p></div>
      <details className={styles.details}><summary>변수의 의미와 적용 기준</summary><TechnicalNote mode={state.mode} /></details>
    </section>;
}

function Formula({ state }: { state: AlgorithmState }) {
  const equation = (label: string, children: React.ReactNode) => <div className={styles.equation} role="math" aria-label={label}>{children}</div>;
  if (state.mode === "fetch") return <div className={styles.formula}>
    {equation("수집 집합은 발견 URL 중 승인된 출처와 유효한 본문을 갖는 기사", <><span>수집 집합 =</span><span>발견 URL ∩ 승인 출처 ∩ 유효 본문</span></>)}
    <p>본문 ≥ 200자<span>독립 매체 ≥ 3곳 → 이슈 비교</span></p>
  </div>;
  if (state.mode === "evidence") return <div className={styles.formula}>
    {equation("근거 인용은 원문의 시작 위치부터 끝 위치 직전까지", <><span>근거 = 원문[시작 : 끝]</span><span className={styles.purple}>길이 = 끝 − 시작</span></>)}
    <p>원문[21 : 45] = 근거 24자<span>이름 대신 문장과 위치를 검증합니다.</span></p>
  </div>;
  if (state.mode === "weights") return <div className={styles.formula}>
    {equation("관점 x는 가중 평균을 반올림한 뒤 마이너스 100에서 100으로 제한", <><span>x = clip</span><span>( round ( <span className={styles.fraction}><span>Σ w<sub>k</sub>x<sub>k</sub></span><span>Σ w<sub>k</sub></span></span> ), −100, 100 )</span></>)}
    <div className={styles.substitution}><span className={styles.blue}>{state.model} × .60</span><span>+</span><span className={styles.coral}>(−10) × .20</span><span>+</span><span className={styles.purple}>20 × .15</span><span>+</span><span className={styles.amber}>0 × .05</span><span>→</span><strong>x = {weightedScore(state.model)}</strong></div>
  </div>;
  if (state.mode === "coordinates") return <div className={styles.formula}>
    {equation("기사의 좌표는 관점 x, 선정성 s, 분석 신뢰도 C", <><span>p = ( <i className={styles.blue}>x</i>, <i className={styles.coral}>s</i>, <i className={styles.purple}>C</i> )</span><span className={styles.coordinateValue}>= ({state.x}, {state.s}, {(state.c / 100).toFixed(2)})</span></>)}
    <div className={styles.secondaryEquation} role="math" aria-label="신뢰도 C 계산식"><span>C = clip( .45c<sub>model</sub> + .25q<sub>evidence</sub></span><span>+ .15min(v/20, 1) + .10min(n/20, 1) + g, 0, 1 )</span></div>
    <p>x ∈ [−100, 100]<span>s ∈ [0, 100]</span><span>C ∈ [0, 1]</span></p>
  </div>;
  return <div className={styles.formula}>
    {equation("추천 점수는 관련성, 최신성, 품질, 신뢰도와 다양성의 합", <><span>F = .30R + .14e<sup>−h/168</sup> + .24Q + .12C</span><span>+ <span className={styles.fraction}><span>.20</span><span>1 + n<sub>source</sub></span></span> + <span className={styles.fraction}><span>.08</span><span>1 + n<sub>issue</sub></span></span> + P(d)</span></>)}
    <p>앞서 고른 매체나 이슈가 반복될수록 점수가 낮아집니다.<span>선택 → 반복 수 갱신 → 다음 점수 재계산</span></p>
  </div>;
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
