import { PageHeader } from "@/components/layout/page-header";
import { serverApiRequest } from "@/lib/api/server";
import { isMockMode } from "@/lib/api/mode";
import { notFound } from "next/navigation";
import { ButtonLink } from "@/components/ui/button";

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
  const templateLabel = card.template === "editorial" ? "편집형" : "스펙트럼형";
  return (
    <div className="public-share-page">
      <PageHeader eyebrow="공개 관점 카드" title={card.display_name || "관점 카드"} description="카드를 만든 시점의 편향성과 과장성 결과입니다." />
      <section className="public-share-card">
        <p className="eyebrow">EFFICA / {templateLabel}</p>
        <div className="public-share-card__title"><h2>{card.display_name || "관점 카드"}</h2><span className="badge badge--positive">공개 시점 결과</span></div>
        <dl className="public-share-card__metrics" aria-label="공개 시점 결과">
          <div><dt>편향성</dt><dd>{x > 0 ? `+${x}` : x}<small>좌편향 −100에서 우편향 +100 사이</small></dd></div>
          <div><dt>과장성</dt><dd>{sensationalism == null ? "미측정" : `${sensationalism}/100`}<small>표현 강도</small></dd></div>
        </dl>
        <div className="public-share-card__foot"><span>{confidence == null ? "분석 신뢰도 미공개" : `분석 신뢰도 ${Math.round(confidence * 100)}%`}</span><a className="button button--primary" href={`/api/v1/public/share/${encodeURIComponent(token)}/image`}>이미지로 열기</a></div>
        <span className="public-share-card__shape" aria-hidden="true" />
      </section>
      <div className="form-actions" style={{ justifyContent: "center" }}><ButtonLink href="/issues">EFFICA에서 기사 관점 비교하기</ButtonLink></div>
    </div>
  );
}
