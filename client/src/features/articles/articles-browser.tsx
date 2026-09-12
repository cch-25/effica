"use client";

import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { StatePanel } from "@/components/ui/state-panel";
import { issueTopics } from "@/features/issues/issue-selection";
import { homePublishedAt } from "@/features/home/home-edition";
import { directoryEntries, loadDirectoryArticles, loadDirectoryIssues } from "./article-directory-data";

export type ArticleFilters = { topic: string; q: string; source: string };

function directoryHref(filters: ArticleFilters) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
  return `/articles${params.size ? `?${params}` : ""}`;
}

function ArticleRow({ entry }: { entry: ReturnType<typeof directoryEntries>[number] }) {
  const { article, issues } = entry;
  const [failedImage, setFailedImage] = useState(false);
  const showImage = Boolean(article.imageUrl) && !failedImage;
  const topics = [...new Set(issues.map((issue) => issue.topic))];
  const relatedIssue = issues.find((issue) => issue.kind === "EVENT");
  return <li className={`article-directory-row${showImage ? " article-directory-row--photo" : ""}`}>
    <article>
      <div className="article-directory-row__byline"><strong>{article.source}</strong><span>{homePublishedAt(article.publishedAt)}</span><span>{topics.join(" / ")}</span></div>
      <h2><Link href={`/articles/${article.id}`}>{article.title}</Link></h2>
      {article.dek && <p className="article-directory-row__summary">{article.analysisStatus === "READY" && "분석 요약 "}{article.dek}</p>}
      <nav className="article-directory-row__links" aria-label={`${article.title} 기사 이동`}>
        <Link href={`/articles/${article.id}`}>기사 읽기 →</Link>
        {article.originalUrl && <a href={article.originalUrl} target="_blank" rel="noreferrer">언론사 원문 <span aria-hidden="true">↗</span><span className="sr-only"> (새 탭)</span></a>}
        {relatedIssue && <Link href={`/issues/${relatedIssue.id}`}>관련 보도 비교</Link>}
        {article.analysisStatus !== "READY" && <span className="article-directory-row__status">{article.analysisStatus === "UNTRUSTED" ? "분석 공개 제한" : article.analysisStatus === "PARTIAL" ? "일부 분석 공개" : "분석 준비 중"}</span>}
      </nav>
    </article>
    {showImage && <Link className="article-directory-row__photo" href={`/articles/${article.id}`} aria-label={`${article.title} 기사 사진으로 읽기`}>
      <Image src={article.imageUrl!} alt="" width={240} height={160} unoptimized referrerPolicy="no-referrer" onError={() => setFailedImage(true)} />
    </Link>}
  </li>;
}

export function ArticlesBrowser({ filters }: { filters: ArticleFilters }) {
  const router = useRouter();
  const [visibleCount, setVisibleCount] = useState(20);
  const index = useQuery({ queryKey: ["article-directory", "issues"], queryFn: ({ signal }) => loadDirectoryIssues(signal), staleTime: 60_000 });
  const issues = (index.data ?? []).filter((issue) => !filters.topic || issue.topic === filters.topic);
  const issueIds = [...new Set(issues.map((issue) => issue.id))].sort();
  const collection = useQuery({
    queryKey: ["article-directory", "articles", issueIds],
    queryFn: ({ signal }) => loadDirectoryArticles(issueIds, signal),
    enabled: index.isSuccess,
    staleTime: 60_000,
  });
  const topics = [...new Set<string>([...issueTopics, ...(index.data ?? []).map((issue) => issue.topic)])];
  const entries = directoryEntries(collection.data?.articles ?? [], issues);
  const sources = [...new Set(entries.map(({ article }) => article.source))].sort((a, b) => a.localeCompare(b, "ko"));
  const search = filters.q.trim().normalize("NFKC").toLocaleLowerCase();
  const matches = entries.filter(({ article }) => (!filters.source || article.source === filters.source)
    && (!search || `${article.title} ${article.source} ${article.dek}`.normalize("NFKC").toLocaleLowerCase().includes(search)));
  const failedCount = collection.data?.failedIssueIds.length ?? 0;
  const pending = index.isPending || collection.isPending;
  const error = index.isError || collection.isError;
  const retry = () => { void index.refetch(); void collection.refetch(); };
  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const q = String(new FormData(event.currentTarget).get("q") ?? "").trim();
    router.push(directoryHref({ ...filters, q }), { scroll: false });
  };

  return <div className="articles-page">
    <header className="page-header"><div className="page-header__body"><h1>기사 모음</h1><p className="page-header__description">카테고리별 기사를 최신순으로 읽고, 언론사 원문과 분석을 확인하세요.</p></div></header>
    <nav className="article-categories" aria-label="기사 카테고리">
      {["", ...topics].map((topic) => <Link key={topic} href={directoryHref({ ...filters, topic, source: "" })} scroll={false} aria-current={filters.topic === topic ? "page" : undefined}>{topic || "전체"}</Link>)}
    </nav>
    <div className="article-directory-tools">
      <form role="search" aria-label="기사 검색" onSubmit={submitSearch}>
        <label htmlFor="article-search" className="sr-only">기사 제목 또는 검색어</label>
        <input id="article-search" name="q" type="search" defaultValue={filters.q} placeholder="기사 제목 또는 검색어" />
        <Button type="submit" variant="secondary">검색</Button>
      </form>
      <label className="article-source-filter">언론사<select aria-label="언론사" value={filters.source} onChange={(event) => router.push(directoryHref({ ...filters, source: event.target.value }), { scroll: false })}>
        <option value="">전체 언론사</option>
        {filters.source && !sources.includes(filters.source) && <option value={filters.source}>{filters.source}</option>}
        {sources.map((source) => <option key={source} value={source}>{source}</option>)}
      </select></label>
    </div>
    <div className="article-directory-status" role="status">
      <span>{pending ? "기사를 불러오는 중입니다." : error ? "기사 목록을 불러오지 못했습니다." : `${filters.topic || "전체"} 기사 ${matches.length}개${failedCount ? " (일부 목록)" : ""}`}</span>
      <span>최신 발행순</span>
      {(filters.q || filters.source || filters.topic) && <Link href="/articles" scroll={false}>조건 초기화</Link>}
    </div>
    {error ? <StatePanel state="error" onRetry={retry} /> : pending ? <StatePanel state="loading" /> : <>
      {failedCount > 0 && <div className="article-directory-warning" role="status"><p>일부 기사를 불러오지 못했습니다. 현재 불러온 기사만 표시합니다.</p><Button variant="ghost" onClick={() => void collection.refetch()} disabled={collection.isFetching}>{collection.isFetching ? "불러오는 중" : "다시 불러오기"}</Button></div>}
      {matches.length > 0 ? <ul className="article-directory-list">{matches.slice(0, visibleCount).map((entry) => <ArticleRow key={entry.article.id} entry={entry} />)}</ul>
        : !failedCount && <div className="article-directory-empty"><h2>{filters.q || filters.source ? "조건에 맞는 기사가 없습니다." : "아직 공개된 기사가 없습니다."}</h2><p>{filters.q || filters.source ? "검색어나 언론사를 바꿔 다시 찾아보세요." : "다른 카테고리의 기사를 먼저 살펴보세요."}</p><Link href="/articles">전체 기사 보기 →</Link></div>}
      {matches.length > visibleCount && <Button className="article-directory-more" variant="ghost" onClick={() => setVisibleCount((count) => count + 20)}>기사 더 보기 ({visibleCount}/{matches.length})</Button>}
    </>}
  </div>;
}
