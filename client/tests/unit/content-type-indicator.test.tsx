import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ContentTypeIndicator, ContentTypeLine, issueOrdinalLabel } from "@/components/ui/content-type-indicator";

describe("content type indicator", () => {
  it("numbers visible issues with a dynamic alphabetic sequence", () => {
    expect([0, 1, 2, 25, 26].map(issueOrdinalLabel)).toEqual(["A", "B", "C", "Z", "AA"]);
  });

  it("visibly distinguishes an issue from an article", () => {
    const { rerender } = render(<ContentTypeIndicator kind="issue" issueOrdinal={1} />);
    expect(screen.getByText("이슈 B")).toHaveAttribute("data-content-type", "issue");

    rerender(<ContentTypeIndicator kind="article" />);
    expect(screen.getByText("기사")).toHaveAttribute("data-content-type", "article");
  });

  it("keeps a wrapping title in a separate aligned column", () => {
    const { container } = render(<ContentTypeLine kind="issue" issueOrdinal={0}>여러 줄로 표시되는 긴 이슈 제목</ContentTypeLine>);

    expect(container.querySelector("[data-content-type-line]")).toContainElement(screen.getByText("이슈 A"));
    expect(screen.getByText("여러 줄로 표시되는 긴 이슈 제목")).toHaveAttribute("data-content-type-copy");
  });
});
