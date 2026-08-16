import { expect, it } from "vitest";
import { voteSchema } from "@/features/voting/model";

it("accepts documented vote ranges and rejects out-of-range input", () => { expect(voteSchema.safeParse({ x: -100, y: 0, z: 100, sensationalism: 100 }).success).toBe(true); expect(voteSchema.safeParse({ x: -101, y: 0, z: 0, sensationalism: 20 }).success).toBe(false); });
