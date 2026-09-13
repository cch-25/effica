"use client";

import { Avatar } from "@base-ui/react/avatar";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { BarChart3, BookOpenText, Boxes, CircleGauge, Compass, FileText, Home, Landmark, MessageSquare, Newspaper, Orbit, Power, SlidersHorizontal, Sparkles, UserRound } from "lucide-react";
import { useState, type ComponentType, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import type { UserView } from "@/lib/api/contracts";
import { apiRequest } from "@/lib/api/client";
import { NewspaperMasthead } from "./newspaper-masthead";

type NavItem = {
  href: string;
  label: string;
  icon: ComponentType<{ size?: number; "aria-hidden"?: boolean }>;
  paths: string[];
};

const userNav: NavItem[] = [
  { href: "/", label: "홈", icon: Home, paths: ["/"] },
  { href: "/articles", label: "기사 모음", icon: BookOpenText, paths: ["/articles"] },
  { href: "/issues", label: "이슈 비교", icon: Newspaper, paths: ["/issues"] },
  { href: "/algo", label: "알고리즘", icon: Orbit, paths: ["/algo"] },
  { href: "/progress", label: "내 활동", icon: CircleGauge, paths: ["/progress", "/share", "/efficacy"] },
  { href: "/feedback", label: "피드백", icon: MessageSquare, paths: ["/feedback"] },
];

const adminNav = [
  { href: "/admin/runtime", label: "LLM 운영", icon: Power, index: "01" },
  { href: "/admin/sources", label: "출처 관리", icon: Landmark, index: "02" },
  { href: "/admin/crawls", label: "콘텐츠 수집", icon: Boxes, index: "03" },
  { href: "/admin/issues", label: "이슈 검수", icon: Newspaper, index: "04" },
  { href: "/admin/models", label: "분석 모델", icon: Sparkles, index: "05" },
  { href: "/admin/weights", label: "추천 가중치", icon: SlidersHorizontal, index: "06" },
  { href: "/admin/autopilot", label: "추천 승인", icon: CircleGauge, index: "07" },
  { href: "/admin/jobs", label: "작업 큐", icon: BarChart3, index: "08" },
  { href: "/admin/audit", label: "변경 이력", icon: FileText, index: "09" },
  { href: "/admin/metrics/efficacy", label: "효능감 통계", icon: BookOpenText, index: "10" },
];

function pathMatches(pathname: string, path: string) {
  return path === "/" ? pathname === path : pathname === path || pathname.startsWith(`${path}/`);
}

function isActive(pathname: string, paths: string[]) {
  return paths.some((path) => pathMatches(pathname, path));
}

function userNavHref(item: NavItem, user: UserView | null) {
  return item.href === "/progress" && !user ? "/login?returnTo=%2Fprogress" : item.href;
}

function SiteHeader({ date, pathname, user, logoutState, onLogout }: {
  date: string; pathname: string; user: UserView | null;
  logoutState: "idle" | "pending" | "error"; onLogout: () => void;
}) {
  return <div className="site-header">
    <NewspaperMasthead date={date} section={pathname.startsWith("/admin") ? "관리자" : pathname === "/" ? "종합" : pathname.startsWith("/articles") ? "기사" : pathname.startsWith("/issues") ? "보도 비교" : pathname.startsWith("/algo") ? "알고리즘" : "독자"} />
    <nav className="site-nav" aria-label="주요 메뉴">
      <Link href="/" className="site-nav__brand" aria-label="종합 1면" aria-current={pathname === "/" ? "page" : undefined}>종합 1면</Link>
      <div className="site-nav__links">
        {userNav.slice(1).map((item) => {
          const { href, label, icon: Icon, paths } = item;
          const active = isActive(pathname, paths);
          return <Link key={href} href={userNavHref(item, user)} className={active ? "site-nav__link is-active" : "site-nav__link"} aria-current={active ? "page" : undefined}><Icon size={17} aria-hidden={true} /><span>{label}</span></Link>;
        })}
      </div>
      <div className="site-nav__account-actions">
        <Link href={user ? "/settings/privacy" : "/login"} className="site-nav__account" aria-current={user && pathMatches(pathname, "/settings/privacy") ? "page" : undefined}><UserRound size={17} aria-hidden="true" /><span>{user ? "개인정보 관리" : "로그인"}</span></Link>
        {user && <Button type="button" variant="ghost" className="site-nav__logout" disabled={logoutState === "pending"} onClick={onLogout}>{logoutState === "pending" ? "처리 중" : logoutState === "error" ? "다시 시도" : "로그아웃"}</Button>}
        {logoutState === "error" && <span className="sr-only" role="alert">로그아웃하지 못했습니다. 다시 시도해 주세요.</span>}
      </div>
    </nav>
  </div>;
}

export function AppShell({ children, user, editionDate = "" }: { children: ReactNode; user: UserView | null; editionDate?: string }) {
  const pathname = usePathname();
  const router = useRouter();
  const [logoutState, setLogoutState] = useState<"idle" | "pending" | "error">("idle");
  const admin = pathname.startsWith("/admin");
  const minimal = pathname === "/login" || pathname === "/admin" || pathname.startsWith("/onboarding");
  const logout = async () => {
    setLogoutState("pending");
    try {
      await apiRequest<void>("/auth/logout", { method: "POST", authFailureMode: "return-error" });
      router.replace("/");
    } catch {
      setLogoutState("error");
    }
  };

  const header = <SiteHeader date={editionDate} pathname={pathname} user={user} logoutState={logoutState} onLogout={() => void logout()} />;

  if (minimal) return <div className={`newspaper-account${pathname === "/login" ? " newspaper-account--login" : ""}`}><a className="skip-link" href="#main-content">본문으로 건너뛰기</a>{header}<main id="main-content" className="minimal-shell" tabIndex={-1}>{children}</main></div>;

  return (
    <div className={admin ? "shell shell--admin" : pathname === "/" ? "shell shell--frontpage" : "shell"}>
      <a className="skip-link" href="#main-content">본문으로 건너뛰기</a>
      {header}
      {admin ? (
        <aside className="sidebar">
          <Link href="/admin/runtime" className="brand" aria-label="EFFICA 관리자 홈">
            <Avatar.Root className="brand__mark" aria-hidden="true"><Avatar.Fallback>EF</Avatar.Fallback></Avatar.Root>
            <span><strong>에피카</strong><small>관리자 지면 안내</small></span>
          </Link>
          <nav aria-label="관리자 메뉴">
            {adminNav.map(({ href, label, icon: Icon, index }) => {
              const active = pathMatches(pathname, href);
              return <Link key={href} href={href} className={active ? "nav-link is-active" : "nav-link"} aria-current={active ? "page" : undefined}><Icon size={16} aria-hidden="true" /><span className="nav-link__label">{label}</span><span className="nav-link__index" aria-hidden="true">{index}</span></Link>;
            })}
          </nav>
          <div className="sidebar__foot">
            <Link href="/" className="nav-link"><Compass size={18} /> 사용자 웹</Link>
            <Link href={user ? "/settings/privacy" : "/login"} className="profile-chip"><Avatar.Root className="profile-avatar"><Avatar.Fallback>{user?.display_name.slice(0, 1) ?? "?"}</Avatar.Fallback></Avatar.Root><span><strong>{user?.display_name ?? "로그인 필요"}</strong><small>{user?.role ?? "Guest"}</small></span></Link>
          </div>
        </aside>
      ) : null}
      <main id="main-content" className="main-content" tabIndex={-1}>
        {children}
      </main>
      {!admin && <footer className="newspaper-footer"><Link href="/" aria-label="에피카 홈">에피카 <small>EFFICA</small></Link><p>같은 이슈를 여러 관점에서 읽고, 근거를 비교합니다.</p><nav aria-label="푸터 메뉴"><Link href="/articles">기사 모음</Link><Link href="/issues">이슈 비교</Link><Link href="/settings/privacy">개인정보 관리</Link></nav><small>© EFFICA</small></footer>}
      {!admin && <nav className="bottom-nav" aria-label="모바일 주요 메뉴">{userNav.map((item) => { const { href, label, icon: Icon, paths } = item; const active = isActive(pathname, paths) || (href === "/progress" && pathname.startsWith("/settings/")); return <Link key={href} href={userNavHref(item, user)} aria-current={active ? "page" : undefined}><Icon size={20} aria-hidden={true} /><span>{label}</span></Link>; })}</nav>}
    </div>
  );
}
