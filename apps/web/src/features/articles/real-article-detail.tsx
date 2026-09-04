"use client";

import { ArrowLeft, ExternalLink, Info } from "lucide-react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { StatePanel } from "@/components/ui/state-panel";
import { VoteForm } from "@/features/voting/vote-form";
import { clampScore, formatBiasScore, formatConfidence, formatPublishedDate, formatSensationalismScore } from "@/lib/api/formatters";
import { useArticleQuery } from "@/lib/api/queries";
import { useArticleAnalysisQuery, useViewerQuery } from "@/lib/api/queries";
import { ArticleDwellTracker } from "@/features/reading/article-dwell-tracker";
import { DefinitionTooltip } from "@/components/ui/definition-tooltip";
import { analysisTerms } from "@/lib/content/analysis-terms";
import { ButtonLink } from "@/components/ui/button";

function AnalysisStatusNotice({ status }: { status: "READY" | "PROCESSING" | "PARTIAL" | "UNTRUSTED" }) {
  const content = status === "UNTRUSTED"
    ? { title: "점수를 표시하지 않습니다.", description: "공개 신뢰 기준을 충족하지 못한 분석입니다." }
    : status === "PARTIAL"
      ? { title: "일부 분석만 확인할 수 있습니다.", description: "나머지 근거와 점수가 준비되면 상태가 갱신됩니다." }
      : { title: "AI 분석을 준비하고 있습니다.", description: "완료되기 전에는 점수를 표시하지 않습니다." };
  return <div className="notice" role="status"><strong>{content.title}</strong><p>{content.description}</p></div>;
}

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
      <nav className="content-path" aria-label="현재 콘텐츠 경로"><Link href={`/issues/${article.issueId}`}>이슈 비교</Link><span aria-hidden="true">/</span><span aria-current="page">기사 분석</span></nav>
      <div className="article-layout">
        <article className="card article-main">
          <div className="news-card__meta"><Badge>{article.source}</Badge><span>{formatPublishedDate(article.publishedAt)}</span>{!ready ? <Badge tone="warning">분석 준비 중</Badge> : null}</div>
          <h1>{article.title}</h1>
          {article.dek && <p className="article-main__dek">{article.dek}</p>}
          <div className="notice"><Info size={15} aria-hidden="true" /> 편향성과 과장성 점수는 기사의 사실 여부나 품질을 판정하지 않습니다. 각 분석 기록에서 공개 근거 제공 여부를 확인할 수 있으며, 기사 전체 내용은 원문에서 확인해 주세요.</div>
          {ready ? <p className="article-analysis-confidence"><DefinitionTooltip {...analysisTerms.confidence} /><strong>{formatConfidence(article.confidence)}</strong></p> : <AnalysisStatusNotice status={article.analysisStatus} />}
          {ready && article.confidence < 0.6 ? <div className="notice">분석 신뢰도가 낮아 점수를 확정적 판단으로 해석하면 안 됩니다.</div> : null}
          <div className="section-head"><h2>AI 분석 기록</h2><span className="badge">제한 공개</span></div>
          {analysis.isPending ? <StatePanel state="loading" /> : analysis.isError ? <StatePanel state="error" onRetry={() => void analysis.refetch()} /> : analysis.data.assessments.assessments.length === 0 ? <p className="notice">공개할 수 있는 AI 분석 기록이 없습니다. 원문과 다른 보도를 함께 확인해 주세요.</p> : <div className="article-analysis-list">{analysis.data.assessments.assessments.map((assessment, index) => {
            const evidence = Array.isArray(assessment.evidence) ? assessment.evidence : [];
            const evidenceQuotes = evidence.map((item) => String(item.quote ?? item.text ?? "근거 상세 비공개"));
            return <section className="article-analysis-record" key={String(assessment.id ?? index)}><div className="article-analysis-record__head"><Badge tone={evidence.length ? "positive" : "warning"}>{evidence.length ? "공개 근거 있음" : "공개 근거 없음"}</Badge><span>AI 분석 기록 {index + 1}</span></div><h3>{String(assessment.summary ?? `분석 ${index + 1}`)}</h3>{evidenceQuotes.length ? <ul className="claim-list" aria-label="공개된 분석 근거">{evidenceQuotes.map((quote, evidenceIndex) => <li key={`${index}-${evidenceIndex}`}>{quote}</li>)}</ul> : <p className="article-analysis-record__limitation">점수는 생성됐지만 공개 가능한 근거 인용이 함께 제공되지 않았습니다. 이 결과를 단독 근거로 해석하지 마세요.</p>}<p className="article-analysis-record__meta"><span><DefinitionTooltip {...analysisTerms.confidence} /> {String(assessment.confidence ?? "미측정")}</span><time>{formatPublishedDate(String(assessment.created_at ?? ""))}</time></p><details className="article-analysis-technical"><summary>분석 기술 정보 보기</summary><dl><div><dt>분석 대상 기사 버전</dt><dd>{String(analysis.data?.assessments.article_version_id ?? "확인 중")}</dd></div><div><dt>사용한 AI 모델</dt><dd>{String(assessment.model_alias ?? "별칭 없음")} / {String(assessment.actual_model_id ?? "모델 ID 비공개")}</dd></div><div><dt>분석 기준 버전</dt><dd>{String(assessment.prompt_version ?? "확인 중")}</dd></div></dl></details></section>;
          })}</div>}
          <div className="section-head" id="analysis-history"><h2>분석 점수 수정 이력</h2></div>
          {analysis.data && <div className="table-wrap"><table className="data-table"><thead><tr><th>버전</th><th>편향성</th><th>과장성</th><th>생성 시각</th></tr></thead><tbody>{analysis.data.history.items.map((entry, index) => <tr key={String(entry.id ?? index)}><td data-label="버전">{String(entry.score_version_id ?? entry.id ?? index + 1)}</td><td data-label="편향성">{String(entry.x ?? "확인 불가")}</td><td data-label="과장성">{String(entry.sensationalism ?? "미측정")}</td><td data-label="생성 시각">{String(entry.created_at ?? "확인 불가")}</td></tr>)}</tbody></table></div>}
        </article>
        <aside className="card article-side" aria-label="기사 관점 분석">
          {ready ? <><div className="axis" aria-label={`편향성 ${formatBiasScore(article.x)}`}>
            <div className="axis__head"><DefinitionTooltip {...analysisTerms.bias} /><span>{formatBiasScore(article.x)}</span></div>
            <div className="axis__labels"><span>− 좌편향</span><span>+ 우편향</span></div>
            <div className="axis__track" aria-hidden="true"><span className="axis__center" /><span className="axis__marker" style={{ left: `${(clampScore(article.x) + 100) / 2}%` }} /></div>
          </div>
          <div className="axis" aria-label={`과장성 ${formatSensationalismScore(article.sensationalism)}`}>
            <div className="axis__head"><DefinitionTooltip {...analysisTerms.sensationalism} /><span>{formatSensationalismScore(article.sensationalism)}</span></div>
            <div className="axis__labels"><span>낮음</span><span>높음</span></div>
            {article.sensationalism === null ? <small>이 버전에는 과장성 측정값이 없습니다.</small> : <div className="axis__track" aria-hidden="true"><span className="axis__marker" style={{ left: `${clampScore(article.sensationalism, 0, 100)}%` }} /></div>}
            <small>허위 판정이 아닌 표현 강도 평가</small>
          </div></> : <AnalysisStatusNotice status={article.analysisStatus} />}
          <a className="external-link" href={article.originalUrl} target="_blank" rel="noreferrer">출처 원문 새 창에서 보기 <ExternalLink size={15} /></a>
          {article.issueId !== "unclustered" ? <ButtonLink variant="secondary" href={`/issues/${article.issueId}`}><ArrowLeft size={15} aria-hidden="true" /> 관련 이슈 비교로 돌아가기</ButtonLink> : null}
        </aside>
      </div>
      <div style={{ marginTop: "1rem" }}><VoteForm articleId={article.id} /></div>
    </>
  );
}
