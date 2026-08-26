import { PageHeader } from "@/components/layout/page-header";
import { serverApiRequest } from "@/lib/api/server";
import { isMockMode } from "@/lib/api/mode";
import { notFound } from "next/navigation";

type PublicShare = {
  id: string;
  template: string;
  display_name: string | null;
  snapshot: Record<string, unknown>;
  etag: string | null;
};

export default async function PublicSharePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  const card = isMockMode()
    ? {
      id: "01H00000000000000000000006",
      template: "orbit",
      display_name: "김사이",
      snapshot: { x: 4, sensationalism: 18, confidence: 0.68 },
      etag: '"mock"',
    } satisfies PublicShare
    : await serverApiRequest<PublicShare>(`/public/share/${encodeURIComponent(token)}`).catch(() => null);
  if (!card) notFound();
  const snapshot = card.snapshot;
  const x = Number(snapshot.x ?? 0);
  const sensationalism = snapshot.sensationalism == null ? null : Number(snapshot.sensationalism);
  const confidence = snapshot.confidence == null ? null : Number(snapshot.confidence);
  return (
    <div className="public-share-page">
      <PageHeader eyebrow="Public share" title={card.display_name || "관점 카드"} description="편향성과 과장성 점수의 공개 snapshot입니다." />
      <section className="public-share-card">
        <p className="eyebrow">EFFICA / {card.template}</p>
        <div className="public-share-card__title"><h2>{card.display_name || "관점 카드"}</h2><span className="badge badge--positive">공개 snapshot</span></div>
        <dl className="public-share-card__metrics" aria-label="공개 스냅샷">
          <div><dt>편향성</dt><dd>{x > 0 ? `+${x}` : x}</dd><small>좌편향 −100 · 우편향 +100</small></div>
          <div><dt>과장성</dt><dd>{sensationalism == null ? "미측정" : `${sensationalism}/100`}</dd><small>표현 강도</small></div>
        </dl>
        <div className="public-share-card__foot"><span>{confidence == null ? "분석 신뢰도 미공개" : `분석 신뢰도 ${Math.round(confidence * 100)}%`}</span><a className="button button--primary" href={`/api/v1/public/share/${encodeURIComponent(token)}/image`}>PNG 보기</a></div>
        <span className="public-share-card__shape" aria-hidden="true" />
      </section>
    </div>
  );
}
