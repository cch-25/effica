import Link from "next/link";
import { QuestionnaireForm } from "@/features/onboarding/questionnaire-form";
import { safeReturnTo } from "@/lib/navigation/return-to";

export default async function QuestionnairePage({ searchParams }: { searchParams: Promise<{ returnTo?: string }> }) {
  const returnTo = safeReturnTo((await searchParams).returnTo);
  return <section className="card form-card form-card--wide"><Link className="form-brand" href="/">EFFICA</Link><p className="eyebrow">정치 이념 검사 / 베타</p><h1>내 생각은 좌파와 우파 중 어디에 가까울까</h1><p className="form-card__intro">경제정책으로 좌우 성향을 살펴보고, 권위주의와 자유주의를 구분합니다. 주권주의와 국제주의를 더해 나의 위치를 3차원으로 보여줍니다.</p><p className="questionnaire-disclaimer">원할 때 응답할 수 있는 선택 검사입니다. 문항과 채점 기준을 검토 중인 베타 검사입니다. 정식 검증된 정치성향 진단이 아니며, 지금의 생각을 돌아보는 참고 자료로 이용해 주세요. 기사 평가는 이 결과에 영향을 주지 않습니다.</p><QuestionnaireForm returnTo={returnTo} /></section>;
}
