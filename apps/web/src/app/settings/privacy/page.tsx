import { PageHeader } from "@/components/layout/page-header";
import { PrivacyActions } from "@/features/auth/privacy-actions";

export default function PrivacyPage() { return <><PageHeader eyebrow="Settings / privacy" title="내 정보와 동의 관리" description="정치 설문과 행동 좌표는 일반 계정 정보와 분리된 민감정보로 취급합니다." /><PrivacyActions /></>; }
