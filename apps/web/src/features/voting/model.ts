import { z } from "zod";

export const voteSchema = z.object({
  x: z.number().int().min(-100).max(100),
  y: z.number().int().min(-100).max(100),
  z: z.number().int().min(-100).max(100),
  sensationalism: z.number().int().min(0).max(100),
});

export type VoteInput = z.infer<typeof voteSchema>;
