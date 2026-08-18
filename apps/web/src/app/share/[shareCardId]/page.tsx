import { PageHeader } from "@/components/layout/page-header";
import { ShareCardStatus } from "@/features/share-cards/share-card-status";
import type { ShareCardView } from "@/lib/api/contracts";
import { serverApiRequest } from "@/lib/api/server";
import { notFound } from "next/navigation";
import { isMockMode } from "@/lib/api/mode";

export default async function SharePage({ params }: { params: Promise<{ shareCardId: string }> }) {
  const { shareCardId } = await params;
  const fixtureStatus = (["queued", "rendering", "failed", "revoked"] as ShareCardView["status"][]).find((status) => shareCardId.endsWith(status)) ?? "ready";
  const fixture: ShareCardView = { id: shareCardId, status: fixtureStatus, public_token: fixtureStatus === "ready" ? "mock-public-token" : null, etag: null, snapshot: { x: 4, sensationalism: 18, confidence: 0.68 } };
  const card = isMockMode() ? fixture : await serverApiRequest<ShareCardView>(`/share-cards/${encodeURIComponent(shareCardId)}`).catch(() => null);
  if (!card) notFound();
  return <><PageHeader eyebrow="Share render" title="공유 카드" description={`카드 ${shareCardId}의 렌더링·공개·폐기 상태를 관리합니다.`} /><ShareCardStatus initialCard={card} /></>;
}
