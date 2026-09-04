import { expect, it } from "vitest";
import { canAccessAdmin, canPerform } from "@/lib/auth/permissions";

it("enforces the administrator role matrix", () => { expect(canAccessAdmin("member")).toBe(false); expect(canPerform("analyst", "operate")).toBe(true); expect(canPerform("analyst", "review")).toBe(false); expect(canPerform("reviewer", "publish")).toBe(false); expect(canPerform("admin", "publish")).toBe(true); });
