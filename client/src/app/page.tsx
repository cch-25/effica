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
            <p className="eyebrow">EFFICA / 보도 비교와 관점 분석</p>
            <DataAsOfBadge fallback={issues} />
          </div>
          <h1 aria-label="Political efficacy"><span>POLITICAL</span><span><em>EFFICA</em>CY</span></h1>
          <p>같은 이슈를 다룬 여러 출처의 기사를 나란히 비교하고, AI 분석의 근거와 한계를 확인하세요.</p>
          <div className="page-header__actions"><ButtonLink href="/issues">이슈 비교 시작 <ArrowRight size={15} /></ButtonLink><ButtonLink variant="secondary" href="/visualization"><Compass size={15} /> 기사 관점 지도</ButtonLink></div>
        </div>
        <div className="feature-banner__aside" aria-hidden="true">
          <span className="paper-shape paper-shape--circle" />
          <span className="paper-shape paper-shape--square" />
          <span className="paper-shape paper-shape--dash" />
          <PerspectiveOrb />
        </div>
      </section>

      <section className="home-section home-section--issues">
        <div className="section-head">
          <div><span className="section-index">01</span><h2>지금 비교할 수 있는 이슈</h2></div>
          <Link href="/issues">이슈 전체 보기 →</Link>
        </div>
        <IssueGrid fallback={issues} columns={3} featuredOnly />
      </section>

      <section className="home-section home-section--feed">
        <div className="section-head"><div><span className="section-index">02</span><h2>추천 기사와 관점 분석</h2></div><span className="badge"><Layers3 size={12} /> 다른 출처 추천</span></div>
        <FeedGrid fallback={articles} />
      </section>

      <section className="home-principle">
        <span className="section-index">03</span>
        <div>
          <p className="eyebrow">추천 방식</p>
          <h2>왜 이 기사를 추천했나요?</h2>
        </div>
        <div className="home-principle__copy">
          <p>현재 관점과 가깝지만 다른 기사부터 보여주고, 덜 본 출처와 같은 이슈의 보완 관점을 이어서 제안합니다.</p>
          <ButtonLink variant="secondary" href="/visualization">추천 기사를 지도에서 보기 <ArrowRight size={15} /></ButtonLink>
        </div>
        <span className="home-principle__shape" aria-hidden="true" />
      </section>
    </div>
  );
}
