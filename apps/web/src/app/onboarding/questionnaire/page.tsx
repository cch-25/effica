import Link from "next/link";
import { QuestionnaireForm } from "@/features/onboarding/questionnaire-form";
import { safeReturnTo } from "@/lib/navigation/return-to";

export default async function QuestionnairePage({ searchParams }: { searchParams: Promise<{ returnTo?: string }> }) {
  const returnTo = safeReturnTo((await searchParams).returnTo);
  return <section className="card form-card form-card--wide"><Link className="form-brand" href="/">EFFICA</Link><nav className="progress-dots" aria-label="온보딩 3단계 중 2단계"><span className="is-active" aria-hidden="true" /><span className="is-active" aria-hidden="true" /><span aria-hidden="true" /></nav><p className="eyebrow">Step 02 · Questionnaire</p><h1>지금의 생각을 세 개의 축으로.</h1><p className="form-card__intro">정답은 없습니다. 응답은 현재 자기보고 좌표를 계산하는 데만 사용되며 결과는 언제든 다시 측정할 수 있습니다.</p><QuestionnaireForm returnTo={returnTo} /></section>;
}
