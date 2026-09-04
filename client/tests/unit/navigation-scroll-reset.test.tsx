import { render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NavigationScrollReset } from "@/components/layout/navigation-scroll-reset";

let pathname = "/issues";

vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
}));

describe("NavigationScrollReset", () => {
  const scrollTo = vi.fn();

  beforeEach(() => {
    pathname = "/issues";
    scrollTo.mockClear();
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
      callback(0);
      return 1;
    });
    Object.defineProperty(window, "scrollTo", { configurable: true, value: scrollTo });
    Object.defineProperty(window.history, "scrollRestoration", { configurable: true, writable: true, value: "auto" });
    document.documentElement.style.scrollBehavior = "smooth";
  });

  afterEach(() => {
    vi.restoreAllMocks();
    document.documentElement.style.scrollBehavior = "";
  });

  it("resets every pathname transition instantly and restores smooth in-page scrolling", () => {
    const view = render(<NavigationScrollReset />);

    expect(window.history.scrollRestoration).toBe("manual");
    expect(scrollTo).toHaveBeenCalledTimes(3);
    expect(scrollTo).toHaveBeenLastCalledWith({ top: 0, left: 0, behavior: "auto" });
    expect(document.documentElement.style.scrollBehavior).toBe("smooth");

    view.rerender(<NavigationScrollReset />);
    expect(scrollTo).toHaveBeenCalledTimes(3);

    pathname = "/issues/issue-housing";
    view.rerender(<NavigationScrollReset />);
    expect(scrollTo).toHaveBeenCalledTimes(6);
    expect(document.documentElement.style.scrollBehavior).toBe("smooth");

    view.unmount();
    expect(window.history.scrollRestoration).toBe("auto");
  });
});
