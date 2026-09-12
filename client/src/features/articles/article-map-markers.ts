import { publisherIdentity } from "@/lib/api/publisher";
import type { Article } from "@/lib/api/types";

// Categorical publisher colors, unrelated to political lean or article scores.
const publisherColors = ["#286A9B", "#A06419", "#77549B", "#247D71", "#AC4D67", "#6C742E", "#9B573C", "#535B98"];

export function articleMapMarkers(articles: Article[]) {
  const publishers = [...new Set(articles.map(publisherIdentity))].sort();
  return new Map(articles.map((article, index) => [article.id, {
    marker: String(index + 1),
    color: publisherColors[publishers.indexOf(publisherIdentity(article)) % publisherColors.length],
  }]));
}
