import Link from "next/link";
import { ConsentForm } from "@/features/onboarding/consent-form";
import { safeReturnTo } from "@/lib/navigation/return-to";

export default async function ConsentPage({ searchParams }: { searchParams: Promise<{ returnTo?: string }> }) {
  const returnTo = safeReturnTo((await searchParams).returnTo);
  return <section className="card form-card form-card--wide"><Link className="form-brand" href="/">EFFICA</Link><h1>이용 동의</h1><p className="form-card__intro">기사 평가에 필요한 정보 처리 목적을 확인해 주세요. 정치성향 검사는 내 활동에서 원할 때 진행할 수 있습니다.</p><ConsentForm returnTo={returnTo} /></section>;
}
