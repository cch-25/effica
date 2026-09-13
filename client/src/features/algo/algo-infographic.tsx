"use client";

import Link from "next/link";
import { useState, type CSSProperties } from "react";
import { Button } from "@/components/ui/button";
import { InteractiveGraph } from "@/components/graphs/interactive-graph";
import type { GraphAxes, GraphPoint } from "@/components/graphs/graph-model";
import styles from "./algo-infographic.module.css";

const AXES: GraphAxes = [
  { label: "관점 x", min: -100, max: 100, low: "진보", high: "보수" },
  { label: "선정성 s", min: 0, max: 100, low: "절제", high: "강한 표현" },
  { label: "분석 신뢰도", min: 0, max: 100, suffix: "%", low: "낮음", high: "높음" },
];
const CHAPTERS = [
  ["fetch", "원문을 가져온다", "검색 주소 → 검증된 본문"],
  ["evidence", "문장의 근거를 찾는다", "본문 → 근거 구간"],
  ["coordinates", "비교할 좌표를 만든다", "분석 신호 → x, s, C"],
  ["ranking", "읽을 순서를 정한다", "점수와 다양성 → 추천"],
] as const;

export function AlgoInfographic() {
  return <article className={styles.page}>
    <header className={styles.hero}>
      <p className={styles.eyebrow}>EFFICA / 알고리즘 해설</p>
      <h1>기사 한 편은 어떻게<br />비교할 수 있는 정보가 될까?</h1>
      <p className={styles.lead}>출처에서 원문을 가져오는 순간부터 추천 순서가 정해질 때까지.<br className={styles.desktopBreak} /> 직접 값을 바꾸며 에피카가 뉴스를 처리하는 과정을 따라가 보세요.</p>
      <nav className={styles.overview} aria-label="알고리즘 목차">
        {CHAPTERS.map(([id, title, description], i) => <Link href={`#${id}`} key={id}>
          <span className={styles.chapterNo}>0{i + 1}<span aria-hidden="true">→</span></span>
          <strong>{title}</strong><small>{description}</small>
        </Link>)}
      </nav>
    </header>
    <section id="fetch" className={styles.chapter} aria-labelledby="fetch-title">
      <ChapterTitle number="01" label="수집" title="검색은 주소를 찾고, Fetch는 본문을 가져옵니다." id="fetch-title" />
      <div className={styles.spread}>
        <div className={styles.copy}>
          <p>검색 결과의 요약만으로 기사를 분석할 수는 없습니다. 에피카는 검색에서 확인한 주소를 따라 <strong>언론사 서버에 직접 요청</strong>하고, 응답으로 받은 HTML에서 실제 본문을 추출합니다.</p>
          <ol className={styles.explanation}>
            <li><strong>실제 주소인지 확인</strong><span>검색 출처나 인용에 등장한 기사 URL만 후보로 받습니다. 허용된 매체 안에서 최근 3일을 먼저 찾고 최대 7일까지 넓힙니다.</span></li>
            <li><strong>가져와도 되는 출처인지 확인</strong><span>매체의 수집 정책 승인과 robots 및 이용 조건의 허용 여부를 확인합니다.</span></li>
            <li><strong>서버 응답에서 본문 추출</strong><span>HTTP 요청 후 HTML의 기사 메타데이터와 본문 영역을 읽습니다. 검색 요약문을 원문 대신 채워 넣지 않습니다.</span></li>
            <li><strong>같은 사건의 보도끼리 비교</strong><span>원문을 읽고 같은 정책 논쟁을 다루는지 재검증합니다. 독립 매체 3곳 이상이 확보돼야 이슈 비교를 구성합니다.</span></li>
          </ol>
          <details className={styles.details}><summary>네트워크 요청은 어떻게 검증하나요?</summary><p>요청과 재시도마다 DNS 결과가 공개 네트워크 주소인지 검사하고 검증된 IP로 연결합니다. 리디렉션도 한 단계씩 확인합니다. 요청 속도와 응답 크기, 대기 시간을 제한하며 다른 출처로 이동할 때 인증 정보를 전달하지 않습니다.</p><p>일반 기사 수집은 별도로 승인된 출처의 RSS, API, 크롤러 설정을 사용합니다. 이슈 비교의 ‘매체 3곳’ 조건을 일반 기사 한 편의 저장 조건과 혼동하지 않습니다.</p></details>
        </div>
        <FetchDiagram />
      </div>
    </section>
    <section id="evidence" className={styles.chapter} aria-labelledby="evidence-title">
      <ChapterTitle number="02" label="분석" title="누가 썼는지 가리고, 어떤 문장인지 읽습니다." id="evidence-title" />
      <div className={styles.spread}>
        <div className={styles.copy}>
          <p>같은 사안도 무엇을 제목에 올리고 어떤 표현을 고르느냐에 따라 다르게 읽힙니다. 모델은 출처 이름을 가린 본문에서 <strong>선택과 강조의 근거</strong>를 찾습니다.</p>
          <p>본문은 최대 2만 자까지 입력합니다. 모델은 관점과 선정성, 분석 신뢰도를 정해진 JSON 구조로 반환하고 판단에 사용한 원문 구간도 함께 제출합니다.</p>
          <div className={styles.takeaway}><strong>설명만 그럴듯해서는 통과하지 못합니다.</strong><p>인용 문구가 해당 원문 버전의 정확한 글자 위치와 일치해야 합니다. 공통 사실에는 최소 두 기사의 근거가 연결됩니다.</p></div>
          <details className={styles.details}><summary>출처 정보는 언제 다시 쓰이나요?</summary><p>모델의 본문 분석 입력에서는 매체명과 주소, 기자 정보를 가립니다. 최종 점수 결합 단계에는 버전별 설정에 따라 출처 사전값이 별도의 신호로 들어갈 수 있습니다. ‘본문 우선 분석’이 모든 단계에서 출처를 없앤다는 뜻은 아닙니다.</p></details>
        </div>
        <EvidenceDiagram />
      </div>
    </section>
    <section id="coordinates" className={styles.chapter} aria-labelledby="coordinates-title">
      <ChapterTitle number="03" label="좌표" title="방향, 표현의 강도, 분석의 안정성을 따로 봅니다." id="coordinates-title" />
      <CoordinateLab />
    </section>
    <section id="ranking" className={styles.chapter} aria-labelledby="ranking-title">
      <ChapterTitle number="04" label="추천" title="점수가 높아도, 같은 보도만 줄 세우지 않습니다." id="ranking-title" />
      <RankingLab />
    </section>
    <footer className={styles.closing}>
      <div><p className={styles.eyebrow}>숫자를 읽는 기준</p><h2>좌표는 비교의 출발점입니다.</h2><p>관점은 정답이 아니고, 선정성은 기사 품질이 아닙니다.<br />분석 신뢰도는 진실 확률이나 매체의 신뢰도를 뜻하지 않습니다.</p></div>
      <Link href="/issues">실제 이슈 비교하기 <span aria-hidden="true">→</span></Link>
    </footer>
  </article>;
}

function ChapterTitle({ number, label, title, id }: { number: string; label: string; title: string; id: string }) {
  return <header className={styles.chapterHeading}><span>{number} / {label}</span><h2 id={id}>{title}</h2></header>;
}

const FETCH_STEPS = ["주소 발견", "출처 승인", "HTTP 응답", "본문 검증", "이슈 구성"];
const SOURCES = [
  { name: "매체 A", url: "a.example/news/101", chars: 1240, days: 1, failure: "", gate: 9 },
  { name: "매체 B", url: "b.example/news/202", chars: 980, days: 2, failure: "", gate: 9 },
  { name: "매체 C", url: "c.example/news/303", chars: 1560, days: 1, failure: "", gate: 9 },
  { name: "미승인 출처", url: "unknown.example/404", chars: 0, days: 0, failure: "출처 미승인", gate: 1 },
  { name: "매체 D", url: "d.example/news/505", chars: 84, days: 1, failure: "본문 200자 미만", gate: 3 },
];

function FetchDiagram() {
  const [step, setStep] = useState(0);
  const passed = SOURCES.filter(source => source.gate > step).length;
  return <figure className={styles.lab}>
    <figcaption className={styles.labHeading}><strong>주소 5개가 들어오면</strong><span>가상 수집 예시</span></figcaption>
    <div className={styles.fetchTabs} role="group" aria-label="수집 단계">
      {FETCH_STEPS.map((label, i) => <Button key={label} variant="ghost" aria-pressed={step === i} onClick={() => setStep(i)}><small>0{i + 1}</small>{label}</Button>)}
    </div>
    <div className={styles.fetchRows}>
      {SOURCES.map(source => {
        const rejected = source.gate <= step;
        const status = rejected ? source.failure : step === 0 ? "검색 출처 확인" : step === 1 ? "수집 허용" : step === 2 ? "200 OK → HTML" : step === 3 ? `${source.chars.toLocaleString()}자 / ${source.days}일 전` : "같은 논쟁 확인";
        return <div key={source.url} data-rejected={rejected} className={styles.fetchRow}>
          <span><strong>{source.name}</strong><small>{source.url}</small></span>
          <span className={styles.transfer} aria-hidden="true"><i key={`${source.url}-${step}`} /></span>
          <span className={styles.fetchStatus}>{rejected ? "× " : ""}{status}</span>
        </div>;
      })}
    </div>
    <div className={styles.result} aria-live="polite"><span>{step === 4 ? "이슈 비교에 사용" : "다음 검사로 이동"}</span><strong>{passed}<small> / 5편</small></strong></div>
    <p className={styles.caption}>{[
      "검색은 기사 주소를 발견하는 단계입니다. 아직 본문을 가져오거나 분석하지 않았습니다.",
      "미승인 출처는 요청 전에 제외됩니다. 허용 출처 4곳에만 접근합니다.",
      "서버가 HTML을 보내줬다는 사실만 확인했습니다. 200 OK라고 분석 가능한 기사인 것은 아닙니다.",
      "제목과 발행 시각, 충분한 본문을 확인합니다. 여기서는 본문이 84자인 응답 하나가 탈락합니다.",
      "서로 다른 매체 A, B, C의 원문이 같은 논쟁을 다룹니다. 이 예시는 3편으로 이슈를 구성합니다.",
    ][step]}</p>
    <Button variant="secondary" className={styles.next} onClick={() => setStep((step + 1) % 5)}>{step === 4 ? "처음부터 다시 보기" : "다음 검사로 보내기"}<span aria-hidden="true">→</span></Button>
  </figure>;
}

const EXAMPLE_PREFIX = "정부가 새로운 지원 대책을 발표했다. ";
const EXAMPLE_QUOTE = "예산 부담은 남았지만 단기 효과가 기대된다.";
function EvidenceDiagram() {
  const [masked, setMasked] = useState(true);
  const [highlight, setHighlight] = useState(false);
  return <figure className={styles.lab}>
    <figcaption className={styles.labHeading}><strong>모델에 전달되는 기사</strong><span>가상 문장 예시</span></figcaption>
    <div className={styles.controls}>
      <Button variant="secondary" aria-pressed={masked} onClick={() => setMasked(!masked)}>{masked ? "출처 가림 켜짐" : "출처 가림 꺼짐"}</Button>
      <Button variant="secondary" aria-pressed={highlight} onClick={() => setHighlight(!highlight)}>근거 구간 {highlight ? "숨기기" : "확인"}</Button>
    </div>
    <div className={styles.document}>
      <div className={styles.byline}><span>매체</span><strong className={masked ? styles.redacted : undefined}>{masked ? "가려짐" : "예시신문"}</strong><span>기자</span><strong className={masked ? styles.redacted : undefined}>{masked ? "가려짐" : "김기자"}</strong></div>
      <h3>지원 대책 발표, 기대와 비용 사이</h3>
      <p>{EXAMPLE_PREFIX}<mark data-highlight={highlight}>{EXAMPLE_QUOTE}</mark> 시행 범위와 재원 조달 방식은 추가 논의하기로 했다.</p>
      <div className={styles.evidenceResult} aria-live="polite">
        <span>{highlight ? "본문에서 직접 확인한 구간" : "‘근거 구간 확인’을 누르세요"}</span>
        <code>{highlight ? `[${EXAMPLE_PREFIX.length}, ${EXAMPLE_PREFIX.length + EXAMPLE_QUOTE.length})` : "[start, end)"}</code>
        <p>{highlight ? `“${EXAMPLE_QUOTE}”` : "모델이 인용한 문구와 원문 위치를 대조합니다."}</p>
      </div>
    </div>
    <p className={styles.caption}>이 문장은 UI 설명을 위한 예시이며 실제 모델 분석 결과가 아닙니다. 위치 범위는 위 예시 본문의 글자 수로 계산됩니다.</p>
  </figure>;
}

function Range({ label, value, min, max, onChange, suffix = "" }: { label: string; value: number; min: number; max: number; onChange: (value: number) => void; suffix?: string }) {
  return <label className={styles.range}><span>{label}<output>{value}{suffix}</output></span><input aria-label={label} type="range" min={min} max={max} value={value} onChange={event => onChange(Number(event.target.value))} /><span className={styles.rangeEnds}><small>{min}{suffix}</small><small>{max}{suffix}</small></span></label>;
}

function CoordinateLab() {
  const [x, setX] = useState(20);
  const [s, setS] = useState(35);
  const [c, setC] = useState(75);
  const points: GraphPoint[] = [{ id: "demo", ids: ["demo"], label: "예시 기사", values: [x, s, c], marker: "A" }];
  return <>
    <div className={styles.spread}>
      <div className={styles.copy}>
        <p><strong>가로는 관점, 높이는 선정성, 깊이는 분석 신뢰도.</strong> 슬라이더 하나를 움직이면 그 축의 값만 바뀝니다. 서로 다른 의미의 수치를 하나의 ‘좋은 기사 점수’로 합치지 않습니다.</p>
        <div className={styles.ranges}>
          <Range label="관점 x / 진보에서 보수로" value={x} min={-100} max={100} onChange={setX} />
          <Range label="선정성 s / 표현의 강도" value={s} min={0} max={100} onChange={setS} />
          <Range label="분석 신뢰도 C / 근거의 안정성" value={c} min={0} max={100} suffix="%" onChange={setC} />
        </div>
        <p className={styles.caption}>위 슬라이더는 축의 의미를 배우는 도구입니다. 실제 기사 점수나 사용자 프로필은 변경하지 않습니다. 깊이는 C × 100으로 표시합니다.</p>
      </div>
      <figure className={`${styles.lab} ${styles.coordinateLab}`}>
        <figcaption className={styles.labHeading}><strong>세 값이 한 점이 되는 과정</strong><span>THREE.JS / 수치 기반 예시</span></figcaption>
        <InteractiveGraph axes={AXES} points={points} selectedId="demo" title="관점과 선정성, 분석 신뢰도에 따른 예시 기사 좌표" />
      </figure>
    </div>
    <WeightLab />
  </>;
}

function WeightLab() {
  const [model, setModel] = useState(30);
  const signals = [
    { name: "모델 판단", value: model, weight: 0.6 },
    { name: "상대 프레이밍", value: -10, weight: 0.2 },
    { name: "독자 평가", value: 20, weight: 0.15 },
    { name: "출처 사전값", value: 0, weight: 0.05 },
  ];
  const raw = signals.reduce((sum, signal) => sum + signal.value * signal.weight, 0);
  const final = Math.sign(raw) * Math.floor(Math.abs(raw) + 0.5);
  return <div className={styles.calculation}>
    <div className={styles.copy}><h3>그럼 관점 x는 어떻게 계산할까요?</h3><p>각 신호에 설정된 비중을 곱한 뒤 전체 비중으로 나눈 가중 평균입니다. 모델 판단을 바꾸면 오른쪽의 기여량과 최종 좌표가 함께 변합니다.</p><Range label="모델 판단을 바꿔 보세요" value={model} min={-100} max={100} onChange={setModel} /><p className={styles.caption}>설명용 가중치 60%, 20%, 15%, 5%를 사용합니다. 운영 가중치는 버전별 설정을 따릅니다.</p></div>
    <div className={styles.weightVisual}>
      <div className={styles.labHeading}><strong>입력 × 가중치 = 기여량</strong><span>음수 ← 0 → 양수</span></div>
      {signals.map(signal => <div className={styles.weightRow} key={signal.name}><span>{signal.name}<small>{signal.value} × {signal.weight}</small></span><div className={styles.signedBar}><i style={{ left: `${50 + Math.min(0, signal.value * signal.weight) / 1.2}%`, width: `${Math.abs(signal.value * signal.weight) / 1.2}%` }} /></div><output>{(signal.value * signal.weight).toFixed(1)}</output></div>)}
      <div className={styles.result} aria-live="polite"><span>합계 {raw.toFixed(1)} / 총 비중 1 → 반올림</span><strong>x = {final > 0 ? "+" : ""}{final}</strong></div>
    </div>
    <details className={styles.details}><summary>실제 점수와 신뢰도 수식 보기</summary>
      <p className={styles.formula}>x = clip(round(Σ wₖxₖ / Σ wₖ), −100, 100)<br />s = clip(round(s_model), 0, 100)</p>
      <p className={styles.formula}>C = clip(.45c_model + .25q_evidence + .15min(v/20, 1) + .10min(n/20, 1) + g, 0, 1)</p>
      <p>v는 독자 평가 수, n은 출처 표본 수입니다. g는 모델 신뢰도가 양수일 때 .05 × (1 − min(spread/100, 1))이며 그 외에는 0입니다. 평가 수와 표본 수는 각각 20개에서 포화됩니다.</p>
      <p>원문 버전과 설정의 지문을 기록합니다. 새 점수가 활성화되면 이전 점수는 비활성화해 분석 이력을 추적할 수 있도록 합니다.</p>
    </details>
  </div>;
}

const FEED_EXAMPLES = [
  { id: "A", source: "가 매체", issue: "예산", x: 15, s: 10, c: .92, h: 2 },
  { id: "B", source: "가 매체", issue: "교통", x: 90, s: 35, c: .86, h: 5 },
  { id: "C", source: "나 매체", issue: "예산", x: -95, s: 40, c: .84, h: 4 },
  { id: "D", source: "다 매체", issue: "주거", x: -10, s: 15, c: .82, h: 8 },
];
function RankingLab() {
  const [profile, setProfile] = useState(0);
  const [diverse, setDiverse] = useState(true);
  const score = (item: typeof FEED_EXAMPLES[number], sources: Record<string, number> = {}, issues: Record<string, number> = {}) => {
    const d = Math.min(1, Math.hypot((item.x - profile) / 200, item.s / 100) / Math.SQRT2);
    return .14 * Math.exp(-item.h / 168) + .36 * item.c + .20 / (1 + (sources[item.source] ?? 0)) + .08 / (1 + (issues[item.issue] ?? 0)) + (d > .02 && d <= .65 ? .18 : .04 * (1 - d));
  };
  const ranked = [...FEED_EXAMPLES].sort((a, b) => score(b) - score(a));
  const chosen: Array<{ item: typeof FEED_EXAMPLES[number]; score: number }> = [];
  const sourceCounts: Record<string, number> = {};
  const issueCounts: Record<string, number> = {};
  const pool = [...ranked];
  while (pool.length) {
    const allowed = pool.filter(item => !diverse || (!issueCounts[item.issue] && chosen.at(-1)?.item.source !== item.source));
    allowed.sort((a, b) => score(b, sourceCounts, issueCounts) - score(a, sourceCounts, issueCounts));
    const item = allowed[0];
    if (!item) break;
    chosen.push({ item, score: score(item, sourceCounts, issueCounts) });
    sourceCounts[item.source] = (sourceCounts[item.source] ?? 0) + 1;
    issueCounts[item.issue] = (issueCounts[item.issue] ?? 0) + 1;
    pool.splice(pool.indexOf(item), 1);
  }
  return <div className={styles.spread}>
    <div className={styles.copy}>
      <p>기본 점수에 최신성, 분석 신뢰도, 관점의 차이를 반영합니다. 기사를 하나 고를 때마다 매체와 이슈의 반복 횟수를 갱신하고, <strong>다음으로 고를 수 있는 기사</strong>의 점수를 다시 계산합니다.</p>
      <Range label="예시 독자의 관점 x" value={profile} min={-100} max={100} onChange={setProfile} />
      <div className={styles.takeaway}><strong>다양성 규칙을 켜 보세요.</strong><p>같은 이슈의 중복 기사는 제외되고, 같은 매체의 기사가 연속되지 않도록 다음 기사가 달라집니다.</p></div>
      <details className={styles.details}><summary>추천 점수 수식과 현재 적용값</summary><p className={styles.formula}>F = .30R + .14e^(−h/168) + .24Q + .12C + .20/(1+n_source) + .08/(1+n_issue) + P(d)</p><p>R은 관련성, h는 발행 후 경과 시간입니다. n은 이미 선택한 동일 매체 또는 이슈의 기사 수입니다. 현재 공개 피드와 이 데모는 Q = C, R = 0을 사용합니다.</p><p className={styles.formula}>d = min(1, √(((x−uₓ)/200)² + ((s−uₛ)/100)²) / √2)</p><p>0.02 &lt; d ≤ 0.65이면 P(d) = 0.18입니다. 그 밖에는 0.04(1−d)를 더합니다. 프로필이 없으면 0.05를 더하고, 현재 설문 프로필의 선정성 좌표 uₛ는 0입니다.</p></details>
    </div>
    <figure className={styles.lab}>
      <figcaption className={styles.labHeading}><strong>점수순에서 읽는 순서로</strong><span>기사 4편 / 가상 입력</span></figcaption>
      <div className={styles.controls}><Button variant="secondary" aria-pressed={diverse} onClick={() => setDiverse(!diverse)}>다양성 규칙 {diverse ? "켜짐" : "꺼짐"}</Button></div>
      <div className={styles.rankingLabels}><span>초기 점수</span><span>선택 순서</span></div>
      <div className={styles.rankingDiagram}>
        <div className={styles.candidates}>{ranked.map(item => <div key={item.id}><strong>{item.id}<small>{item.source} / {item.issue}</small></strong><span className={styles.scoreBar}><i style={{ width: `${score(item) * 100}%` }} /></span><output>{score(item).toFixed(3)}</output></div>)}</div>
        <ol className={styles.chosen} aria-label="예시 추천 순서" style={{ minHeight: `${chosen.length * 5.3}rem` }}>{chosen.map(({ item, score: itemScore }, i) => <li key={item.id} style={{ "--order": i } as CSSProperties}><span>{i + 1}</span><strong>기사 {item.id}<small>{item.source} / {item.issue}</small></strong><output>{itemScore.toFixed(3)}</output></li>)}</ol>
      </div>
      <p className={styles.caption} aria-live="polite">{diverse ? `선택 순서: ${chosen.map(({ item }) => item.id).join(" → ")}. ${pool.length ? `${pool.map(item => item.id).join(", ")}는 이미 선택된 이슈와 겹치거나 연속 매체 조건으로 제외됩니다.` : "모든 후보가 제약을 통과했습니다."}` : "반복 횟수에 따른 점수 보정은 유지하고, 연속 매체와 중복 이슈의 선택 제한만 해제했습니다."}</p>
      <details className={styles.details}><summary>데모 입력값 확인</summary><div className={styles.inputs}>{FEED_EXAMPLES.map(item => <p key={item.id}>{item.id}: x={item.x}, s={item.s}, C={item.c}, {item.h}시간 전</p>)}</div></details>
    </figure>
  </div>;
}
