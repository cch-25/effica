import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { AdminLoginForm } from "@/features/admin/admin-login-form";
import type { UserView } from "@/lib/api/contracts";
import { normalizeRole } from "@/lib/api/contracts";
import { isMockMode } from "@/lib/api/mode";
import { serverApiRequest } from "@/lib/api/server";
import type { Role } from "@/lib/api/types";
import { canAccessAdmin } from "@/lib/auth/permissions";

export const metadata = { title: "관리자 로그인" };

function adminReturnTo(candidate: string | undefined): string {
  return candidate?.startsWith("/admin/") ? candidate : "/admin/runtime";
}

export default async function AdminLoginPage({
  searchParams,
}: {
  searchParams: Promise<{ returnTo?: string }>;
}) {
  const returnTo = adminReturnTo((await searchParams).returnTo);
  const mockRole = isMockMode() ? (await cookies()).get("mock-role")?.value : undefined;
  const user = mockRole ? null : await serverApiRequest<UserView>("/me").catch(() => null);
  const role = (mockRole && ["member", "analyst", "reviewer", "admin"].includes(mockRole)
    ? mockRole
    : normalizeRole(user?.role)) as Role;

  if (canAccessAdmin(role)) redirect(returnTo);
  return <AdminLoginForm returnTo={returnTo} />;
}
