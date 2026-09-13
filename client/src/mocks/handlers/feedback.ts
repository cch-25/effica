import { http, HttpResponse } from "msw";
import { z } from "zod";
import type { components } from "@/lib/api/generated/schema";
import { mockResponse } from "../openapi-contract";

const entries = new Map<string, components["schemas"]["FeedbackView"]>();
const createSchema = z.object({
  name: z.string().trim().min(1).max(30),
  content: z.string().trim().min(1).refine((value) => Array.from(value).length <= 200),
  submission_key: z.uuid(),
});

export const feedbackHandlers = [
  http.get("/api/v1/feedback", ({ request }) => {
    const cursor = new URL(request.url).searchParams.get("cursor");
    const rows = [...entries.values()].reverse();
    const start = cursor ? rows.findIndex((row) => row.id === cursor) + 1 : 0;
    const items = rows.slice(start, start + 20);
    return HttpResponse.json(mockResponse("FeedbackPage", { items, next_cursor: rows.length > start + 20 ? items.at(-1)!.id : null }));
  }),
  http.post("/api/v1/feedback", async ({ request }) => {
    const parsed = createSchema.safeParse(await request.json());
    if (!parsed.success) return HttpResponse.json({ error: { message: "이름과 200자 이내의 내용을 입력해 주세요." } }, { status: 422 });
    const { name, content, submission_key: key } = parsed.data;
    const existing = entries.get(key);
    if (existing && (existing.name !== name || existing.content !== content)) return HttpResponse.json({ error: { message: "작성 내용이 변경되었습니다." } }, { status: 409 });
    const entry = existing ?? { id: String(entries.size + 1).padStart(26, "0"), name, content, created_at: new Date().toISOString() };
    entries.set(key, entry);
    return HttpResponse.json(mockResponse("FeedbackView", entry), { status: 201 });
  }),
];
