import { expect, it } from "vitest";
import { canTransitionShareCard } from "@/features/share-cards/model";

it("allows documented share card transitions and keeps revoked terminal", () => { expect(canTransitionShareCard("queued", "rendering")).toBe(true); expect(canTransitionShareCard("rendering", "ready")).toBe(true); expect(canTransitionShareCard("ready", "revoked")).toBe(true); expect(canTransitionShareCard("revoked", "ready")).toBe(false); });
