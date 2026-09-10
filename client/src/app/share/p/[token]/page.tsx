import { PageHeader } from "@/components/layout/page-header";
import { serverApiRequest } from "@/lib/api/server";
import { isMockMode } from "@/lib/api/mode";
import { notFound } from "next/navigation";
import { ButtonLink } from "@/components/ui/button";
import { PerspectivePreview } from "@/features/share-cards/perspective-preview";
import { consumptionSnapshot } from "@/features/share-cards/consumption";

type PublicShare = { id: string; template: string; display_name: string | null; snapshot: Record<string, unknown>; etag: string | null };

export default async function PublicSharePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  const card = isMockMode()
    ? { id: "01H00000000000000000000006", template: "orbit", display_name: "김사이", snapshot: { diversity_score: 68, diversity_article_count: 12, ideology: { completed: true, x: 28, y: 12, z: 35, questionnaire_status: "beta" } }, etag: '"mock"' } satisfies PublicShare
    : await serverApiRequest<PublicShare>(`/public/share/${encodeURIComponent(token)}`).catch(() => null);
  if (!card) notFound();
  const snapshot = consumptionSnapshot(card.snapshot);
  const legacy = !snapshot || card.snapshot.legacy === true || card.snapshot.legacy_snapshot === true;
  return <div className="public-share-page">
    <PageHeader eyebrow="공개 뉴스 소비 카드" title="뉴스 소비 성향" description="카드를 만든 시점의 뉴스 소비 기록과 별도 검사 결과입니다." />
    {legacy ? <section className="card card--padded"><h2>이전 방식으로 만든 카드입니다.</h2><p>기사 평가로 계산한 예전 점수를 이용자의 정치성향으로 표시하지 않습니다. 작성자가 새 카드를 만들면 뉴스 소비 다양성과 검사 결과를 확인할 수 있습니다.</p></section> : <>
      <PerspectivePreview displayName={card.display_name ?? ""} template={card.template === "editorial" ? "editorial" : "orbit"} snapshot={snapshot} compact publicView />
      <div className="form-actions" style={{ justifyContent: "center" }}><a className="button button--secondary" href={`/api/v1/public/share/${encodeURIComponent(token)}/image`}>이미지로 열기</a></div>
    </>}
    <div className="form-actions" style={{ justifyContent: "center" }}><ButtonLink href="/issues">EFFICA에서 기사 관점 비교하기</ButtonLink></div>
  </div>;
}
