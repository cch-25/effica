"use client";

import { Avatar } from "@base-ui/react/avatar";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart3, BookOpenText, Boxes, CircleGauge, Compass, FileText, Home, Landmark, Newspaper, Power, SlidersHorizontal, Sparkles, UserRound } from "lucide-react";
import type { ReactNode } from "react";
import type { UserView } from "@/lib/api/contracts";
import { HeadlineBand } from "./headline-band";

const userNav = [
  { href: "/", label: "홈", icon: Home, index: "01" },
  { href: "/issues", label: "이슈", icon: Newspaper, index: "02" },
  { href: "/visualization", label: "관점 지도", icon: Compass, index: "03" },
  { href: "/progress", label: "나의 기록", icon: CircleGauge, index: "04" },
];

const adminNav = [
  { href: "/admin/runtime", label: "LLM 사용", icon: Power, index: "01" },
  { href: "/admin/sources", label: "출처", icon: Landmark, index: "02" },
  { href: "/admin/crawls", label: "수집", icon: Boxes, index: "03" },
  { href: "/admin/issues", label: "이슈", icon: Newspaper, index: "04" },
  { href: "/admin/models", label: "모델", icon: Sparkles, index: "05" },
  { href: "/admin/weights", label: "가중치", icon: SlidersHorizontal, index: "06" },
  { href: "/admin/autopilot", label: "Auto Pilot", icon: CircleGauge, index: "07" },
  { href: "/admin/jobs", label: "작업", icon: BarChart3, index: "08" },
  { href: "/admin/audit", label: "감사 로그", icon: FileText, index: "09" },
  { href: "/admin/metrics/efficacy", label: "효능감", icon: BookOpenText, index: "10" },
];

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
              const active = pathname.startsWith(href);
              return <Link key={href} href={href} className={active ? "nav-link is-active" : "nav-link"} aria-current={active ? "page" : undefined}><Icon size={16} aria-hidden="true" /><span className="nav-link__label">{label}</span><span className="nav-link__index" aria-hidden="true">{index}</span></Link>;
            })}
          </nav>
          <div className="sidebar__foot">
            <Link href="/" className="nav-link"><Compass size={18} /> 사용자 웹</Link>
            <Link href={user ? "/settings/privacy" : "/login"} className="profile-chip"><Avatar.Root className="profile-avatar"><Avatar.Fallback>{user?.display_name.slice(0, 1) ?? "?"}</Avatar.Fallback></Avatar.Root><span><strong>{user?.display_name ?? "로그인 필요"}</strong><small>{user?.role ?? "Guest"}</small></span></Link>
          </div>
        </aside>
      ) : (
        <HeadlineBand />
      )}
      {!admin && (
        <nav className="corner-nav" aria-label="빠른 이동">
          <Link href="/" className="corner-nav__link" aria-label="홈" aria-current={pathname === "/" ? "page" : undefined}><Home size={20} aria-hidden="true" /></Link>
          <Link href="/issues" className="corner-nav__link" aria-label="오늘의 이슈" aria-current={pathname.startsWith("/issues") ? "page" : undefined}><Newspaper size={20} aria-hidden="true" /></Link>
          <Link href={user ? "/progress" : "/login"} className="corner-nav__link member-entry" aria-label={user ? `${user.display_name}의 나의 기록` : "로그인"} aria-current={pathname.startsWith("/progress") ? "page" : undefined}><UserRound size={20} aria-hidden="true" /></Link>
        </nav>
      )}
      <main id="main-content" className="main-content" tabIndex={-1}>
        {children}
      </main>
      {!admin && <nav className="bottom-nav" aria-label="모바일 주요 메뉴">{userNav.map(({ href, label, icon: Icon }) => <Link key={href} href={href} aria-current={pathname === href ? "page" : undefined}><Icon size={20} /><span>{label}</span></Link>)}</nav>}
    </div>
  );
}
