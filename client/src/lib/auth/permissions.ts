import type { Role } from "@/lib/api/types";

const rank: Record<Role, number> = { guest: 0, member: 1, analyst: 2, reviewer: 3, admin: 4 };

export function canAccessAdmin(role: Role): boolean {
  return rank[role] >= rank.analyst;
}

export function canPerform(role: Role, action: "view" | "operate" | "review" | "publish"): boolean {
  const required: Record<typeof action, Role> = {
    view: "analyst",
    operate: "analyst",
    review: "reviewer",
    publish: "admin",
  };
  return rank[role] >= rank[required[action]];
}
