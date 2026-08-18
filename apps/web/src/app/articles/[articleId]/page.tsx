import { ExternalLink, History, Info } from "lucide-react";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { Badge } from "@/components/ui/badge";
import { StatePanel } from "@/components/ui/state-panel";
import { ReadActions } from "@/features/reading/read-actions";
import { VoteForm } from "@/features/voting/vote-form";
import { Button } from "@/components/ui/button";
import { articles } from "@/mocks/fixtures/content";
import { clampScore, formatBiasScore, formatConfidence, formatSensationalismScore } from "@/lib/api/formatters";
import { RealArticleDetail } from "@/features/articles/real-article-detail";
import { isMockMode } from "@/lib/api/mode";

export default async function ArticlePage({ params }: { params: Promise<{ articleId: string }> }) {
  const { articleId } = await params;
  if (!isMockMode()) return <RealArticleDetail articleId={articleId} />;
  const article = articles.find((item) => item.id === articleId);
  if (!article) notFound();
  return (
    <>
      {article.stale && <div style={{ marginBottom: "1rem" }}><StatePanel state="stale" /></div>}
      <div className="article-layout">
        <article className="card article-main">
          <div className="news-card__meta"><Badge>{article.source}</Badge><span>2026. 08. 16.</span><Badge tone="info">{article.scoreVersion}</Badge><Badge>LLM 평가 편향성 · {formatBiasScore(article.x)}</Badge><Badge>LLM 평가 과장성 · {formatSensationalismScore(article.sensationalism)}</Badge></div>
          <h1>{article.title}</h1><p className="article-main__dek">{article.dek}</p>
          <div className="notice"><Info size={15} aria-hidden="true" /> 아래 내용은 원문을 대체하지 않는 제한 공개 분석입니다. 편향성과 과장성 평가는 사실성이나 기사 품질 판정이 아닙니다.</div>
          <div className="section-head"><h2>핵심 주장</h2></div><ol className="claim-list">{article.claims.map((claim) => <li key={claim}>{claim}</li>)}</ol>
          <div className="section-head"><h2>모델별 제한 공개 요약</h2></div>
          <div className="grid grid--2"><section className="card card--padded"><Badge tone="positive">model-a · 성공</Badge><h3 style={{ marginTop: ".8rem" }}>정책 효과와 공공성의 긴장을 중심으로 해석</h3><p style={{ color: "var(--muted)" }}>인허가 시차와 공공 기여의 예측 가능성을 주요 근거로 들었습니다.</p><small>confidence 0.88 · prompt-v6</small></section><section className="card card--padded"><Badge tone="positive">model-b · 성공</Badge><h3 style={{ marginTop: ".8rem" }}>공급 확대의 실행 조건을 강조</h3><p style={{ color: "var(--muted)" }}>정책 수단보다 시행 과정의 병목을 더 크게 평가했습니다.</p><small>confidence 0.82 · prompt-v6</small></section><section className="card card--padded"><Badge tone="danger">model-c · 부분 실패</Badge><h3 style={{ marginTop: ".8rem" }}>이 모델의 분석은 집계에서 제외됨</h3><p style={{ color: "var(--muted)" }}>응답 schema가 기준을 충족하지 않아 확인 가능한 두 모델의 결과만 표시합니다.</p><small>stable error · MODEL_SCHEMA_REJECTED</small></section></div>
          <div className="section-head"><h2>독자 투표 분포</h2><span className="badge">qualified 184 / raw 203</span></div>
          <p style={{ color: "var(--muted)" }}>작은 인구통계 세그먼트는 표시하지 않습니다. 현재 집계 snapshot vote-v8.</p>
        </article>
        <aside className="card article-side" aria-label="기사 관점 분석">
          <div><p className="eyebrow">LLM 기사 평가</p><h2>편향성과 과장성</h2><p style={{ color: "var(--muted)", fontSize: ".82rem" }}>분석 신뢰도 {formatConfidence(article.confidence)}</p></div>
          <div className="axis" aria-label={`편향성 ${formatBiasScore(article.x)}`}>
            <div className="axis__head"><strong>편향성</strong><span>{formatBiasScore(article.x)}</span></div>
            <div className="axis__labels"><span>좌편향</span><span>우편향</span></div>
            <div className="axis__track axis__track--bias" aria-hidden="true"><span className="axis__center" /><span className="axis__marker" style={{ left: `${(clampScore(article.x) + 100) / 2}%` }} /></div>
          </div>
          <div className="axis" aria-label={`과장성 ${formatSensationalismScore(article.sensationalism)}`}>
            <div className="axis__head"><strong>과장성</strong><span>{formatSensationalismScore(article.sensationalism)}</span></div>
            <div className="axis__labels"><span>낮음</span><span>높음</span></div>
            {article.sensationalism === null ? <small>이 버전에는 과장성 측정값이 없습니다.</small> : <div className="axis__track" aria-hidden="true"><span className="axis__marker" style={{ left: `${clampScore(article.sensationalism, 0, 100)}%` }} /></div>}
            <small>허위 판정이 아닌 표현 강도 평가</small>
          </div>
          <a className="external-link" href={article.originalUrl} target="_blank" rel="noreferrer">언론사 원문 새 창에서 보기 <ExternalLink size={15} /></a>
          <Suspense><ReadActions articleId={article.id} originalUrl={article.originalUrl} /></Suspense>
          <Button variant="ghost"><History size={15} /> 점수 정정·버전 이력</Button>
        </aside>
      </div>
      <div style={{ marginTop: "1rem" }}><VoteForm articleId={article.id} /></div>
    </>
  );
}
