import "./home.css";
import { articles, issues } from "@/mocks/fixtures/content";
import { HomeNewspaper } from "@/features/home/home-newspaper";

export default function HomePage() {
  return <div className="home-page" data-layout="newspaper">
    <HomeNewspaper fallbackIssues={issues} fallbackArticles={articles} />
  </div>;
}
