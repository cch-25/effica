import Link from "next/link";
import { LoginOptions } from "@/features/auth/login-options";
import { safeReturnTo } from "@/lib/navigation/return-to";

export const metadata = { title: "로그인" };

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ returnTo?: string; oauthError?: string }> }) {
  const params = await searchParams;
  const returnTo = safeReturnTo(params.returnTo);
  const oauthError = params.oauthError === "cancelled"
    ? "Google 로그인이 취소되었습니다. 다시 시도해 주세요."
    : params.oauthError === "failed"
      ? "Google 로그인을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요."
      : null;
  return (
    <section className="card form-card">
      <Link className="form-brand" href="/">EFFICA</Link>
      <p className="eyebrow">Welcome between views</p><h1>한쪽이 아닌,<br />사이를 읽는 시작.</h1>
      <p className="form-card__intro">로그인 후 별도 동의와 설문을 완료하면 관점을 넓히는 맞춤 피드를 볼 수 있습니다.</p>
      {oauthError ? <p role="alert" className="form-error">{oauthError}</p> : null}
      <LoginOptions returnTo={returnTo} />
      <p style={{ margin: "1.5rem 0 0", color: "var(--muted)", fontSize: ".78rem" }}>Google 계정으로만 로그인할 수 있습니다. 로그인하면 이용약관과 개인정보 처리방침 확인 단계로 이동합니다.</p>
    </section>
  );
}
