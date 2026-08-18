import { loadEnvConfig } from "@next/env";
import type { NextConfig } from "next";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
loadEnvConfig(repositoryRoot);

const apiMode = process.env.NEXT_PUBLIC_API_MODE;
if (apiMode !== undefined && apiMode !== "mock" && apiMode !== "real") {
  throw new Error("NEXT_PUBLIC_API_MODE must be either 'mock' or 'real'.");
}
if ((process.env.VERCEL_ENV === "production" || process.env.NODE_ENV === "production") && apiMode !== "real") {
  throw new Error("NEXT_PUBLIC_API_MODE=real is required for production builds.");
}

function backendApiBase(): string {
  const configured = process.env.API_BACKEND_URL;
  if (!configured && process.env.VERCEL_ENV === "production") {
    throw new Error("API_BACKEND_URL must be configured for Vercel production deployments.");
  }
  const url = new URL(configured ?? "http://127.0.0.1:8000");
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash) {
    throw new Error("API_BACKEND_URL must be an HTTP(S) origin or API base URL without credentials, query, or fragment.");
  }
  const pathname = url.pathname.replace(/\/$/, "");
  url.pathname = pathname.endsWith("/api/v1") ? pathname : `${pathname}/api/v1`;
  return url.toString().replace(/\/$/, "");
}

const nextConfig: NextConfig = {
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  reactStrictMode: true,
  poweredByHeader: false,
  allowedDevOrigins: ["127.0.0.1"],
  experimental: {
    optimizePackageImports: ["lucide-react"],
  },
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${backendApiBase()}/:path*` }];
  },
};

export default nextConfig;
