import Link from "next/link";
import { ArrowRight, Compass, Layers3 } from "lucide-react";
import { FeedGrid } from "@/features/feed/feed-grid";
import { IssueGrid } from "@/features/issues/issue-grid";
import { articles, issues } from "@/mocks/fixtures/content";
import { ButtonLink } from "@/components/ui/button";
import { DataAsOfBadge } from "@/features/issues/data-as-of-badge";
import { PerspectiveOrb } from "@/features/home/perspective-orb";

export default function HomePage() {
  return (
    <div className="home-page">
      <section className="feature-banner">
        <div className="feature-banner__content">
          <div className="feature-banner__meta">
            <p className="eyebrow">EFFICA · 오늘의 관점 브리핑</p>
            <DataAsOfBadge fallback={issues} />
          </div>
          <h1 aria-label="Political efficacy"><span>POLITICAL</span><span><em>EFFICA</em>CY</span></h1>
          <p>서로 다른 출처를 나란히 보고, AI 분석과 독자 평가를 근거와 불확실성까지 구분해 확인하세요.</p>
          <div className="page-header__actions"><ButtonLink href="/issues">오늘의 이슈 <ArrowRight size={15} /></ButtonLink><ButtonLink variant="secondary" href="/visualization"><Compass size={15} /> 관점 지도</ButtonLink></div>
        </div>
        <div className="feature-banner__aside" aria-hidden="true">
          <span className="paper-shape paper-shape--circle" />
          <span className="paper-shape paper-shape--square" />
          <span className="paper-shape paper-shape--dash" />
          <PerspectiveOrb />
        </div>
      </section>

      <section className="home-section home-section--issues">
        <div className="section-head"><div><span className="section-index">01</span><h2>서로 다른 시선이 모인 이슈</h2></div><Link href="/issues">전체 이슈 →</Link></div>
        <IssueGrid fallback={issues} columns={3} featuredOnly />
      </section>

      <section className="home-section home-section--feed">
        <div className="section-head"><div><span className="section-index">02</span><h2>관점을 넓히는 기사</h2></div><span className="badge"><Layers3 size={12} /> 다양성 보정 피드</span></div>
        <FeedGrid fallback={articles} />
      </section>

      <section className="home-principle">
        <span className="section-index">03</span>
        <div>
          <p className="eyebrow">추천 원칙</p>
          <h2>정반대가 아니라,<br />이해할 수 있는 거리부터.</h2>
        </div>
        <div className="home-principle__copy">
          <p>현재 관점과 가깝지만 다른 기사, 덜 본 출처, 같은 이슈의 보완 관점을 먼저 제안합니다.</p>
          <ButtonLink variant="secondary" href="/visualization">내 관점 살펴보기 <ArrowRight size={15} /></ButtonLink>
        </div>
        <span className="home-principle__shape" aria-hidden="true" />
      </section>
    </div>
  );
}
