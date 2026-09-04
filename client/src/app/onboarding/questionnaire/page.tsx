import Link from "next/link";
import { QuestionnaireForm } from "@/features/onboarding/questionnaire-form";
import { safeReturnTo } from "@/lib/navigation/return-to";

export default async function QuestionnairePage({ searchParams }: { searchParams: Promise<{ returnTo?: string }> }) {
  const returnTo = safeReturnTo((await searchParams).returnTo);
  return <section className="card form-card form-card--wide"><Link className="form-brand" href="/">EFFICA</Link><nav aria-label="온보딩 단계"><ol><li>1. 동의</li><li aria-current="step"><strong>2. 관점 설문</strong></li><li>3. 선택 정보</li></ol></nav><p className="eyebrow">2단계 / 관점 설문</p><h1>현재 관점을 기록해 주세요.</h1><p className="form-card__intro">정답은 없습니다. 응답은 현재 자기보고 좌표를 계산하는 데만 사용되며 결과는 언제든 다시 측정할 수 있습니다.</p><QuestionnaireForm returnTo={returnTo} /></section>;
}
