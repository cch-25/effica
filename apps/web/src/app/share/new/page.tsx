import { PageHeader } from "@/components/layout/page-header";
import { ShareCardCreator } from "@/features/share-cards/share-card-creator";

export default function NewSharePage() { return <><PageHeader eyebrow="Share card" title="공개할 정보만, 분명하게" description="카드는 현재 좌표와 활동 티어의 snapshot입니다. 생성 전 공개 범위를 확인하세요." /><ShareCardCreator /></>; }
