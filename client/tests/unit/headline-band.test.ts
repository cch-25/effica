import { describe, expect, it } from "vitest";
import { decodeHeadlineEntities } from "@/components/layout/headline-band";

describe("headline band", () => {
  it("decodes nested and numeric HTML entities without rendering HTML", () => {
    expect(decodeHeadlineEntities("소방청&amp;middot;교육부 &#39;119안심콜&#39;")).toBe("소방청·교육부 '119안심콜'");
  });
});
