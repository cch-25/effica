"use client";

import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/form-controls";
import { isMockMode } from "@/lib/api/mode";

export function AdminLoginForm({ returnTo }: { returnTo: string }) {
  return <CredentialsLoginForm returnTo={returnTo} admin />;
}

export function CredentialsLoginForm({ returnTo, admin = false }: { returnTo: string; admin?: boolean }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const title = admin ? "관리자 로그인" : "아이디 로그인";
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let active = true;
    const markReady = () => {
      if (active) setReady(true);
    };
    if (isMockMode()) {
      void import("@/mocks/browser")
        .then(({ startMockWorker }) => startMockWorker())
        .then(markReady, markReady);
    } else {
      markReady();
    }
    return () => {
      active = false;
    };
  }, []);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      if (isMockMode()) {
        const { startMockWorker } = await import("@/mocks/browser");
        await startMockWorker();
      }
      const response = await fetch(admin ? "/api/v1/auth/admin/login" : "/api/v1/auth/login", {
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
      if (isMockMode()) document.cookie = `mock-role=${admin ? "admin" : "member"}; Path=/; SameSite=Lax`;
      queryClient.clear();
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
      <p className="eyebrow">{admin ? "관리자 접속" : "데모 계정"}</p>
      <h1 id="admin-login-title">{title}</h1>
      <p className="form-card__intro">{admin ? "운영 도구에 접근하려면 관리자 계정을 입력하세요." : "활동 기록이 쌓인 데모 계정으로 서비스를 둘러보세요."}</p>
      <form onSubmit={(event) => void submit(event)}>
        <TextField
          label="아이디"
          name="username"
          autoComplete="username"
          autoCapitalize="none"
          autoFocus
          required
          disabled={!ready || submitting}
          value={username}
          onChange={(event) => setUsername(event.target.value)}
        />
        <TextField
          label="비밀번호"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          disabled={!ready || submitting}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        {error ? <p className="form-error admin-login__error" role="alert">{error}</p> : null}
        <Button className="admin-login__submit" type="submit" disabled={!ready || submitting}>
          {!ready ? "준비 중" : submitting ? "확인 중" : "접속하기"}
        </Button>
      </form>
      <p className="admin-login__user-link"><Link href={`/login?returnTo=${encodeURIComponent(returnTo)}`}>다른 방법으로 로그인</Link></p>
    </section>
  );
}
