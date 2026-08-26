"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { ExternalLink } from "lucide-react";
import { Badge } from "@/components/ui/badge";
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

function replaceArticleQuery(pathname: string, articleIds: string[]): string {
  const params = new URLSearchParams();
  params.set("articles", articleIds.join(","));
  return `${pathname}?${params}`;
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
    parsed.error === "TOO_MANY" ? "비교할 기사는 최대 4개까지 선택할 수 있습니다." : "",
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
      setSelectionMessage("비교에는 최소 2개의 기사가 필요합니다.");
      return;
    }
    if (!included && selected.length >= 4) {
      setSelectionMessage("비교할 기사는 최대 4개까지 선택할 수 있습니다.");
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
  return (
    <div className="issue-comparison">
      <header className="comparison-hero">
        <div>
          <p className="eyebrow">하나의 사건 · 여러 보도</p>
          <h1>{issue.title}</h1>
          <p className="comparison-hero__summary">{issue.summary}</p>
        </div>
        <dl className="comparison-hero__meta" aria-label="사건 비교 범위">
          <div><dt>기준일</dt><dd>{dataAsOf ? formatPublishedDate(dataAsOf) : "확인 중"}</dd></div>
          <div><dt>포함 기사</dt><dd>{snapshot?.issue.article_count ?? issue.articleIds.length}개</dd></div>
          <div><dt>출처</dt><dd>{snapshot?.issue.source_count ?? issue.sourceCount}곳</dd></div>
        </dl>
      </header>

      <section className="comparison-selector" aria-labelledby="comparison-selector-title">
        <div className="section-head">
          <div><p className="eyebrow">비교 기사 선택</p><h2 id="comparison-selector-title">2개에서 4개까지 나란히 읽기</h2></div>
          <Badge tone="info">현재 {selected.length}개</Badge>
        </div>
        <div className="comparison-selector__list" role="group" aria-label="비교할 기사">
          {articles.map((article, index) => {
            const checked = selected.includes(article.id);
            return (
              <Button
                key={article.id}
                variant="secondary"
                className="comparison-selector__item"
                aria-pressed={checked}
                data-selected={checked ? "" : undefined}
                onClick={() => updateSelection(article.id)}
              >
                <span className="comparison-selector__number">{String(index + 1).padStart(2, "0")}</span>
                <span className="comparison-selector__copy"><strong>{article.source}</strong><small>{article.title}</small></span>
                <span className="comparison-selector__state" aria-hidden="true">{checked ? "선택됨" : "선택"}</span>
              </Button>
            );
          })}
        </div>
        <p className="comparison-selector__status" role="status" aria-live="polite">
          {selectionMessage || "선택은 주소에 저장되어 새로고침하거나 링크를 공유해도 유지됩니다."}
        </p>
      </section>

      {selected.length < 2 ? (
        <div className="notice">비교를 시작하려면 서로 다른 기사 2개 이상을 선택해 주세요.</div>
      ) : comparison.isPending ? (
        <StatePanel state="loading" />
      ) : comparisonIsPreparing ? (
        <StatePanel state="processing" />
      ) : comparison.isError ? (
        <StatePanel state="error" onRetry={() => void comparison.refetch()} />
      ) : snapshot ? (
        <>
          <section className="common-facts" aria-labelledby="common-facts-title">
            <div className="section-head">
              <div><p className="eyebrow">공통 사실</p><h2 id="common-facts-title">보도들이 함께 확인한 사건의 바탕</h2></div>
              <Badge>{snapshot.common_facts.length}개</Badge>
            </div>
            {snapshot.common_facts.length ? (
              <ul>{snapshot.common_facts.map((fact) => <li key={fact.id}>{fact.text}<small>{fact.article_ids.length}개 기사에서 뒷받침</small></li>)}</ul>
            ) : <p className="notice">공통 사실 근거 부족</p>}
          </section>

          <div className="comparison-disclaimer">
            <strong>분석 요약</strong>
            <span>편향성은 사실성·진실성·품질 판정이 아니며, 과장성은 허위 판정이 아닙니다. AI 평가와 독자 집계는 서로 다른 자료입니다.</span>
          </div>

          <section className="comparison-grid" data-columns={snapshot.articles.length} aria-label="선택한 기사 비교">
            {snapshot.articles.map(({ article, score, assessment, frame, vote_aggregate }, index) => (
              <article className="comparison-column" key={article.id} aria-labelledby={`comparison-article-${article.id}`}>
                <p className="comparison-column__index">기사 {String.fromCharCode(65 + index)}</p>
                <div className="comparison-column__source"><Badge>{article.source}</Badge><time dateTime={article.published_at ?? undefined}>{formatPublishedDate(article.published_at ?? "")}</time></div>
                <h3 id={`comparison-article-${article.id}`}>{article.title}</h3>

                <section><h4>핵심 프레임</h4><p>{frame.headline_frame || "근거 부족"}</p>{frame.emphasis.length > 0 && <ul className="tag-list">{frame.emphasis.map((item) => <li key={item}>{item}</li>)}</ul>}</section>
                <section><h4>편향성</h4><strong>{formatBiasScore(score.x)}</strong><small>사실성이나 품질 판정이 아님</small></section>
                <section><h4>과장성</h4><strong>{formatSensationalismScore(score.sensationalism)}</strong><small>허위 여부 판정이 아님</small></section>
                <section><h4>분석 confidence</h4><strong>{formatConfidence(score.confidence)}</strong><small>{formatPublishedDate(score.created_at)} 생성</small></section>
                <section><h4>제한 공개 근거</h4><p>{assessment.summary || "근거 부족"}</p><details><summary>근거 참조와 분석 정보</summary><p>{frame.evidence_refs.length ? frame.evidence_refs.join(" · ") : "근거 참조 부족"}</p><small>{assessment.model_alias} / {assessment.actual_model_id} · {assessment.prompt_version}</small></details></section>
                {frame.omissions_note && <section><h4>기사에서 확인되지 않은 내용</h4><p>{frame.omissions_note}</p></section>}
                <section className="reader-aggregate" aria-label="독자 평가 집계">
                  <h4>독자 평가 · AI 평가와 별도</h4>
                  {vote_aggregate.status === "pending" ? <p aria-live="polite">집계 반영 중</p> : vote_aggregate.qualified_count === 0 ? <p>아직 공개할 독자 집계가 없습니다.</p> : <><p>편향성 {vote_aggregate.qualified.x === null ? "미측정" : formatBiasScore(vote_aggregate.qualified.x)}</p><p>과장성 {formatSensationalismScore(vote_aggregate.qualified.sensationalism)}</p><small>qualified {vote_aggregate.qualified_count}명 · 기준 {vote_aggregate.generated_at ? formatPublishedDate(vote_aggregate.generated_at) : "확인 중"}</small></>}
                  {vote_aggregate.small_segments_suppressed && <small>작은 집단의 세부 결과는 공개하지 않습니다.</small>}
                </section>
                <nav className="comparison-column__actions" aria-label={`${article.source} 기사 이동`}>
                  <a href={article.canonical_url} target="_blank" rel="noreferrer">원문 <ExternalLink size={14} aria-hidden="true" /></a>
                  <Link href={`/articles/${article.id}`}>상세 분석</Link>
                </nav>
              </article>
            ))}
          </section>
          <footer className="comparison-provenance">
            비교 snapshot {snapshot.comparison_version} · {snapshot.model_alias} / {snapshot.actual_model_id} · {snapshot.prompt_version} · 검수 {formatPublishedDate(snapshot.reviewed_at)}
          </footer>
        </>
      ) : null}
    </div>
  );
}
