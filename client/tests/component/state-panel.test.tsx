import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { StatePanel } from "@/components/ui/state-panel";

it("announces partial failures without hiding available content", () => { render(<StatePanel state="partial" />); expect(screen.getByText("일부 분석만 도착했습니다")).toBeVisible(); expect(screen.getByRole("status")).toHaveAttribute("aria-live", "polite"); });
