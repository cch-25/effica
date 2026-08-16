import Link from "next/link";
import { ArrowUpRight, Clock3 } from "lucide-react";
import type { Article } from "@/lib/api/types";
import { reasonLabels } from "@/mocks/fixtures/content";
import { Badge } from "@/components/ui/badge";
import { formatBiasScore, formatConfidence, formatSensationalismScore } from "@/lib/api/formatters";

export function ArticleCard({ article }: { article: Article }) {
  return (
    <article className="card news-card">
      <div className="news-card__meta"><Badge tone="info">{reasonLabels[article.reasonCode]}</Badge><Badge>LLM 평가 편향 · {formatBiasScore(article.x)}</Badge><Badge>LLM 평가 과장성 · {formatSensationalismScore(article.sensationalism)}</Badge><span>{article.source}</span><span><Clock3 size={12} aria-hidden="true" /> 8분</span></div>
      <h3><Link href={`/articles/${article.id}`}>{article.title}</Link></h3>
      <p>{article.dek}</p>
      <div className="news-card__footer"><span>분석 신뢰도 {formatConfidence(article.confidence)}</span><Link href={`/articles/${article.id}`} aria-label={`${article.title} 분석 보기`}>분석 보기 <ArrowUpRight size={14} aria-hidden="true" /></Link></div>
    </article>
  );
}
