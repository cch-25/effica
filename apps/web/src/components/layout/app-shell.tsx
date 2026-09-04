"use client";

import { Avatar } from "@base-ui/react/avatar";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart3, BookOpenText, Boxes, CircleGauge, Compass, FileText, Home, Landmark, Newspaper, Power, SlidersHorizontal, Sparkles, UserRound } from "lucide-react";
import type { ComponentType, ReactNode } from "react";
import type { UserView } from "@/lib/api/contracts";
import { HeadlineBand } from "./headline-band";

type NavItem = {
  href: string;
  label: string;
  icon: ComponentType<{ size?: number; "aria-hidden"?: boolean }>;
  paths: string[];
};

const userNav: NavItem[] = [
  { href: "/", label: "홈", icon: Home, paths: ["/"] },
  { href: "/issues", label: "이슈 비교", icon: Newspaper, paths: ["/issues", "/articles"] },
  { href: "/visualization", label: "기사 관점 지도", icon: Compass, paths: ["/visualization"] },
  { href: "/progress", label: "내 활동", icon: CircleGauge, paths: ["/progress", "/share", "/efficacy"] },
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

export function AppShell({ children, user }: { children: ReactNode; user: UserView | null }) {
  const pathname = usePathname();
  const admin = pathname.startsWith("/admin");
  const minimal = pathname === "/login" || pathname === "/admin" || pathname.startsWith("/onboarding");

  if (minimal) return <main className="minimal-shell">{children}</main>;

  return (
    <div className={admin ? "shell shell--admin" : "shell"}>
      <a className="skip-link" href="#main-content">본문으로 건너뛰기</a>
      {admin ? (
        <aside className="sidebar">
          <Link href="/admin/runtime" className="brand" aria-label="EFFICA 관리자 홈">
            <Avatar.Root className="brand__mark" aria-hidden="true"><Avatar.Fallback>EF</Avatar.Fallback></Avatar.Root>
            <span><strong>EFFICA</strong><small>운영 관제</small></span>
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
      ) : (
        <>
          <HeadlineBand />
          <nav className="site-nav" aria-label="주요 메뉴">
            <Link href="/" className="site-nav__brand" aria-label="EFFICA 홈" aria-current={pathname === "/" ? "page" : undefined}>EFFICA</Link>
            <div className="site-nav__links">
              {userNav.slice(1).map((item) => {
                const { href, label, icon: Icon, paths } = item;
                const active = isActive(pathname, paths);
                return <Link key={href} href={userNavHref(item, user)} className={active ? "site-nav__link is-active" : "site-nav__link"} aria-current={active ? "page" : undefined}><Icon size={17} aria-hidden={true} /><span>{label}</span></Link>;
              })}
            </div>
            <Link href={user ? "/settings/privacy" : "/login"} className="site-nav__account" aria-current={user && pathMatches(pathname, "/settings/privacy") ? "page" : undefined}><UserRound size={17} aria-hidden="true" /><span>{user ? "개인정보 관리" : "로그인"}</span></Link>
          </nav>
        </>
      )}
      <main id="main-content" className="main-content" tabIndex={-1}>
        {children}
      </main>
      {!admin && <nav className="bottom-nav" aria-label="모바일 주요 메뉴">{userNav.map((item) => { const { href, label, icon: Icon, paths } = item; const active = isActive(pathname, paths) || (href === "/progress" && pathname.startsWith("/settings/")); return <Link key={href} href={userNavHref(item, user)} aria-current={active ? "page" : undefined}><Icon size={20} aria-hidden={true} /><span>{label}</span></Link>; })}</nav>}
    </div>
  );
}
