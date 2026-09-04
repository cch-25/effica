import { ArrowLeft } from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { ButtonLink } from "@/components/ui/button";
import { ShareCardCreator } from "@/features/share-cards/share-card-creator";

export default function NewSharePage() { return <><PageHeader eyebrow="내 활동" title="공유 카드 만들기" description="카드에는 생성 시점의 관점 점수와 활동 단계만 담깁니다. 만들기 전에 공개 범위를 확인해 주세요." actions={<ButtonLink variant="secondary" href="/progress"><ArrowLeft size={15} aria-hidden="true" /> 내 활동으로 돌아가기</ButtonLink>} /><ShareCardCreator /></>; }
