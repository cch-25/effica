"use client";

import Link from "next/link";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { apiRequest } from "@/lib/api/client";
import type { UserView } from "@/lib/api/contracts";
import { Button } from "@/components/ui/button";

export function AccountMenu({ user }: { user: UserView | null }) {
  const router = useRouter();
  const pathname = usePathname();
  const cache = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!user) return <Link className="site-nav__account" href={`/login?returnTo=${encodeURIComponent(pathname)}`}>로그인</Link>;
  const logout = async () => {
    setBusy(true); setError("");
    try {
      await apiRequest<void>("/auth/logout", { method: "POST", authFailureMode: "return-error" });
      cache.clear();
      router.replace("/");
      router.refresh();
    } catch { setError("로그아웃하지 못했습니다. 다시 시도해 주세요."); }
    finally { setBusy(false); }
  };
  return <details className="account-menu">
    <summary>{user.display_name}</summary>
    <div><Link href="/settings/privacy">개인정보 관리</Link>
      {user.role === "ADMIN" && <Link href="/admin/issues">관리자</Link>}
      <Button variant="ghost" disabled={busy} onClick={() => void logout()}>{busy ? "로그아웃 중" : "로그아웃"}</Button>
      {error && <p role="alert">{error}</p>}
    </div>
  </details>;
}
