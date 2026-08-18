import { notFound, redirect } from "next/navigation";
import { cookies } from "next/headers";
import { AdminResourcePage } from "@/features/admin/admin-resource-page";
import { adminConfigs } from "@/features/admin/config";
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
  if (!user && !mockRole) redirect(`/login?returnTo=${encodeURIComponent(`/admin/${key}`)}`);
  const role = (mockRole && ["member", "analyst", "reviewer", "admin"].includes(mockRole) ? mockRole : normalizeRole(user?.role)) as Role;
  return <AdminResourcePage configKey={key} role={role} />;
}
