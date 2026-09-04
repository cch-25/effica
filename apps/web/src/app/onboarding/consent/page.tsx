import Link from "next/link";
import { ConsentForm } from "@/features/onboarding/consent-form";
import { safeReturnTo } from "@/lib/navigation/return-to";

export default async function ConsentPage({ searchParams }: { searchParams: Promise<{ returnTo?: string }> }) {
  const returnTo = safeReturnTo((await searchParams).returnTo);
  return <section className="card form-card form-card--wide"><Link className="form-brand" href="/">EFFICA</Link><nav aria-label="온보딩 단계"><ol><li aria-current="step"><strong>1. 동의</strong></li><li>2. 관점 설문</li><li>3. 선택 정보</li></ol></nav><p className="eyebrow">1단계 / 동의</p><h1>민감한 정보 처리에 동의해 주세요.</h1><p className="form-card__intro">정치적 견해와 관련된 응답은 별도 동의가 있어야 처리합니다. 각 목적과 철회 효과를 확인해 주세요.</p><ConsentForm returnTo={returnTo} /></section>;
}
