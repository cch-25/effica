import { PageHeader } from "@/components/layout/page-header";
import { ShareCardStatus } from "@/features/share-cards/share-card-status";
import type { ShareCardStatus as Status } from "@/features/share-cards/model";

export default async function SharePage({ params }: { params: Promise<{ shareCardId: string }> }) { const { shareCardId } = await params; const fixtureStatus = (["queued", "rendering", "failed", "revoked"] as Status[]).find((status) => shareCardId.endsWith(status)) ?? "ready"; return <><PageHeader eyebrow="Share render" title="공유 카드" description={`카드 ${shareCardId}의 렌더링·공개·폐기 상태를 관리합니다.`} /><ShareCardStatus initialStatus={fixtureStatus} /></>; }
