import { notFound, redirect } from "next/navigation";
import { cookies } from "next/headers";
import { AdminResourcePage } from "@/features/admin/admin-resource-page";
import { RuntimeControlPage } from "@/features/admin/runtime-control-page";
import { adminConfigs } from "@/features/admin/config";
import { canAccessAdmin } from "@/lib/auth/permissions";
import type { UserView } from "@/lib/api/contracts";
import { normalizeRole } from "@/lib/api/contracts";
import { serverApiRequest } from "@/lib/api/server";
import { isMockMode } from "@/lib/api/mode";
import type { Role } from "@/lib/api/types";

export default async function AdminSectionPage({ params }: { params: Promise<{ section: string[] }> }) {
  const { section } = await params; const key = section.join("/"); const config = adminConfigs[key];
  if (!config) notFound();
  const mockRole = isMockMode() ? (await cookies()).get("mock-role")?.value : undefined;
  const user = mockRole ? null : await serverApiRequest<UserView>("/me").catch(() => null);
  const role = (mockRole && ["member", "analyst", "reviewer", "admin"].includes(mockRole) ? mockRole : normalizeRole(user?.role)) as Role;
  if (!canAccessAdmin(role)) redirect(`/admin?returnTo=${encodeURIComponent(`/admin/${key}`)}`);
  return <div data-admin-role={role}>{key === "runtime" ? <RuntimeControlPage role={role} /> : <AdminResourcePage configKey={key} role={role} />}</div>;
}
