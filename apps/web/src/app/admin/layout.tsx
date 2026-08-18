import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import type { ReactNode } from "react";
import { canAccessAdmin } from "@/lib/auth/permissions";
import type { UserView } from "@/lib/api/contracts";
import { normalizeRole } from "@/lib/api/contracts";
import { serverApiRequest } from "@/lib/api/server";
import { isMockMode } from "@/lib/api/mode";
import type { Role } from "@/lib/api/types";

export default async function AdminLayout({ children }: { children: ReactNode }) {
  const mockRole = isMockMode() ? (await cookies()).get("mock-role")?.value : undefined;
  const user = mockRole ? null : await serverApiRequest<UserView>("/me").catch(() => null);
  const role = (mockRole && ["member", "analyst", "reviewer", "admin"].includes(mockRole) ? mockRole : normalizeRole(user?.role)) as Role;
  if (!canAccessAdmin(role)) redirect("/login?returnTo=/admin/sources");
  return <div data-admin-role={role}>{children}</div>;
}
