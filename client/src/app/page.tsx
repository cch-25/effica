import Link from "next/link";
import { articles, issues } from "@/mocks/fixtures/content";
import { DataAsOfBadge } from "@/features/issues/data-as-of-badge";
import { FrontPage } from "@/features/home/front-page";

export default function HomePage() {
  return <div className="home-page">
    <div className="front-page-dateline"><span>정치와 정책 / 주요 이슈와 보도</span><DataAsOfBadge fallback={issues} /></div>
    <FrontPage fallbackIssues={issues} fallbackArticles={articles} />
    <section className="reader-notice" aria-label="독자 안내"><strong>독자 안내</strong><p>기사의 편향성과 과장성은 사실 여부나 품질의 판정이 아닙니다. 각 기사에서 관점 지도와 분석 근거를 확인하고 원문을 함께 읽어 주세요.</p><Link href="/issues">이슈별 기사 살펴보기 →</Link></section>
  </div>;
}
