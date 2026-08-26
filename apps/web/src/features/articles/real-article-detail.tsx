"use client";

import { ExternalLink, Info } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { StatePanel } from "@/components/ui/state-panel";
import { VoteForm } from "@/features/voting/vote-form";
import { clampScore, formatBiasScore, formatConfidence, formatPublishedDate, formatSensationalismScore } from "@/lib/api/formatters";
import { useArticleQuery } from "@/lib/api/queries";
import { useArticleAnalysisQuery, useViewerQuery } from "@/lib/api/queries";
import { ArticleDwellTracker } from "@/features/reading/article-dwell-tracker";

export function RealArticleDetail({ articleId }: { articleId: string }) {
  const query = useArticleQuery(articleId);
  const analysis = useArticleAnalysisQuery(articleId);
  const viewer = useViewerQuery();
  if (query.isPending) return <StatePanel state="loading" />;
  if (query.isError) return <StatePanel state="error" />;
  const article = query.data;
  const ready = article.analysisStatus === "READY";

  return (
    <>
      {viewer.data ? <ArticleDwellTracker articleId={article.id} /> : null}
      <div className="article-layout">
        <article className="card article-main">
          <div className="news-card__meta"><Badge>{article.source}</Badge><span>{formatPublishedDate(article.publishedAt)}</span>{ready ? <><Badge tone="info">{article.scoreVersion}</Badge><Badge>LLM 평가 편향 · {formatBiasScore(article.x)}</Badge><Badge>LLM 평가 과장성 · {formatSensationalismScore(article.sensationalism)}</Badge></> : <Badge tone="warning">분석 준비 중</Badge>}</div>
          <h1>{article.title}</h1>
          {article.dek && <p className="article-main__dek">{article.dek}</p>}
          <div className="notice"><Info size={15} aria-hidden="true" /> 편향성과 과장성 평가는 사실성이나 기사 품질 판정이 아닙니다. 아래에는 원문을 대체하지 않는 제한 공개 근거만 표시합니다.</div>
          {ready ? <p>분석 신뢰도 {formatConfidence(article.confidence)}</p> : <StatePanel state={article.analysisStatus === "UNTRUSTED" ? "partial" : "processing"} />}
          {ready && article.confidence < 0.6 ? <div className="notice">분석 신뢰도가 낮아 점수를 확정적 판단으로 해석하면 안 됩니다.</div> : null}
          <div className="section-head"><h2>AI 분석 기록</h2><span className="badge">제한 공개</span></div>
          {analysis.isPending ? <StatePanel state="loading" /> : analysis.isError ? <StatePanel state="error" onRetry={() => void analysis.refetch()} /> : analysis.data.assessments.assessments.length === 0 ? <StatePanel state="processing" /> : <div className="article-analysis-list">{analysis.data.assessments.assessments.map((assessment, index) => {
            const evidence = Array.isArray(assessment.evidence) ? assessment.evidence : [];
            return <section className="article-analysis-record" key={String(assessment.id ?? index)}><div className="article-analysis-record__head"><Badge tone={evidence.length ? "positive" : "warning"}>{evidence.length ? "공개 근거 있음" : "공개 근거 없음"}</Badge><span>{String(assessment.model_alias ?? "모델 별칭 없음")}</span></div><h3>{String(assessment.summary ?? `분석 ${index + 1}`)}</h3>{evidence.length === 0 ? <p className="article-analysis-record__limitation">점수는 생성됐지만 공개 가능한 근거 인용이 함께 제공되지 않았습니다. 이 결과를 단독 근거로 해석하지 마세요.</p> : null}<p className="article-analysis-record__meta"><span>신뢰도 {String(assessment.confidence ?? "미측정")}</span><span>{String(assessment.prompt_version ?? "prompt 미확인")}</span><span>{String(assessment.actual_model_id ?? "모델 ID 비공개")}</span><time>{formatPublishedDate(String(assessment.created_at ?? ""))}</time></p></section>;
          })}</div>}
          <div className="section-head"><h2>점수 정정·버전 이력</h2></div>
          {analysis.data && <div className="table-wrap"><table className="data-table"><thead><tr><th>버전</th><th>편향성</th><th>과장성</th><th>생성 시각</th></tr></thead><tbody>{analysis.data.history.items.map((entry, index) => <tr key={String(entry.id ?? index)}><td data-label="버전">{String(entry.score_version_id ?? entry.id ?? index + 1)}</td><td data-label="편향성">{String(entry.x ?? "—")}</td><td data-label="과장성">{String(entry.sensationalism ?? "미측정")}</td><td data-label="생성 시각">{String(entry.created_at ?? "—")}</td></tr>)}</tbody></table></div>}
        </article>
        <aside className="card article-side" aria-label="기사 관점 분석">
          {ready ? <><div className="axis" aria-label={`편향성 ${formatBiasScore(article.x)}`}>
            <div className="axis__head"><strong>편향성</strong><span>{formatBiasScore(article.x)}</span></div>
            <div className="axis__labels"><span>− 좌편향</span><span>+ 우편향</span></div>
            <div className="axis__track" aria-hidden="true"><span className="axis__center" /><span className="axis__marker" style={{ left: `${(clampScore(article.x) + 100) / 2}%` }} /></div>
          </div>
          <div className="axis" aria-label={`과장성 ${formatSensationalismScore(article.sensationalism)}`}>
            <div className="axis__head"><strong>과장성</strong><span>{formatSensationalismScore(article.sensationalism)}</span></div>
            <div className="axis__labels"><span>낮음</span><span>높음</span></div>
            {article.sensationalism === null ? <small>이 버전에는 과장성 측정값이 없습니다.</small> : <div className="axis__track" aria-hidden="true"><span className="axis__marker" style={{ left: `${clampScore(article.sensationalism, 0, 100)}%` }} /></div>}
            <small>허위 판정이 아닌 표현 강도 평가</small>
          </div></> : <StatePanel state={article.analysisStatus === "UNTRUSTED" ? "partial" : "processing"} />}
          <a className="external-link" href={article.originalUrl} target="_blank" rel="noreferrer">언론사 원문 새 창에서 보기 <ExternalLink size={15} /></a>
        </aside>
      </div>
      <div style={{ marginTop: "1rem" }}><VoteForm articleId={article.id} /></div>
    </>
  );
}
