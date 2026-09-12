"use client";

import { ArrowLeft, ExternalLink } from "lucide-react";
import Link from "next/link";
import { ApiError } from "@/lib/api/client";
import { Badge } from "@/components/ui/badge";
import { StatePanel } from "@/components/ui/state-panel";
import { VoteForm } from "@/features/voting/vote-form";
import { clampScore, formatBiasScore, formatConfidence, formatPublishedDate, formatSensationalismScore } from "@/lib/api/formatters";
import { useArticleQuery } from "@/lib/api/queries";
import { useArticleAnalysisQuery, useViewerQuery } from "@/lib/api/queries";
import { ArticleDwellTracker } from "@/features/reading/article-dwell-tracker";
import { ButtonLink } from "@/components/ui/button";
import { AnalysisReadinessNotice } from "./analysis-readiness-notice";
import { ArticlePerspectiveMap } from "./article-perspective-map";

function AnalysisStatusNotice({ status, articleId }: { status: "READY" | "PROCESSING" | "PARTIAL" | "UNTRUSTED"; articleId: string }) {
  if (status === "PROCESSING") return <AnalysisReadinessNotice articleId={articleId} />;
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
  if (query.error instanceof ApiError && [404, 410].includes(query.error.status)) return <section className="issue-readiness" role="status"><div><h1>현재 공개되지 않는 기사입니다.</h1><p>소속 이슈의 발행 목록이 바뀌었거나 공개 기간이 지났습니다.</p><Link href="/issues">현재 이슈 보기</Link></div></section>;
  if (query.isPending) return <StatePanel state="loading" />;
  if (query.isError) return <StatePanel state="error" />;
  const article = query.data;
  const ready = article.analysisStatus === "READY";

  return (
    <>
      {viewer.data ? <ArticleDwellTracker articleId={article.id} /> : null}
      <nav className="content-path" aria-label="현재 콘텐츠 경로"><Link href="/articles">기사 모음</Link>{article.issueId !== "unclustered" && <><span aria-hidden="true">/</span><Link href={`/issues/${article.issueId}`}>이슈 비교</Link></>}<span aria-hidden="true">/</span><span aria-current="page">기사 분석</span></nav>
      <div className="article-layout">
        <article className="card article-main">
          <div className="news-card__meta"><Badge>{article.source}</Badge><span>{formatPublishedDate(article.publishedAt)}</span>{!ready ? <Badge tone="warning">{article.analysisStatus === "UNTRUSTED" ? "분석 미제공" : article.analysisStatus === "PARTIAL" ? "일부 분석 공개" : "분석 대기 상태 확인"}</Badge> : null}</div>
          <h1>{article.title}</h1>
          {article.originalUrl && <a className="text-link" href={article.originalUrl} target="_blank" rel="noreferrer">언론사 원문 읽기 <ExternalLink size={15} aria-hidden="true" /><span className="sr-only"> (새 탭)</span></a>}
          {article.dek && <p className="article-main__dek">{article.dek}</p>}
          {ready ? <p className="article-analysis-confidence"><span>분석 신뢰도</span><strong>{formatConfidence(article.confidence)}</strong></p> : <AnalysisStatusNotice status={article.analysisStatus} articleId={articleId} />}
          <details className="article-analysis-details"><summary>분석에 사용한 근거 보기</summary>
            {analysis.isPending ? <p>근거를 불러오는 중입니다.</p> : analysis.isError ? <StatePanel state="error" onRetry={() => void analysis.refetch()} /> : analysis.data.assessments.assessments.map((assessment, index) => {
              const evidence = Array.isArray(assessment.evidence) ? assessment.evidence : [];
              return <section key={String(assessment.id ?? index)}>{evidence.length ? <ul className="claim-list">{evidence.map((item, i) => <li key={i}><p>{String(item.quote ?? item.text ?? "")}</p>{(item.rationale || item.reason) && <p>{String(item.rationale ?? item.reason)}</p>}</li>)}</ul> : <p>추가로 공개된 인용 근거가 없습니다.</p>}<p>분석 시각 {formatPublishedDate(String(assessment.created_at ?? ""))}</p></section>;
            })}
          </details>
        </article>
        <aside className="card article-side" aria-label="기사 관점 분석">
          {ready ? <><div className="axis" aria-label={`편향성 ${formatBiasScore(article.x)}`}>
            <div className="axis__head"><span>편향성</span><span>{formatBiasScore(article.x)}</span></div>
            <div className="axis__labels"><span>− 좌편향</span><span>+ 우편향</span></div>
            <div className="axis__track" aria-hidden="true"><span className="axis__center" /><span className="axis__marker" style={{ left: `${(clampScore(article.x) + 100) / 2}%` }} /></div>
          </div>
          <div className="axis" aria-label={`과장성 ${formatSensationalismScore(article.sensationalism)}`}>
            <div className="axis__head"><span>과장성</span><span>{formatSensationalismScore(article.sensationalism)}</span></div>
            <div className="axis__labels"><span>낮음</span><span>높음</span></div>
            {article.sensationalism === null ? <small>이 버전에는 과장성 측정값이 없습니다.</small> : <div className="axis__track" aria-hidden="true"><span className="axis__marker" style={{ left: `${clampScore(article.sensationalism, 0, 100)}%` }} /></div>}
            <small>점수는 관점과 표현 강도를 나타내며 사실 여부나 기사 품질을 판정하지 않습니다.</small>
          </div></> : <p>공개 기준을 충족한 분석 결과가 준비되면 이곳에 점수가 표시됩니다.</p>}

          {article.issueId !== "unclustered" ? <ButtonLink variant="secondary" href={`/issues/${article.issueId}`}><ArrowLeft size={15} aria-hidden="true" /> 같은 이슈의 보도 비교</ButtonLink> : null}
        </aside>
      </div>
      <ArticlePerspectiveMap article={article} />
      <div style={{ marginTop: "1rem" }}><VoteForm articleId={article.id} /></div>
    </>
  );
}
