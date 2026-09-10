import { ArrowLeft } from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { ButtonLink } from "@/components/ui/button";
import { ShareCardCreator } from "@/features/share-cards/share-card-creator";

export default function NewSharePage() { return <><PageHeader eyebrow="내 활동" title="공유 카드 만들기" description="뉴스를 얼마나 다양하게 읽었는지 돌아보고, 별도 검사로 확인한 이념 위치를 함께 공유하세요. 만들기 전에 공개 범위를 확인해 주세요." actions={<ButtonLink variant="secondary" href="/progress"><ArrowLeft size={15} aria-hidden="true" /> 내 활동으로 돌아가기</ButtonLink>} /><ShareCardCreator /></>; }
