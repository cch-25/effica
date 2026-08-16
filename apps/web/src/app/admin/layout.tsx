import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";
import type { Role } from "@/lib/api/types";
import { canAccessAdmin } from "@/lib/auth/permissions";

export default async function AdminLayout({ children }: { children: ReactNode }) {
  const role = ((await cookies()).get("mock-role")?.value ?? "admin") as Role;
  if (!canAccessAdmin(role)) redirect("/login?returnTo=/admin/sources");
  return <div data-admin-role={role}>{children}</div>;
}
