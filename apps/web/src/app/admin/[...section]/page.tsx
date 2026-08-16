import { cookies } from "next/headers";
import { notFound } from "next/navigation";
import type { Role } from "@/lib/api/types";
import { AdminResourcePage } from "@/features/admin/admin-resource-page";
import { adminConfigs } from "@/features/admin/config";

export default async function AdminSectionPage({ params }: { params: Promise<{ section: string[] }> }) {
  const { section } = await params; const key = section.join("/"); const config = adminConfigs[key];
  if (!config) notFound();
  const role = ((await cookies()).get("mock-role")?.value ?? "admin") as Role;
  return <AdminResourcePage config={config} role={role} />;
}
