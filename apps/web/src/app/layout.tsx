import type { Metadata } from "next";
import "./globals.css";
import "./base-ui.css";
import { Providers } from "./providers";
import { AppShell } from "@/components/layout/app-shell";
import { serverApiRequest } from "@/lib/api/server";
import type { UserView } from "@/lib/api/contracts";

export const metadata: Metadata = {
  title: { default: "EFFICA — 관점 사이를 읽다", template: "%s | EFFICA" },
  description: "같은 이슈를 여러 관점에서 읽고, 근거를 비교하는 뉴스 플랫폼",
};

export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const user = await serverApiRequest<UserView>("/me").catch(() => null);
  return (
    <html lang="ko" data-scroll-behavior="smooth">
      <body>
        <div className="app-root">
          <Providers><AppShell user={user}>{children}</AppShell></Providers>
        </div>
      </body>
    </html>
  );
}
