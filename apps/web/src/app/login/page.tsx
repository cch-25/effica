import Link from "next/link";
import { MessageCircle, Search, ShieldCheck } from "lucide-react";
import { ButtonLink } from "@/components/ui/button";

export const metadata = { title: "로그인" };

export default function LoginPage() {
  return (
    <section className="card form-card">
      <Link className="form-brand" href="/">사이 SAI</Link>
      <p className="eyebrow">Welcome between views</p><h1>한쪽이 아닌,<br />사이를 읽는 시작.</h1>
      <p className="form-card__intro">로그인 후 별도 동의와 설문을 완료하면 관점을 넓히는 맞춤 피드를 볼 수 있습니다.</p>
      <div className="oauth-list">
        <ButtonLink href="/onboarding/consent" variant="secondary" className="oauth-button"><MessageCircle size={16} /> Kakao로 계속하기</ButtonLink>
        <ButtonLink href="/onboarding/consent" variant="secondary" className="oauth-button"><strong>N</strong> Naver로 계속하기</ButtonLink>
        <ButtonLink href="/onboarding/consent" variant="secondary" className="oauth-button"><Search size={16} /> Google로 계속하기</ButtonLink>
        <ButtonLink href="/onboarding/consent" variant="secondary" className="oauth-button"><ShieldCheck size={16} /> 로컬 mock으로 계속하기</ButtonLink>
      </div>
      <p style={{ margin: "1.5rem 0 0", color: "var(--muted)", fontSize: ".78rem" }}>OAuth 제공자 활성 상태에 따라 버튼이 표시됩니다. 로그인하면 이용약관과 개인정보 처리방침 확인 단계로 이동합니다.</p>
    </section>
  );
}
