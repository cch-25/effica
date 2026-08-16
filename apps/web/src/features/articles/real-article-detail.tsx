"use client";

import { ExternalLink } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { StatePanel } from "@/components/ui/state-panel";
import { VoteForm } from "@/features/voting/vote-form";
import { clampScore, formatBiasScore, formatConfidence, formatSensationalismScore } from "@/lib/api/formatters";
import { useArticleQuery } from "@/lib/api/queries";

export function RealArticleDetail({ articleId }: { articleId: string }) {
  const query = useArticleQuery(articleId);
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
            <div className="axis__track" aria-hidden="true"><span className="axis__marker" style={{ left: `${clampScore(article.sensationalism, 0, 100)}%` }} /></div>
            <small>허위 판정이 아닌 표현 강도 평가</small>
          </div>
          <a className="external-link" href={article.originalUrl} target="_blank" rel="noreferrer">언론사 원문 새 창에서 보기 <ExternalLink size={15} /></a>
        </aside>
      </div>
      <div style={{ marginTop: "1rem" }}><VoteForm articleId={article.id} /></div>
    </>
  );
}
