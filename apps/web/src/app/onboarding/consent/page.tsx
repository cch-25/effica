import Link from "next/link";
import { ConsentForm } from "@/features/onboarding/consent-form";

export default function ConsentPage() { return <section className="card form-card form-card--wide"><Link className="form-brand" href="/">사이 SAI</Link><div className="progress-dots" aria-label="온보딩 3단계 중 1단계"><span className="is-active" /><span /><span /></div><p className="eyebrow">Step 01 · Consent</p><h1>민감한 정보는<br />따로 묻고, 따로 지킵니다.</h1><p className="form-card__intro">정치적 견해와 관련된 응답은 별도 동의가 있어야 처리합니다. 각 목적과 철회 효과를 확인해 주세요.</p><ConsentForm /></section>; }
