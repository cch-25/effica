"use client";

import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Check } from "lucide-react";
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
import { publisherIdentity } from "@/lib/api/publisher";
import { isComparisonReadyArticle, parseComparisonSelection } from "./selection";
import { IssueReadiness } from "../issue-readiness";

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
  return (
    <div className="comparison-score">
      <div className="comparison-score__head">
        <span>{label}</span>
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

function PendingReviewComparison({ articles }: { articles: Article[] }) {
  return (
    <section className="comparison-results comparison-results--pending" aria-labelledby="pending-comparison-title">
      <div className="comparison-results__head">
        <div className="comparison-section-title">
          <h2 id="pending-comparison-title">기사별 AI 분석 비교</h2>
        </div>
        <p>기사별 점수를 먼저 비교해 보세요.</p>
      </div>
      <section className="comparison-grid" data-columns={articles.length} aria-label="선택한 기사별 공개 분석 비교">
        {articles.map((article) => {
          return (
            <article className="comparison-column" key={article.id} aria-labelledby={`pending-article-${article.id}`}>
              <header className="comparison-column__header">
                <div className="comparison-column__source">
                  <span><strong>{article.source}</strong><time dateTime={article.publishedAt || undefined}>{formatPublishedDate(article.publishedAt)}</time></span>
                </div>
                <h3 id={`pending-article-${article.id}`}><Link href={`/articles/${article.id}`}>{article.title}</Link></h3>
              </header>
              <div className="comparison-column__scores">
                <ScoreScale label="편향성" value={article.x} kind="bias" />
                <ScoreScale label="과장성" value={article.sensationalism ?? 0} kind="intensity" />
                <p className="comparison-column__confidence">분석 신뢰도 {formatConfidence(article.confidence)}</p>
              </div>
            </article>
          );
        })}
      </section>
      <p className="comparison-results__note">점수는 사실 여부나 기사 품질을 판정하지 않습니다.</p>
    </section>
  );
}

function AcquiredArticles({ articles }: { articles: Article[] }) {
  return (
    <section className="available-articles" aria-labelledby="available-articles-title">
      <div className="comparison-section-title"><h2 id="available-articles-title">확보한 기사</h2><span>{articles.length}개</span></div>
      <ul>{articles.map((article) => <li key={article.id}>
        <span>{article.source} / {isComparisonReadyArticle(article) ? "분석 완료" : "분석 준비 중"}</span>
        <Link href={`/articles/${article.id}`}>{article.title}</Link>
        <a href={article.originalUrl} target="_blank" rel="noreferrer" aria-label={`${article.source} 확보한 기사 원문 보기, 새 창`}>원문 보기</a>
      </li>)}</ul>
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
  const readyArticles = useMemo(
    () => articles.filter(isComparisonReadyArticle),
    [articles],
  );
  const readySourceCount = useMemo(
    () => new Set(readyArticles.map(publisherIdentity)).size,
    [readyArticles],
  );
  const parsed = useMemo(
    () => parseComparisonSelection(initialArticles, readyArticles),
    [initialArticles, readyArticles],
  );
  const selected = parsed.selected;
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
    const candidate = readyArticles.find((article) => article.id === articleId);
    const sourceAlreadySelected = candidate && selected.some((selectedId) => (
      readyArticles.some((article) => article.id === selectedId && publisherIdentity(article) === publisherIdentity(candidate))
    ));
    if (!included && sourceAlreadySelected) {
      setSelectionMessage("같은 출처에서는 기사 1개만 선택할 수 있습니다.");
      return;
    }
    const next = included
      ? selected.filter((id) => id !== articleId)
      : [...selected, articleId];
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
    .map((articleId) => readyArticles.find((article) => article.id === articleId))
    .filter((article): article is Article => article !== undefined);
  const selectedSourceCount = new Set(selectedArticles.map(publisherIdentity)).size;

  const detailHeader = (
    <header className="comparison-hero">
      <p className="eyebrow">하나의 사건에서 여러 보도 비교</p>
      <h1>{issue.title}</h1>
      <p className="comparison-hero__meta">
        <span>전체 기사 {snapshot?.issue.article_count ?? issue.articleIds.length}개</span>
        <span>전체 출처 {snapshot?.issue.source_count ?? issue.sourceCount}곳</span>
        {dataAsOf ? <span>최신 보도 {formatPublishedDate(dataAsOf)}</span> : null}
      </p>
      <details className="comparison-context"><summary>이슈 배경 읽기</summary><p>{issue.summary}</p></details>
      <Link href="/issues">전체 이슈로 돌아가기</Link>
    </header>
  );

  if (readyArticles.length < 2 || readySourceCount < 2) {
    return (
      <div className="issue-comparison">
        {detailHeader}
        <IssueReadiness articleCount={readyArticles.length} sourceCount={readySourceCount} />
        <AcquiredArticles articles={articles} />
      </div>
    );
  }

  return (
    <div className="issue-comparison">
      {detailHeader}
      {readyArticles.length < articles.length ? <AcquiredArticles articles={articles} /> : null}

      <details className="comparison-selector"><summary>비교할 기사 변경 ({selected.length}개 선택)</summary>
        <div className="comparison-section-title">
          <h2 id="comparison-selector-title">비교할 기사</h2>
          <span>{selected.length}개 기사, {selectedSourceCount}곳 출처 선택</span>
        </div>
        <p className="comparison-selector__hint">서로 다른 출처에서 준비된 기사를 2개부터 4개까지 선택하세요.</p>
        <div className="comparison-selector__list" role="group" aria-label="비교할 기사">
          {[...readyArticles].sort((a, b) => a.id.localeCompare(b.id)).map((article) => {
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

              </div>
            );
          })}
        </div>
        {selectionMessage ? <p className="comparison-selector__status" role="status">{selectionMessage}</p> : null}
      </details>

      {selected.length < 2 ? (
        <p className="notice">비교할 기사를 2개 이상 선택해 주세요.</p>
      ) : comparison.isPending ? (
        <StatePanel state="loading" />
      ) : comparisonIsPreparing ? (
        <>
          <PendingReviewComparison articles={selectedArticles} />
          <IssueReadiness articleCount={readyArticles.length} sourceCount={readySourceCount} />
        </>
      ) : comparison.isError ? (
        <StatePanel state="error" onRetry={() => void comparison.refetch()} />
      ) : snapshot ? (
        <>
          <section className="common-facts" aria-labelledby="common-facts-title">
            <h2 id="common-facts-title">공통으로 확인된 사실</h2>
            <p>표시는 이 사실을 뒷받침하는 근거가 확인된 기사입니다. 표시가 없다고 해당 보도가 사실을 부정한다는 뜻은 아닙니다.</p>
            {snapshot.common_facts.map((fact) => <div className="ux-fact" key={fact.id}><h3>{fact.text}</h3><ul>{comparedArticles.map(({ article }) => <li key={article.id}><strong>{article.source}</strong><span>{fact.article_ids.includes(article.id) ? "근거 확인" : "근거 미확인"}</span></li>)}</ul></div>)}
            {!snapshot.common_facts.length && <p>여러 기사에서 함께 확인된 사실이 아직 없습니다.</p>}
          </section>
          <section className="ux-comparison" aria-labelledby="comparison-results-title">
            <h2 id="comparison-results-title">보도별 관점</h2>
            <div className="ux-comparison-head" style={{ gridTemplateColumns: `repeat(${comparedArticles.length}, minmax(0, 1fr))` }}>{comparedArticles.map(({ article }) => <div key={article.id}><strong>{article.source}</strong><Link href={`/articles/${article.id}`}>{article.title}</Link></div>)}</div>
            {[
              { label: "핵심 관점", render: (item: typeof comparedArticles[number]) => item.frame.headline_frame || "확인된 관점 없음" },
              { label: "강조하는 내용", render: (item: typeof comparedArticles[number]) => item.frame.emphasis.join(" / ") || "확인된 강조점 없음" },
              { label: "추가로 살펴볼 맥락", render: (item: typeof comparedArticles[number]) => item.frame.omissions_note || "별도로 확인된 내용 없음" },
            ].map((row) => <section className="ux-comparison-row" key={row.label}><h3>{row.label}</h3><div style={{ gridTemplateColumns: `repeat(${comparedArticles.length}, minmax(0, 1fr))` }}>{comparedArticles.map((item) => <div key={item.article.id}><strong className="ux-mobile-source">{item.article.source}</strong><p>{row.render(item)}</p></div>)}</div></section>)}
            <section className="ux-comparison-row"><h3>AI 점수</h3><div style={{ gridTemplateColumns: `repeat(${comparedArticles.length}, minmax(0, 1fr))` }}>{comparedArticles.map(({ article, score }) => <div key={article.id}><strong className="ux-mobile-source">{article.source}</strong><ScoreScale label="편향성" value={score.x} kind="bias" /><ScoreScale label="과장성" value={score.sensationalism} kind="intensity" /><p>분석 신뢰도 {formatConfidence(score.confidence)}</p><Link href={`/articles/${article.id}`}>기사 분석과 내 평가 →</Link></div>)}</div></section>
            <p>편향성은 좌우 관점, 과장성은 표현 강도입니다. 사실 여부나 기사 품질을 판정하지 않습니다.</p>
            <details><summary>기사별 요약 읽기</summary>{comparedArticles.map(({ article, assessment }) => <section key={article.id}><h3>{article.source}</h3><p>{assessment.summary}</p></section>)}</details>
          </section>
        </>
      ) : null}
    </div>
  );
}
