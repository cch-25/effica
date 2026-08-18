import Link from "next/link";
import { ArrowRight, Compass, Layers3 } from "lucide-react";
import { FeedGrid } from "@/features/feed/feed-grid";
import { IssueGrid } from "@/features/issues/issue-grid";
import { articles, issues } from "@/mocks/fixtures/content";
import { Badge } from "@/components/ui/badge";
import { ButtonLink } from "@/components/ui/button";

export default function HomePage() {
  return (
    <>
      <section className="feature-banner">
        <div className="feature-banner__content">
          <Badge tone="positive">오늘의 관점 지도 · 8월 16일</Badge>
          <h1>POLITICAL <span className="feature-banner__effica">EFFICA</span>CY</h1>
          <p>같은 이슈를 여러 출처와 관점에서 읽고, AI와 독자의 평가는 근거와 불확실성까지 함께 비교하세요.</p>
          <div className="page-header__actions"><ButtonLink href="/issues">오늘의 이슈 <ArrowRight size={15} /></ButtonLink><ButtonLink variant="secondary" href="/visualization"><Compass size={15} /> 관점 지도</ButtonLink></div>
        </div>
        <div className="feature-banner__aside" aria-hidden="true"><div className="orbit"><span /><span /><span /></div></div>
      </section>

      <div className="section-head"><h2>서로 다른 시선이 모인 이슈</h2><Link href="/issues">전체 이슈 →</Link></div>
      <IssueGrid fallback={issues} columns={3} />

      <div className="section-head"><h2>관점을 넓히는 기사</h2><span className="badge"><Layers3 size={12} /> 다양성 보정 피드</span></div>
      <FeedGrid fallback={articles} />

      <section className="card card--padded" style={{ marginTop: "1rem" }}>
        <p className="eyebrow">추천 원칙</p><h2>정반대가 아니라, 이해할 수 있는 거리부터</h2>
        <p style={{ maxWidth: 720, color: "var(--muted)" }}>EFFICA는 사용자의 현재 관점과 가깝지만 다른 기사, 덜 본 출처, 같은 이슈의 보완 관점을 우선합니다. 추천 이유는 모든 카드에 표시됩니다.</p>
      </section>
    </>
  );
}
