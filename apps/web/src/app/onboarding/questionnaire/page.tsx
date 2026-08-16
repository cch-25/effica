import Link from "next/link";
import { QuestionnaireForm } from "@/features/onboarding/questionnaire-form";

export default function QuestionnairePage() { return <section className="card form-card form-card--wide"><Link className="form-brand" href="/">사이 SAI</Link><div className="progress-dots" aria-label="온보딩 3단계 중 2단계"><span className="is-active" /><span className="is-active" /><span /></div><p className="eyebrow">Step 02 · Questionnaire v3</p><h1>지금의 생각을<br />세 개의 축으로.</h1><p className="form-card__intro">정답은 없습니다. 응답은 현재 자기보고 좌표를 계산하는 데만 사용되며 결과는 언제든 다시 측정할 수 있습니다.</p><QuestionnaireForm /></section>; }
