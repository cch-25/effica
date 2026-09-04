import { ArrowLeft } from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { ButtonLink } from "@/components/ui/button";
import { PrivacyActions } from "@/features/auth/privacy-actions";

export default function PrivacyPage() { return <><PageHeader eyebrow="내 활동" title="개인정보 관리" description="정치 설문과 행동 좌표는 일반 계정 정보와 분리된 민감정보로 취급합니다." actions={<ButtonLink variant="secondary" href="/progress"><ArrowLeft size={15} aria-hidden="true" /> 내 활동으로 돌아가기</ButtonLink>} /><PrivacyActions /></>; }
