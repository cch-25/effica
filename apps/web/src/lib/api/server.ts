import { cookies } from "next/headers";

function backendApiBase(): string {
  const configured = process.env.API_BACKEND_URL ?? "http://127.0.0.1:8000";
  const url = new URL(configured);
  const path = url.pathname.replace(/\/$/, "");
  url.pathname = path.endsWith("/api/v1") ? path : `${path}/api/v1`;
  return url.toString().replace(/\/$/, "");
}

export async function serverApiRequest<T>(path: string): Promise<T> {
  const cookieHeader = (await cookies()).toString();
  const response = await fetch(`${backendApiBase()}${path}`, {
    headers: cookieHeader ? { cookie: cookieHeader } : undefined,
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`API ${path} returned ${response.status}`);
  return response.json() as Promise<T>;
}
