"use client";

import Image from "next/image";
import Link from "next/link";
import { Button } from "@base-ui/react/button";
import { useRef, useState, type ReactNode } from "react";
import { useIssueArticlesQuery, useIssuesQuery } from "@/lib/api/queries";
import { isMockMode } from "@/lib/api/mode";
import { formatPublishedDate } from "@/lib/api/formatters";
import type { Article, Issue } from "@/lib/api/types";
import { StatePanel } from "@/components/ui/state-panel";
import {
  articlesForHomeIssue, buildHomeEdition, homePublishedAt, initialGroupIssue, publisherPreview,
  type HomeIssueGroup,
} from "./home-edition";

function Headline({ text }: { text: string }) {
  return text.split(/(\s+)/).map((word, index) => /\s/.test(word)
    ? word : <span className="home-headline-word" key={index}>{word}</span>);
}

function IssuePhoto({ article, onFailure }: { article: Article; onFailure: () => void }) {
  if (!article.imageUrl) return null;
  return <figure className="home-issue-photo">
    <Image src={article.imageUrl} alt={`${article.source}의 이 쟁점 관련 기사 사진`} width={800} height={500}
      unoptimized referrerPolicy="no-referrer" onError={onFailure} />
    <figcaption><span>{article.title}</span><a href={article.originalUrl} target="_blank" rel="noreferrer">사진 출처: {article.source}</a></figcaption>
  </figure>;
}

function ArticleColumn({ article, primary }: { article: Article; primary: boolean }) {
  const ready = article.analysisStatus === "READY";
  const Heading = primary ? "h3" : "h4";
  return <li className="home-article">
    <div className="home-article__meta"><strong>{article.source}</strong><span>{homePublishedAt(article.publishedAt)}</span></div>
    <Heading><Link href={`/articles/${article.id}`}><Headline text={article.title} /></Link></Heading>
    <p className="home-article__summary">{ready && article.dek ? <><span>분석 요약 </span>{article.dek}</> : "분석을 준비하고 있습니다. 원문에서 보도 내용을 먼저 확인할 수 있습니다."}</p>
    <div className="home-article__links">
      <Link href={`/articles/${article.id}`}>{ready ? "분석 근거 읽기" : "기사 보기"} →</Link>
      <a href={article.originalUrl} target="_blank" rel="noreferrer">원문<span className="sr-only"> 읽기 (새 탭)</span></a>
    </div>
  </li>;
}

function IssueReading({ issue, primary, groupId, fallbackArticles, children }: {
  issue: Issue; primary: boolean; groupId: string; fallbackArticles: Article[]; children: ReactNode;
}) {
  const query = useIssueArticlesQuery(issue.id);
  const articles = articlesForHomeIssue(issue, query.data?.items ?? (isMockMode() ? fallbackArticles : []));
  const [expandedIssue, setExpandedIssue] = useState<string | null>(null);
  const [failedPhotos, setFailedPhotos] = useState<Set<string>>(() => new Set());
  const expanded = expandedIssue === issue.id;
  const preview = publisherPreview(articles);
  const visible = expanded ? articles : preview;
  const photo = articles.find((article) => article.imageUrl && !failedPhotos.has(article.id));
  const ready = issue.analysisStatus === "READY";
  const waiting = query.isPending && !articles.length;
  const Heading = primary ? "h1" : "h2";
  const CoverageHeading = primary ? "h2" : "h3";
  return <div className="home-reading" data-issue-id={issue.id}>
    <div className={`home-issue-opening${photo ? " home-issue-opening--photo" : ""}`}>
      <div className="home-issue-story">
        <Heading id={`home-title-${groupId}`}><Headline text={issue.title} /></Heading>
        <p className="home-issue-summary">{issue.summary}</p>
        <div className="home-issue-meta"><span>기사 {issue.articleIds.length}개 / 언론사 {issue.sourceCount}곳</span><span>{ready ? "비교 가능" : "분석 준비 중"}</span>{issue.dataAsOf && <span>최근 보도 {formatPublishedDate(issue.dataAsOf)}</span>}</div>
        <Link className="home-compare-link" href={`/issues/${issue.id}`}>
          {ready ? "이 쟁점의 보도 비교하기" : "이 쟁점의 기사와 준비 상태 보기"} <span aria-hidden="true">→</span>
        </Link>
      </div>
      {photo && <IssuePhoto key={photo.id} article={photo} onFailure={() => setFailedPhotos(previous => new Set([...previous, photo.id]))} />}
    </div>
    {children}
    <section className="home-coverage" aria-label={`${issue.title} 관련 기사`}>
      <div className="home-coverage__heading"><CoverageHeading id={`home-coverage-${groupId}`}>이 쟁점을 다룬 기사</CoverageHeading>
        {articles.length > 0 && <p>{expanded ? "발행 시각 최신순" : "언론사별 최신 1건을 발행 시각순으로"} / {visible.length}개 표시</p>}
      </div>
      {query.isError ? <div className="home-load-message" role="status"><p>기사 목록을 새로 불러오지 못했습니다.</p><Button type="button" onClick={() => void query.refetch()}>다시 불러오기</Button></div>
        : waiting ? <p className="home-load-message" role="status">이 쟁점의 기사를 불러오는 중입니다.</p>
          : !articles.length && <p className="home-load-message" role="status">현재 표시할 기사가 없습니다. 쟁점 상세에서 준비 상태를 확인해 주세요.</p>}
      <ul className="home-article-list">{visible.map((article) => <ArticleColumn key={article.id} article={article} primary={primary} />)}</ul>
      {articles.length > preview.length && <Button className="home-expand" type="button" aria-expanded={expanded} onClick={() => setExpandedIssue(expanded ? null : issue.id)}>
        {expanded ? `언론사별 기사 ${preview.length}개만 보기` : `이 쟁점의 기사 ${articles.length}개 모두 보기`} <span aria-hidden="true">{expanded ? "−" : "+"}</span>
      </Button>}
      {query.data?.next_cursor && <Link className="home-expand" href={`/issues/${issue.id}`}>전체 기사 목록 보기 →</Link>}
    </section>
  </div>;
}

function IssueSpread({ group, primary, fallbackArticles }: { group: HomeIssueGroup; primary: boolean; fallbackArticles: Article[] }) {
  const [selectedId, setSelectedId] = useState(initialGroupIssue(group).id);
  const picker = useRef<HTMLDetailsElement>(null);
  const issue = group.issues.find((item) => item.id === selectedId) ?? initialGroupIssue(group);
  return <section id={`home-issue-${group.id}`} className={`home-spread${primary ? " home-spread--lead" : ""}`} aria-labelledby={`home-title-${group.id}`}>
    <div className="home-selected-context"><span>{primary ? "주요 이슈" : "다른 이슈"} / {group.issues.length > 1 ? group.title : issue.topic}</span>
      {group.issues.length > 1 && <span>관련 쟁점 {group.issues.length}개</span>}</div>
    <IssueReading issue={issue} primary={primary} groupId={group.id} fallbackArticles={fallbackArticles}>
      {group.issues.length > 1 && <details className="home-angle-picker" ref={picker}>
        <summary>같은 이슈의 다른 쟁점 {group.issues.length - 1}개 <span aria-hidden="true">+</span></summary>
        <p>관련 쟁점을 한 지면에 모았습니다. 쟁점을 선택하면 위의 요약과 아래 기사가 함께 바뀝니다.</p>
        <div role="group" aria-label="비교할 쟁점 선택">{group.issues.map((item) => <Button type="button" key={item.id} aria-pressed={item.id === issue.id} onClick={() => {
          setSelectedId(item.id);
          // Keep focus on the persistent disclosure when its option disappears.
          if (picker.current) { picker.current.open = false; picker.current.querySelector("summary")?.focus(); }
        }}><span>{item.title}</span><small>{item.id === issue.id ? "선택됨" : item.analysisStatus === "READY" ? "비교 가능" : "분석 준비 중"}</small></Button>)}</div>
      </details>}
    </IssueReading>
  </section>;
}

export function HomeNewspaper({ fallbackIssues, fallbackArticles }: { fallbackIssues: Issue[]; fallbackArticles: Article[] }) {
  const query = useIssuesQuery(250);
  const issues = query.data?.items ?? (isMockMode() ? fallbackIssues : []);
  const groups = buildHomeEdition(issues);
  return <>
    <div className="home-edition-intro"><p>{isMockMode() ? "샘플 지면 / " : ""}정치와 정책 <span>같은 쟁점의 보도를 나란히 읽습니다.</span></p><Link href="/issues">전체 이슈 보기 →</Link></div>
    {groups.length > 1 && <nav className="home-index" aria-label="이 지면의 이슈"><strong>이 지면의 이슈</strong><ol>{groups.map((group, index) => <li key={group.id}>
      <a href={`#home-issue-${group.id}`}><span className="home-index__number">{String(index + 1).padStart(2, "0")}</span><span>{group.title}</span>{group.issues.length > 1 && <small>쟁점 {group.issues.length}개</small>}</a>
    </li>)}</ol></nav>}
    {query.isPending && !isMockMode() ? <StatePanel state="loading" /> : query.isError ? <StatePanel state="error" onRetry={() => void query.refetch()} /> : !groups.length ?
      <section className="home-empty" role="status"><h1>비교할 이슈를 준비하고 있습니다.</h1><p>최근 기사를 여러 언론사에서 확보한 이슈부터 보여드립니다.</p><Link href="/issues">전체 이슈와 준비 상태 보기 →</Link></section>
      : <div className="home-spreads">{groups.map((group, index) => <IssueSpread key={group.id} group={group} primary={index === 0} fallbackArticles={fallbackArticles} />)}</div>}
    <aside className="home-reading-guide" aria-label="독자 안내"><div><strong>기사 분석은 어떻게 읽나요?</strong><p>기사에서 강조한 내용과 그 근거를 살펴보세요. 편향성과 과장성 점수는 사실 여부나 기사 품질의 판정이 아닙니다.</p></div>
      <details className="home-selection-rule"><summary>지면 구성 기준</summary><p>최근 기사가 3개 이상이고 언론사 3곳 이상을 확보한 이슈를 보여드립니다. 관련 쟁점은 한 묶음으로 모읍니다.</p><p>편집 우선순위가 높은 묶음부터 최대 5개를 표시합니다. 우선순위가 같으면 언론사 수와 기사 수, 최근 갱신 시각을 차례로 봅니다.</p><p>날짜와 발행 시각은 한국 시간 기준입니다.</p></details>
    </aside>
  </>;
}
