import Link from "next/link";
import { ButtonLink } from "@/components/ui/button";
import { CredentialsLoginForm } from "@/features/admin/admin-login-form";
import { LoginOptions } from "@/features/auth/login-options";
import { safeReturnTo } from "@/lib/navigation/return-to";

export const metadata = { title: "로그인" };

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ returnTo?: string; oauthError?: string; method?: string }> }) {
  const params = await searchParams;
  const returnTo = safeReturnTo(params.returnTo);
  if (params.method === "id") return <CredentialsLoginForm returnTo={returnTo} />;
  const oauthError = params.oauthError === "cancelled"
    ? "Google 로그인이 취소되었습니다. 다시 시도해 주세요."
    : params.oauthError === "failed"
      ? "Google 로그인을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요."
      : null;
  return (
    <section className="login-page" aria-labelledby="login-title">
      <header className="login-page__heading">
        <h1 id="login-title">로그인</h1>
        <p>기사에 내 평가를 남기고,<br />읽은 기록을 확인하세요.</p>
      </header>
      {oauthError ? <p role="alert" className="form-error">{oauthError}</p> : null}
      <LoginOptions returnTo={returnTo} />
      <div className="oauth-list"><ButtonLink variant="secondary" className="oauth-button" href={`/login?method=id&returnTo=${encodeURIComponent(returnTo)}`}>아이디 로그인</ButtonLink></div>
      <p className="login-page__notice">처음 이용하시면 이용 동의 후 원래 보던 화면으로 돌아갑니다.</p>
      <Link className="login-page__back" href={returnTo}>로그인 없이 둘러보기</Link>
    </section>
  );
}
