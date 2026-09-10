import type { Issue } from "@/lib/api/types";

export const issueTopics = ["정치", "사회", "경제"] as const;
export const featuredIssueLimit = 5;

export function isSupportedIssue(issue: Issue): boolean {
  return issueTopics.some((topic) => topic === issue.topic);
}

export function isFeaturedIssue(issue: Issue): boolean {
  return isSupportedIssue(issue)
    && issue.kind === "EVENT"
    && issue.freshnessStatus === "CURRENT"
    && issue.articleIds.length >= 3
    && issue.sourceCount >= 3
    && issue.summary.trim().length > 0
    && !issueTopics.some((topic) => topic === issue.title.trim());
}

export function compareIssueImportance(left: Issue, right: Issue): number {
  return (left.editorialPriority ?? Number.MAX_SAFE_INTEGER) - (right.editorialPriority ?? Number.MAX_SAFE_INTEGER)
    || right.sourceCount - left.sourceCount
    || right.articleIds.length - left.articleIds.length
    || new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime()
    || left.id.localeCompare(right.id);
}
