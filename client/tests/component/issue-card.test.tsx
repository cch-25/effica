import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { IssueCard } from "@/features/issues/issue-card";
import { issues } from "@/mocks/fixtures/content";

afterEach(cleanup);

describe("issue card destination", () => {
  it("promises article comparison only when enough analyzed articles and sources are ready", () => {
    render(<IssueCard issue={issues[0]} />);

    expect(screen.getByText("경제")).toBeVisible();
    expect(screen.getByText("8월 16일 기준")).toBeVisible();
    expect(screen.getByText("기사 3개 / 출처 3곳")).toBeVisible();
    expect(screen.getByRole("link", { name: "보도 비교하기 →" })).toHaveAttribute(
      "href",
      "/issues/issue-housing",
    );
  });

  it("sends an incomplete issue to its preparation status", () => {
    render(<IssueCard issue={{ ...issues[0], articleIds: ["article-01"], sourceCount: 2 }} />);

    expect(screen.getByRole("link", { name: "준비 상태 보기 →" })).toHaveAttribute(
      "href",
      "/issues/issue-housing",
    );
  });
});
