import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { AppShell } from "@/components/layout/app-shell";
import { HeadlineBand } from "@/components/layout/headline-band";
import type { UserView } from "@/lib/api/contracts";

const navigation = vi.hoisted(() => ({ pathname: "/" }));
const originalApiMode = process.env.NEXT_PUBLIC_API_MODE;
const originalMatchMedia = window.matchMedia;

vi.mock("next/navigation", () => ({
  usePathname: () => navigation.pathname,
}));

const member: UserView = {
  id: "user-1",
  display_name: "김시민",
  role: "MEMBER",
  consent_complete: true,
  onboarding_complete: true,
  behavioral_profile_active: true,
};

beforeAll(() => {
  process.env.NEXT_PUBLIC_API_MODE = "mock";
  window.matchMedia = vi.fn().mockReturnValue({ matches: true }) as unknown as typeof window.matchMedia;
});

afterAll(() => {
  if (originalApiMode === undefined) delete process.env.NEXT_PUBLIC_API_MODE;
  else process.env.NEXT_PUBLIC_API_MODE = originalApiMode;
  window.matchMedia = originalMatchMedia;
});

afterEach(() => {
  cleanup();
  navigation.pathname = "/";
});

function withQueryClient(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function renderShell(pathname: string, user: UserView | null = member) {
  navigation.pathname = pathname;
  return render(withQueryClient(<AppShell user={user}><p>본문</p></AppShell>));
}

describe("app shell navigation", () => {
  it("shows the product areas and member account as explicit desktop links", () => {
    renderShell("/visualization");

    const nav = screen.getByRole("navigation", { name: "주요 메뉴" });
    expect(within(nav).getByRole("link", { name: "EFFICA 홈" })).toHaveAttribute("href", "/");
    expect(within(nav).getByRole("link", { name: "이슈 비교" })).toHaveAttribute("href", "/issues");
    expect(within(nav).getByRole("link", { name: "기사 관점 지도" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "내 활동" })).toHaveAttribute("href", "/progress");
    expect(within(nav).getByRole("link", { name: "개인정보 관리" })).toHaveAttribute("href", "/settings/privacy");
  });

  it("shows a clear login link when there is no member", () => {
    renderShell("/issues", null);

    const desktop = screen.getByRole("navigation", { name: "주요 메뉴" });
    const mobile = screen.getByRole("navigation", { name: "모바일 주요 메뉴" });
    expect(within(desktop).getByRole("link", { name: "로그인" })).toHaveAttribute("href", "/login");
    expect(within(desktop).getByRole("link", { name: "내 활동" })).toHaveAttribute("href", "/login?returnTo=%2Fprogress");
    expect(within(mobile).getByRole("link", { name: "내 활동" })).toHaveAttribute("href", "/login?returnTo=%2Fprogress");
  });

  it.each([
    ["/issues/issue-1", "이슈 비교"],
    ["/articles/article-1", "이슈 비교"],
    ["/progress", "내 활동"],
    ["/share/new", "내 활동"],
    ["/efficacy", "내 활동"],
  ])("marks the parent menu for %s as current", (pathname, label) => {
    renderShell(pathname);

    const desktop = screen.getByRole("navigation", { name: "주요 메뉴" });
    const mobile = screen.getByRole("navigation", { name: "모바일 주요 메뉴" });
    expect(within(desktop).getByRole("link", { name: label })).toHaveAttribute("aria-current", "page");
    expect(within(mobile).getByRole("link", { name: label })).toHaveAttribute("aria-current", "page");
  });

  it("keeps four explicit destinations in the mobile menu", () => {
    renderShell("/");

    const nav = screen.getByRole("navigation", { name: "모바일 주요 메뉴" });
    expect(within(nav).getAllByRole("link")).toHaveLength(4);
    expect(within(nav).getByRole("link", { name: "홈" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "이슈 비교" })).toBeVisible();
    expect(within(nav).getByRole("link", { name: "기사 관점 지도" })).toBeVisible();
    expect(within(nav).getByRole("link", { name: "내 활동" })).toBeVisible();
  });

  it("keeps privacy settings inside the mobile activity context", () => {
    renderShell("/settings/privacy");

    const desktop = screen.getByRole("navigation", { name: "주요 메뉴" });
    const mobile = screen.getByRole("navigation", { name: "모바일 주요 메뉴" });
    expect(within(desktop).getByRole("link", { name: "개인정보 관리" })).toHaveAttribute("aria-current", "page");
    expect(within(mobile).getByRole("link", { name: "내 활동" })).toHaveAttribute("aria-current", "page");
  });

  it("uses purpose-first administrator labels and marks nested routes", () => {
    renderShell("/admin/models/model-1");

    const nav = screen.getByRole("navigation", { name: "관리자 메뉴" });
    expect(within(nav).getByRole("link", { name: "LLM 운영" })).toBeVisible();
    expect(within(nav).getByRole("link", { name: "출처 관리" })).toBeVisible();
    expect(within(nav).getByRole("link", { name: "콘텐츠 수집" })).toBeVisible();
    expect(within(nav).getByRole("link", { name: "이슈 검수" })).toBeVisible();
    expect(within(nav).getByRole("link", { name: "분석 모델" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "추천 가중치" })).toBeVisible();
    expect(within(nav).getByRole("link", { name: "추천 승인" })).toBeVisible();
    expect(within(nav).getByRole("link", { name: "작업 큐" })).toBeVisible();
    expect(within(nav).getByRole("link", { name: "변경 이력" })).toBeVisible();
    expect(within(nav).getByRole("link", { name: "효능감 통계" })).toBeVisible();
  });
});

describe("headline band", () => {
  it("keeps the latest article label visible and identifies an external destination", () => {
    render(withQueryClient(<HeadlineBand />));

    const band = screen.getByRole("banner", { name: "최신 기사" });
    expect(within(band).getByText("최신 기사")).toBeVisible();
    const story = within(band).getByRole("link", { name: /외부 기사.*새 창에서 열림/ });
    expect(story).toHaveAttribute("target", "_blank");
    expect(story).toHaveAttribute("rel", "noreferrer");
  });
});
