"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";
import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/form-controls";
import { isMockMode } from "@/lib/api/mode";

export function AdminLoginForm({ returnTo }: { returnTo: string }) {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const response = await fetch("/api/v1/auth/admin/login", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (!response.ok) {
        setError(response.status === 401
          ? "아이디 또는 비밀번호가 올바르지 않습니다."
          : "로그인 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.");
        return;
      }
      if (isMockMode()) document.cookie = "mock-role=admin; Path=/; SameSite=Lax";
      router.replace(returnTo);
      router.refresh();
    } catch {
      setError("서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="form-card admin-login" aria-labelledby="admin-login-title">
      <Link className="form-brand" href="/">EFFICA</Link>
      <p className="eyebrow">Administrator</p>
      <h1 id="admin-login-title">관리자 로그인</h1>
      <p className="form-card__intro">운영 도구에 접근하려면 관리자 계정을 입력하세요.</p>
      <form onSubmit={(event) => void submit(event)}>
        <TextField
          label="아이디"
          name="username"
          autoComplete="username"
          autoCapitalize="none"
          autoFocus
          required
          value={username}
          onChange={(event) => setUsername(event.target.value)}
        />
        <TextField
          label="비밀번호"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        {error ? <p className="form-error admin-login__error" role="alert">{error}</p> : null}
        <Button className="admin-login__submit" type="submit" disabled={submitting}>
          {submitting ? "확인 중" : "접속하기"}
        </Button>
      </form>
      <p className="admin-login__user-link">일반 사용자라면 <Link href="/login">Google 로그인</Link>을 이용해 주세요.</p>
    </section>
  );
}
