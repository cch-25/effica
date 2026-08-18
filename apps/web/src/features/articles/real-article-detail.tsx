"use client";

import { ExternalLink } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { StatePanel } from "@/components/ui/state-panel";
import { VoteForm } from "@/features/voting/vote-form";
import { clampScore, formatBiasScore, formatConfidence, formatSensationalismScore } from "@/lib/api/formatters";
import { useArticleQuery } from "@/lib/api/queries";
import { useArticleAnalysisQuery } from "@/lib/api/queries";
import { ReadActions } from "@/features/reading/read-actions";

export function RealArticleDetail({ articleId }: { articleId: string }) {
  const query = useArticleQuery(articleId);
  const analysis = useArticleAnalysisQuery(articleId);
  if (query.isPending) return <StatePanel state="loading" />;
  if (query.isError) return <StatePanel state="error" />;
  const article = query.data;

  return (
    <>
      <div className="article-layout">
        <article className="card article-main">
          <div className="news-card__meta"><Badge>{article.source}</Badge><Badge tone="info">{article.scoreVersion}</Badge><Badge>LLM 평가 편향 · {formatBiasScore(article.x)}</Badge><Badge>LLM 평가 과장성 · {formatSensationalismScore(article.sensationalism)}</Badge></div>
          <h1>{article.title}</h1>
          {article.dek && <p className="article-main__dek">{article.dek}</p>}
          <p>분석 신뢰도 {formatConfidence(article.confidence)}</p>
          <div className="section-head"><h2>모델별 제한 공개 분석</h2><Badge tone="info">{analysis.data?.assessments.article_version_id ?? "불러오는 중"}</Badge></div>
          {analysis.isPending ? <StatePanel state="loading" /> : analysis.isError ? <StatePanel state="error" onRetry={() => void analysis.refetch()} /> : analysis.data.assessments.assessments.length === 0 ? <StatePanel state="empty" /> : <div className="grid grid--2">{analysis.data.assessments.assessments.map((assessment, index) => <section className="card card--padded" key={String(assessment.id ?? index)}><Badge>{String(assessment.status ?? assessment.model_alias ?? "assessment")}</Badge><h3>{String(assessment.summary ?? assessment.label ?? `분석 ${index + 1}`)}</h3><small>{String(assessment.model_alias ?? assessment.model_alias_id ?? "모델 정보 없음")}</small></section>)}</div>}
          <div className="section-head"><h2>점수 정정·버전 이력</h2></div>
          {analysis.data && <div className="table-wrap"><table className="data-table"><thead><tr><th>버전</th><th>편향성</th><th>과장성</th><th>생성 시각</th></tr></thead><tbody>{analysis.data.history.items.map((entry, index) => <tr key={String(entry.id ?? index)}><td>{String(entry.score_version_id ?? entry.id ?? index + 1)}</td><td>{String(entry.x ?? "—")}</td><td>{String(entry.sensationalism ?? "미측정")}</td><td>{String(entry.created_at ?? "—")}</td></tr>)}</tbody></table></div>}
        </article>
        <aside className="card article-side" aria-label="기사 관점 분석">
          <div className="axis" aria-label={`편향성 ${formatBiasScore(article.x)}`}>
            <div className="axis__head"><strong>편향성</strong><span>{formatBiasScore(article.x)}</span></div>
            <div className="axis__labels"><span>− 좌편향</span><span>+ 우편향</span></div>
            <div className="axis__track" aria-hidden="true"><span className="axis__center" /><span className="axis__marker" style={{ left: `${(clampScore(article.x) + 100) / 2}%` }} /></div>
          </div>
          <div className="axis" aria-label={`과장성 ${formatSensationalismScore(article.sensationalism)}`}>
            <div className="axis__head"><strong>과장성</strong><span>{formatSensationalismScore(article.sensationalism)}</span></div>
            <div className="axis__labels"><span>낮음</span><span>높음</span></div>
            {article.sensationalism === null ? <small>이 버전에는 과장성 측정값이 없습니다.</small> : <div className="axis__track" aria-hidden="true"><span className="axis__marker" style={{ left: `${clampScore(article.sensationalism, 0, 100)}%` }} /></div>}
            <small>허위 판정이 아닌 표현 강도 평가</small>
          </div>
          <a className="external-link" href={article.originalUrl} target="_blank" rel="noreferrer">언론사 원문 새 창에서 보기 <ExternalLink size={15} /></a>
          <ReadActions articleId={article.id} originalUrl={article.originalUrl} />
        </aside>
      </div>
      <div style={{ marginTop: "1rem" }}><VoteForm articleId={article.id} /></div>
    </>
  );
}
