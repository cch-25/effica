import { ArticlesBrowser } from "@/features/articles/articles-browser";
import "./articles.css";

export const metadata = { title: "기사 모음" };

export default async function ArticlesPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  const value = (key: string) => typeof params[key] === "string" ? params[key] as string : "";
  const filters = { q: value("q"), source: value("source") };
  return <ArticlesBrowser key={JSON.stringify(filters)} filters={filters} />;
}
