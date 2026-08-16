import Link from "next/link";
import { DemographicsForm } from "@/features/onboarding/demographics-form";

export default function DemographicsPage() { return <section className="card form-card form-card--wide"><Link className="form-brand" href="/">사이 SAI</Link><div className="progress-dots" aria-label="온보딩 3단계 중 3단계"><span className="is-active" /><span className="is-active" /><span className="is-active" /></div><p className="eyebrow">Step 03 · Optional</p><h1>조금 더 나은 분석을 위한<br />선택 질문.</h1><p className="form-card__intro">인구통계 응답은 선택이며 작은 집단의 결과는 공개하지 않습니다.</p><DemographicsForm /></section>; }
