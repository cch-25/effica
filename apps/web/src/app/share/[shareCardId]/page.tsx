import { ArrowLeft } from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { ButtonLink } from "@/components/ui/button";
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
  return <><PageHeader eyebrow="공유 카드 관리" title="공유 카드 상태와 공개 설정" description="카드 생성 상태를 확인하고 공개 링크와 파일을 각각 관리할 수 있습니다." actions={<ButtonLink variant="secondary" href="/progress"><ArrowLeft size={15} aria-hidden="true" /> 내 활동으로 돌아가기</ButtonLink>} /><ShareCardStatus initialCard={card} /></>;
}
