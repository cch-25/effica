import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { AppShell } from "@/components/layout/app-shell";
import { HeadlineBand } from "@/components/layout/headline-band";
import type { UserView } from "@/lib/api/contracts";

const navigation = vi.hoisted(() => ({ pathname: "/" }));
const api = vi.hoisted(() => ({ request: vi.fn() }));
const originalApiMode = process.env.NEXT_PUBLIC_API_MODE;
const originalMatchMedia = window.matchMedia;

vi.mock("@/lib/api/client", () => ({ apiRequest: api.request }));

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
  api.request.mockReset();
  navigation.pathname = "/";
  process.env.NEXT_PUBLIC_API_MODE = "mock";
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
  it("shows an honest unavailable state in mock mode without a stale link", () => {
    render(withQueryClient(<HeadlineBand />));

    const band = screen.getByRole("banner", { name: "최신 기사" });
    expect(within(band).getByText("최신 기사")).toBeVisible();
    expect(within(band).getByRole("status")).toHaveTextContent("현재 표시할 최신 기사가 없습니다.");
    expect(within(band).queryByRole("link")).not.toBeInTheDocument();
    expect(api.request).not.toHaveBeenCalled();
  });

  it("shows loading while the live feed request is pending", () => {
    process.env.NEXT_PUBLIC_API_MODE = "real";
    api.request.mockImplementation(() => new Promise(() => undefined));

    render(withQueryClient(<HeadlineBand />));

    expect(screen.getByRole("status")).toHaveTextContent("최신 기사를 불러오는 중입니다.");
  });

  it("keeps an empty live feed empty instead of substituting old news", async () => {
    process.env.NEXT_PUBLIC_API_MODE = "real";
    api.request.mockResolvedValue({ items: [], next_cursor: null, personalized: false });

    render(withQueryClient(<HeadlineBand />));

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("현재 표시할 최신 기사가 없습니다."));
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("reports a live feed error without substituting old news", async () => {
    process.env.NEXT_PUBLIC_API_MODE = "real";
    api.request.mockRejectedValue(new Error("feed unavailable"));

    render(withQueryClient(<HeadlineBand />));

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("최신 기사를 불러오지 못했습니다."));
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("links a live feed headline to its article page", async () => {
    process.env.NEXT_PUBLIC_API_MODE = "real";
    api.request.mockResolvedValue({
      items: [{
        analysis_provider: "openai",
        analysis_status: "READY",
        article_id: "article-current",
        coordinate: { x: 0, y: 0, z: 0 },
        issue_id: "issue-current",
        published_at: "2026-09-04T01:00:00Z",
        rank: 1,
        reason_code: "balanced",
        score_version_id: "score-current",
        source: "테스트 언론",
        title: "현재 피드 헤드라인",
      }],
      next_cursor: null,
      personalized: false,
    });

    render(withQueryClient(<HeadlineBand />));

    await waitFor(() => expect(screen.getByRole("link", { name: "현재 피드 헤드라인" })).toHaveAttribute("href", "/articles/article-current"));
  });
});
