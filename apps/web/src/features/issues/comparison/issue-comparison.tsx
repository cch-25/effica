"use client";

import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Check, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { StatePanel } from "@/components/ui/state-panel";
import { ApiError } from "@/lib/api/client";
import {
  formatBiasScore,
  formatConfidence,
  formatPublishedDate,
  formatSensationalismScore,
} from "@/lib/api/formatters";
import { useIssueComparisonQuery } from "@/lib/api/queries";
import type { Article, Issue } from "@/lib/api/types";
import { parseComparisonSelection } from "./selection";
import { IssueReadiness } from "../issue-readiness";
import { DefinitionTooltip } from "@/components/ui/definition-tooltip";
import { analysisTerms } from "@/lib/content/analysis-terms";

function replaceArticleQuery(pathname: string, articleIds: string[]): string {
  const params = new URLSearchParams();
  params.set("articles", articleIds.join(","));
  return `${pathname}?${params}`;
}

function scorePosition(value: number, minimum: number, maximum: number): string {
  const bounded = Math.min(maximum, Math.max(minimum, value));
  return `${((bounded - minimum) / (maximum - minimum)) * 100}%`;
}

function ScoreScale({ label, value, kind }: { label: string; value: number; kind: "bias" | "intensity" }) {
  const bias = kind === "bias";
  const definition = bias ? analysisTerms.bias : analysisTerms.sensationalism;
  return (
    <div className="comparison-score">
      <div className="comparison-score__head">
        <DefinitionTooltip label={label} description={definition.description} />
        <strong>{bias ? formatBiasScore(value) : formatSensationalismScore(value)}</strong>
      </div>
      <div className={`comparison-score__track comparison-score__track--${kind}`} aria-hidden="true">
        <i style={{ left: scorePosition(value, bias ? -100 : 0, 100) }} />
      </div>
      <div className="comparison-score__axis" aria-hidden="true">
        <span>{bias ? "좌편향" : "낮음"}</span>
        {bias ? <span>중립</span> : null}
        <span>{bias ? "우편향" : "높음"}</span>
      </div>
    </div>
  );
}

function hasPublicScore(article: Article): boolean {
  return article.analysisStatus === "READY"
    && article.analysisProvider === "openai"
    && article.sensationalism !== null;
}

function PendingReviewComparison({ articles }: { articles: Article[] }) {
  return (
    <section className="comparison-results comparison-results--pending" aria-labelledby="pending-comparison-title">
      <div className="comparison-results__head">
        <div className="comparison-section-title">
          <h2 id="pending-comparison-title">기사별 AI 분석 비교</h2>
        </div>
        <p>공통 사실과 보도 프레임은 편집 검수 후 공개됩니다.</p>
      </div>
      <section className="comparison-grid" data-columns={articles.length} aria-label="선택한 기사별 공개 분석 비교">
        {articles.map((article) => {
          const scoreReady = hasPublicScore(article);
          return (
            <article className="comparison-column" key={article.id} aria-labelledby={`pending-article-${article.id}`}>
              <header className="comparison-column__header">
                <div className="comparison-column__source">
                  <span><strong>{article.source}</strong><time dateTime={article.publishedAt || undefined}>{formatPublishedDate(article.publishedAt)}</time></span>
                  <a className="comparison-column__original" href={article.originalUrl} target="_blank" rel="noreferrer" aria-label={`${article.source} 기사 원문 보기, 새 창`}>원문 보기 <ExternalLink size={14} aria-hidden="true" /></a>
                </div>
                <h3 id={`pending-article-${article.id}`}>{article.title}</h3>
              </header>
              <div className="comparison-column__frame">
                <span>기사 요약</span>
                <p>{article.dek || "기사 요약을 준비하고 있습니다."}</p>
              </div>
              {scoreReady ? (
                <div className="comparison-column__scores">
                  <ScoreScale label="편향성" value={article.x} kind="bias" />
                  <ScoreScale label="과장성" value={article.sensationalism ?? 0} kind="intensity" />
                  <p className="comparison-column__confidence">분석 신뢰도 {formatConfidence(article.confidence)}</p>
                </div>
              ) : (
                <p className="comparison-column__pending-score">신뢰할 수 있는 기사별 AI 점수를 준비하고 있습니다.</p>
              )}
            </article>
          );
        })}
      </section>
      <p className="comparison-results__note">기사별 점수는 이미 공개 검증을 통과한 분석만 표시하며, 사실 여부나 기사 품질을 판정하지 않습니다.</p>
    </section>
  );
}

export function IssueComparison({
  issue,
  articles,
  initialArticles,
}: {
  issue: Issue;
  articles: Article[];
  initialArticles?: string;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const parsed = useMemo(
    () => parseComparisonSelection(initialArticles, articles),
    [articles, initialArticles],
  );
  const [selected, setSelected] = useState(parsed.selected);
  const [selectionMessage, setSelectionMessage] = useState(
    parsed.error === "TOO_MANY" ? "기사는 최대 4개까지 비교할 수 있습니다." : "",
  );
  const comparison = useIssueComparisonQuery(issue.id, selected);

  useEffect(() => {
    if (parsed.correctionNeeded && parsed.selected.length >= 2) {
      router.replace(replaceArticleQuery(pathname, parsed.selected), { scroll: false });
    }
  }, [parsed, pathname, router]);

  const updateSelection = (articleId: string) => {
    const included = selected.includes(articleId);
    if (included && selected.length <= 2) {
      setSelectionMessage("비교할 기사 2개는 남겨야 합니다.");
      return;
    }
    if (!included && selected.length >= 4) {
      setSelectionMessage("기사는 최대 4개까지 비교할 수 있습니다.");
      return;
    }
    const next = included
      ? selected.filter((id) => id !== articleId)
      : [...selected, articleId];
    setSelected(next);
    setSelectionMessage("");
    router.replace(replaceArticleQuery(pathname, next), { scroll: false });
  };

  const snapshot = comparison.data;
  const comparisonIsPreparing = comparison.error instanceof ApiError
    && comparison.error.body.error.code === "COMPARISON_NOT_READY";
  const dataAsOf = snapshot?.issue.data_as_of ?? issue.dataAsOf;
  const comparedArticles = snapshot
    ? [...snapshot.articles].sort((left, right) => selected.indexOf(left.article.id) - selected.indexOf(right.article.id))
    : [];
  const selectedArticles = selected
    .map((articleId) => articles.find((article) => article.id === articleId))
    .filter((article): article is Article => article !== undefined);

  return (
    <div className="issue-comparison">
      <header className="comparison-hero">
        <p className="eyebrow">하나의 사건 · 여러 보도</p>
        <h1>{issue.title}</h1>
        <p className="comparison-hero__meta">
          기사 {snapshot?.issue.article_count ?? issue.articleIds.length}개
          <span aria-hidden="true">·</span>
          출처 {snapshot?.issue.source_count ?? issue.sourceCount}곳
          {dataAsOf ? <><span aria-hidden="true">·</span>{formatPublishedDate(dataAsOf)} 기준</> : null}
        </p>
      </header>

      <section className="comparison-selector" aria-labelledby="comparison-selector-title">
        <div className="comparison-section-title">
          <h2 id="comparison-selector-title">비교할 기사</h2>
          <span>{selected.length}개 선택</span>
        </div>
        <p className="comparison-selector__hint">준비된 기사 중 2개에서 4개까지 선택해 관점을 나란히 비교합니다.</p>
        <div className="comparison-selector__list" role="group" aria-label="비교할 기사">
          {articles.map((article) => {
            const checked = selected.includes(article.id);
            return (
              <div className="comparison-selector__row" key={article.id}>
                <Button
                  variant="secondary"
                  className="comparison-selector__item"
                  aria-label={`${article.source} 기사 ${checked ? "비교에서 제외하기" : "비교에 추가하기"}`}
                  aria-pressed={checked}
                  data-selected={checked ? "" : undefined}
                  onClick={() => updateSelection(article.id)}
                >
                  <span className="comparison-selector__copy">
                    <strong>{article.source}</strong>
                    <small>{article.title}</small>
                  </span>
                  <span className="comparison-selector__check" aria-hidden="true"><Check size={16} strokeWidth={2.5} /></span>
                </Button>
                {!snapshot ? <a className="comparison-selector__original" href={article.originalUrl} target="_blank" rel="noreferrer" aria-label={`${article.source} 기사 원문 보기, 새 창`}>원문 보기 <ExternalLink size={14} aria-hidden="true" /></a> : null}
              </div>
            );
          })}
        </div>
        {selectionMessage ? <p className="comparison-selector__status" role="status">{selectionMessage}</p> : null}
      </section>

      {selected.length < 2 ? (
        <p className="notice">비교할 기사를 2개 이상 선택해 주세요.</p>
      ) : comparison.isPending ? (
        <StatePanel state="loading" />
      ) : comparisonIsPreparing ? (
        <>
          <PendingReviewComparison articles={selectedArticles} />
          <IssueReadiness articleCount={issue.articleIds.length} sourceCount={issue.sourceCount} />
        </>
      ) : comparison.isError ? (
        <StatePanel state="error" onRetry={() => void comparison.refetch()} />
      ) : snapshot ? (
        <>
          <section className="common-facts" aria-labelledby="common-facts-title">
            <div className="comparison-section-title">
              <h2 id="common-facts-title">공통으로 확인된 사실</h2>
            </div>
            {snapshot.common_facts.length ? (
              <ul>{snapshot.common_facts.map((fact) => <li key={fact.id}>{fact.text}</li>)}</ul>
            ) : <p className="notice">공통으로 확인된 사실이 아직 없습니다.</p>}
          </section>

          <section className="comparison-results" aria-labelledby="comparison-results-title">
            <div className="comparison-results__head">
              <div className="comparison-section-title">
                <h2 id="comparison-results-title">보도별 관점</h2>
              </div>
              <p>편향성은 좌우 관점, 과장성은 표현 강도입니다.</p>
            </div>

            <section className="comparison-grid" data-columns={comparedArticles.length} aria-label="선택한 기사 비교">
              {comparedArticles.map(({ article, score, assessment, frame, vote_aggregate }) => (
                <article className="comparison-column" key={article.id} aria-labelledby={`comparison-article-${article.id}`}>
                  <header className="comparison-column__header">
                    <div className="comparison-column__source">
                      <span><strong>{article.source}</strong><time dateTime={article.published_at ?? undefined}>{formatPublishedDate(article.published_at ?? "")}</time></span>
                      <a className="comparison-column__original" href={article.canonical_url} target="_blank" rel="noreferrer" aria-label={`${article.source} 기사 원문 보기, 새 창`}>원문 보기 <ExternalLink size={14} aria-hidden="true" /></a>
                    </div>
                    <h3 id={`comparison-article-${article.id}`}>{article.title}</h3>
                  </header>

                  <div className="comparison-column__frame">
                    <span>핵심 관점</span>
                    <p>{frame.headline_frame || "분석할 근거가 부족합니다."}</p>
                    {frame.emphasis.length > 0 ? <p className="comparison-column__emphasis">{frame.emphasis.join(" · ")}</p> : null}
                  </div>

                  <div className="comparison-column__analysis">
                    <span>AI 분석 요약</span>
                    <p>{assessment.summary || "공개할 분석 요약이 없습니다."}</p>
                    {frame.omissions_note ? <><span>기사에서 확인되지 않은 내용</span><p>{frame.omissions_note}</p></> : null}
                    <details>
                      <summary>근거와 분석 정보</summary>
                      <p>{frame.evidence_refs.length ? frame.evidence_refs.join(" · ") : "공개 가능한 근거 참조가 없습니다."}</p>
                      <small>{assessment.model_alias} / {assessment.actual_model_id} · {assessment.prompt_version}</small>
                    </details>
                  </div>

                  <div className="comparison-column__scores">
                    <ScoreScale label="편향성" value={score.x} kind="bias" />
                    <ScoreScale label="과장성" value={score.sensationalism} kind="intensity" />
                    <p className="comparison-column__confidence">분석 신뢰도 {formatConfidence(score.confidence)}</p>
                  </div>
                  <div className="comparison-column__reader" aria-label="독자 평가 집계">
                    <span>독자 평가 · AI 평가와 별도</span>
                    {vote_aggregate.status === "pending" ? <p>집계 반영 중</p> : vote_aggregate.qualified_count === 0 ? <p>아직 공개할 독자 집계가 없습니다.</p> : <p>편향성 {vote_aggregate.qualified.x === null ? "미측정" : formatBiasScore(vote_aggregate.qualified.x)} · 과장성 {formatSensationalismScore(vote_aggregate.qualified.sensationalism)}</p>}
                    {vote_aggregate.small_segments_suppressed ? <small>작은 집단의 세부 결과는 공개하지 않습니다.</small> : null}
                  </div>
                  <nav className="comparison-column__actions" aria-label={`${article.source} 기사 이동`}>
                    <a href={article.canonical_url} target="_blank" rel="noreferrer">원문 <ExternalLink size={14} aria-hidden="true" /></a>
                    <Link href={`/articles/${article.id}`}>상세 분석</Link>
                  </nav>
                </article>
              ))}
            </section>
            <p className="comparison-results__note">점수는 사실 여부나 기사 품질을 판정하지 않습니다.</p>
            <footer className="comparison-provenance">비교 {snapshot.comparison_version} · {snapshot.model_alias} / {snapshot.actual_model_id} · {snapshot.prompt_version} · 편집 검수 {formatPublishedDate(snapshot.reviewed_at)}</footer>
          </section>
        </>
      ) : null}
    </div>
  );
}
