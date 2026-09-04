import Link from "next/link";
import { DemographicsForm } from "@/features/onboarding/demographics-form";
import { safeReturnTo } from "@/lib/navigation/return-to";

export default async function DemographicsPage({ searchParams }: { searchParams: Promise<{ returnTo?: string }> }) {
  const returnTo = safeReturnTo((await searchParams).returnTo);
  return <section className="card form-card form-card--wide"><Link className="form-brand" href="/">EFFICA</Link><nav aria-label="온보딩 단계"><ol><li>1. 동의</li><li>2. 관점 설문</li><li aria-current="step"><strong>3. 선택 정보</strong></li></ol></nav><p className="eyebrow">3단계 / 선택 정보</p><h1>선택 정보를 입력하거나 건너뛰세요.</h1><p className="form-card__intro">인구통계 응답은 선택이며 작은 집단의 결과는 공개하지 않습니다.</p><DemographicsForm returnTo={returnTo} /></section>;
}
