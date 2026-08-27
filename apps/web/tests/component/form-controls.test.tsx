import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { CheckboxField } from "@/components/ui/form-controls";

it("체크박스를 표시 라벨과 설명에 명시적으로 연결한다", () => {
  render(<CheckboxField label="서비스 이용약관" description="필수 동의 항목입니다." />);

  const checkbox = screen.getByRole("checkbox", { name: "서비스 이용약관" });
  expect(checkbox).toHaveAccessibleDescription("필수 동의 항목입니다.");
});
