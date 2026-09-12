import type { Article, Issue } from "@/lib/api/types";
import { publisherIdentity } from "@/lib/api/publisher";
import { compareIssueImportance, featuredIssueLimit, isFeaturedIssue } from "@/features/issues/issue-selection";

export type HomeIssueGroup = { id: string; title: string; issues: Issue[] };

// These are display groups only. A related hearing remains its own comparison
// cohort: never combine memberships or scores just because two titles overlap.
const genericWords = new Set([
  "정부", "국회", "정치", "사회", "경제", "한국", "대한민국", "대통령", "여당", "야당", "여야",
  "장관", "후보", "후보자", "의원", "대표", "국회의원", "국무위원", "법무부", "성평등가족부", "국방부",
  "청문회", "인사청문회", "논란", "의혹", "검증", "공방", "관련", "각종", "대한", "둘러싼",
  "정책", "문제", "논의", "쟁점", "입장", "추진", "발표", "요구", "검토", "가능성", "여부",
]);

function titleWords(title: string): Set<string> {
  return new Set((title.normalize("NFKC").toLowerCase().match(/[가-힣a-z0-9]+/g) ?? [])
    .map((word) => word.length > 3 ? word.replace(/(?:에서|으로|과의|와의|에|의|은|는|을|를)$/u, "") : word)
    .filter((word) => word.length >= 2 && !genericWords.has(word)));
}

function isAppointment(issue: Issue): boolean {
  return /인사청문회|장관.{0,12}후보|후보.{0,12}장관/.test(issue.title);
}

function timestamp(value: string | null | undefined): number {
  const date = value ? new Date(value).getTime() : 0;
  return Number.isFinite(date) ? date : 0;
}

export function areRelatedHomeIssues(left: Issue, right: Issue): boolean {
  if (left.topic !== right.topic) return false;
  const leftTime = timestamp(left.dataAsOf ?? left.updatedAt);
  const rightTime = timestamp(right.dataAsOf ?? right.updatedAt);
  if (!leftTime || !rightTime || Math.abs(leftTime - rightTime) > 7 * 86_400_000) return false;
  if (left.articleIds.some((id) => right.articleIds.includes(id))) return true;
  const a = titleWords(left.title);
  const b = titleWords(right.title);
  const shared = [...a].filter((word) => b.has(word));
  // A name alone cannot join unrelated stories. Appointment coverage must also
  // share that event context. Generic titles require multiple specific words.
  return (isAppointment(left) && isAppointment(right) && shared.length >= 1)
    || (shared.length >= 2 && shared.length / Math.max(a.size, b.size) >= 0.4);
}

export function buildHomeEdition(issues: Issue[], limit = featuredIssueLimit): HomeIssueGroup[] {
  const candidates = [...new Map(issues.filter(isFeaturedIssue).map((issue) => [issue.id, issue])).values()]
    .sort(compareIssueImportance);
  const groups: HomeIssueGroup[] = [];
  for (const issue of candidates) {
    const matches = groups.filter((group) => group.issues.some((member) => areRelatedHomeIssues(member, issue)));
    if (!matches.length) {
      groups.push({ id: issue.id, title: issue.title, issues: [issue] });
      continue;
    }
    const target = matches[0];
    target.issues.push(issue);
    for (const group of matches.slice(1)) {
      target.issues.push(...group.issues);
      groups.splice(groups.indexOf(group), 1);
    }
  }
  for (const group of groups) {
    group.issues.sort(compareIssueImportance);
    if (group.issues.length > 1 && group.issues.every(isAppointment)) group.title = "장관 후보자 인사청문회";
  }
  // Group first, then apply the homepage limit so related angles cannot use up
  // all five slots and crowd an unrelated event out of the edition.
  return groups.sort((a, b) => compareIssueImportance(a.issues[0], b.issues[0])).slice(0, limit);
}

export function initialGroupIssue(group: HomeIssueGroup): Issue {
  return group.issues.find((issue) => issue.analysisStatus === "READY") ?? group.issues[0];
}

export function articlesForHomeIssue(issue: Issue, articles: Article[]): Article[] {
  const members = new Set(issue.articleIds);
  return [...new Map(articles.filter((article) => members.has(article.id)).map((article) => [article.id, article])).values()]
    .sort((a, b) => timestamp(b.publishedAt) - timestamp(a.publishedAt) || a.id.localeCompare(b.id));
}

export function publisherPreview(articles: Article[], limit = 3): Article[] {
  const seen = new Set<string>();
  return articles.filter((article) => {
    const publisher = publisherIdentity(article);
    if (seen.has(publisher)) return false;
    seen.add(publisher);
    return true;
  }).slice(0, limit);
}

export function homePublishedAt(value: string): string {
  if (!timestamp(value)) return "발행 시각 미확인";
  return new Intl.DateTimeFormat("ko-KR", {
    year: "numeric", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit",
    hour12: false, timeZone: "Asia/Seoul",
  }).format(new Date(value)) + " 발행";
}
