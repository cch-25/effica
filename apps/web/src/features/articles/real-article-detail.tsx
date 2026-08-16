"use client";

import { ExternalLink } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { ScoreAxis } from "@/components/ui/score-axis";
import { StatePanel } from "@/components/ui/state-panel";
import { VoteForm } from "@/features/voting/vote-form";
import { formatConfidence } from "@/lib/api/formatters";
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
          <div className="news-card__meta"><Badge>{article.source}</Badge><Badge tone="info">{article.scoreVersion}</Badge></div>
          <h1>{article.title}</h1>
          {article.dek && <p className="article-main__dek">{article.dek}</p>}
          <p>분석 신뢰도 {formatConfidence(article.confidence)}</p>
        </article>
        <aside className="card article-side" aria-label="기사 관점 분석">
          <ScoreAxis axis="x" value={article.x} />
          <ScoreAxis axis="y" value={article.y} />
          <ScoreAxis axis="z" value={article.z} />
          <a className="external-link" href={article.originalUrl} target="_blank" rel="noreferrer">언론사 원문 새 창에서 보기 <ExternalLink size={15} /></a>
        </aside>
      </div>
      <div style={{ marginTop: "1rem" }}><VoteForm articleId={article.id} /></div>
    </>
  );
}
