import Link from "next/link";
import { FeedGrid } from "@/features/feed/feed-grid";
import { articles, issues } from "@/mocks/fixtures/content";
import { DataAsOfBadge } from "@/features/issues/data-as-of-badge";
import { FrontPage } from "@/features/home/front-page";

export default function HomePage() {
  return <div className="home-page">
    <div className="front-page-dateline"><span>종합 / 주요 이슈와 보도</span><DataAsOfBadge fallback={issues} /></div>
    <FrontPage fallbackIssues={issues} fallbackArticles={articles} />
    <section className="home-section home-section--feed">
      <div className="section-head"><div><span className="section-index">02</span><h2>추천 기사와 관점 분석</h2></div><Link href="/issues">이슈 전체 보기 →</Link></div>
      <FeedGrid fallback={articles} />
    </section>
    <section className="reader-notice" aria-label="독자 안내"><strong>독자 안내</strong><p>기사의 편향성과 과장성은 사실 여부나 품질의 판정이 아닙니다. 분석의 근거와 한계를 확인하고 원문을 함께 읽어 주세요.</p><Link href="/visualization">기사 관점 지도 →</Link></section>
  </div>;
}
