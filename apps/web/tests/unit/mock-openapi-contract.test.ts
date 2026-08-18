import { describe, expect, it } from "vitest";
import { mockResponse } from "@/mocks/openapi-contract";

describe("mock OpenAPI runtime contract", () => {
  it("accepts a generated error envelope shape", () => {
    expect(mockResponse("ErrorEnvelope", {
      error: {
        code: "NOT_FOUND",
        message: "missing",
        request_id: "mock-request",
        retryable: false,
        details: {},
      },
    }).error.code).toBe("NOT_FOUND");
  });

  it("rejects drift that TypeScript casts could otherwise hide", () => {
    expect(() => mockResponse("ErrorEnvelope", {
      error: {
        code: "NOT_FOUND",
        request_id: "mock-request",
      },
    } as never)).toThrow(/message.*required/);
  });
});
