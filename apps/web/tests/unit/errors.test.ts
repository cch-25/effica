import { expect, it } from "vitest";
import { mapErrorCode } from "@/lib/api/errors";

it("maps stable error codes to user-safe messages", () => { expect(mapErrorCode("CONSENT_REQUIRED")).toContain("별도 동의"); expect(mapErrorCode("UNKNOWN_CODE")).toContain("잠시 후"); });
