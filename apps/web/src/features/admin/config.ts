import type { Role } from "@/lib/api/types";

export type AdminAction = {
  label: string;
  level: "operate" | "review" | "publish";
  method: "POST" | "PATCH" | "PUT";
  path: (itemId: string) => string;
  destructive?: boolean;
  needsValues?: boolean;
  ifMatch?: boolean;
  ifMatchPath?: string;
  defaultValues?: Record<string, unknown>;
  body: (reason: string, values: Record<string, unknown>) => Record<string, unknown>;
};

export type AdminConfig = { eyebrow: string; title: string; description: string; listPath: string; actions: AdminAction[]; minimumRole: Role };
const reasonBody = (reason: string) => ({ reason });

export const adminConfigs: Record<string, AdminConfig> = {
  sources: { eyebrow: "Collection policy", title: "출처와 수집 정책", description: "서버에 저장된 수집 정책과 실행 상태입니다.", listPath: "/admin/sources", minimumRole: "analyst", actions: [
    { label: "수집 실행", level: "operate", method: "POST", path: (id) => `/admin/sources/${id}/crawl`, body: reasonBody },
    { label: "정책 수정", level: "publish", method: "PATCH", path: (id) => `/admin/sources/${id}`, needsValues: true, ifMatch: true, body: (reason, values) => ({ reason, values }) },
  ] },
  crawls: { eyebrow: "Ingestion runs", title: "수집 실행과 오류", description: "실제 수집 실행과 오류를 읽기 전용으로 확인합니다.", listPath: "/admin/crawls", minimumRole: "analyst", actions: [] },
  issues: { eyebrow: "Issue desk", title: "이슈 군집 검수", description: "기사 관계 변경은 작업 큐와 감사 로그에 남습니다.", listPath: "/issues", minimumRole: "analyst", actions: [
    { label: "Merge", level: "operate", method: "POST", path: (id) => `/admin/issues/${id}/merge`, needsValues: true, body: (reason, values) => ({ reason, target_issue_id: values.target_issue_id }) },
    { label: "Split", level: "operate", method: "POST", path: (id) => `/admin/issues/${id}/split`, needsValues: true, body: (reason, values) => ({ reason, article_ids: values.article_ids }) },
  ] },
  models: { eyebrow: "Model observatory", title: "모델 상태와 불일치", description: "서버에 등록된 모델 alias 상태를 확인하고 수정합니다.", listPath: "/admin/models", minimumRole: "analyst", actions: [
    { label: "모델 수정", level: "publish", method: "PATCH", path: (id) => `/admin/models/${id}`, needsValues: true, ifMatch: true, body: (reason, values) => ({ reason, values }) },
  ] },
  weights: { eyebrow: "Weight control", title: "가중치 revision", description: "simulation 결과를 확인한 뒤 publish 또는 rollback합니다.", listPath: "/admin/weights", minimumRole: "analyst", actions: [
    { label: "7·30일 simulation", level: "operate", method: "POST", path: (id) => `/admin/weights/${id}/simulate`, defaultValues: { windows: [7, 30] }, body: (reason, values) => ({ reason, windows: values.windows ?? [7, 30] }) },
    { label: "Publish", level: "publish", method: "POST", path: (id) => `/admin/weights/${id}/publish`, ifMatch: true, ifMatchPath: "/admin/autopilot/settings", body: reasonBody },
    { label: "Rollback", level: "publish", method: "POST", path: (id) => `/admin/weights/${id}/rollback`, destructive: true, needsValues: true, ifMatch: true, ifMatchPath: "/admin/autopilot/settings", body: (reason, values) => ({ reason, target_revision_id: values.target_revision_id }) },
  ] },
  autopilot: { eyebrow: "Auto Pilot", title: "추천 inbox와 guardrail", description: "서버가 생성한 추천을 승인하거나 거절합니다.", listPath: "/admin/autopilot/recommendations", minimumRole: "analyst", actions: [
    { label: "Approve", level: "review", method: "POST", path: (id) => `/admin/autopilot/recommendations/${id}/approve`, body: reasonBody },
    { label: "Reject", level: "review", method: "POST", path: (id) => `/admin/autopilot/recommendations/${id}/reject`, destructive: true, body: reasonBody },
  ] },
  jobs: { eyebrow: "MariaDB queue", title: "작업 큐", description: "lease와 attempt 상태를 확인하고 운영 재시도·취소를 실행합니다.", listPath: "/admin/jobs", minimumRole: "analyst", actions: [
    { label: "Retry", level: "review", method: "POST", path: (id) => `/admin/jobs/${id}/retry`, body: reasonBody },
    { label: "Cancel", level: "review", method: "POST", path: (id) => `/admin/jobs/${id}/cancel`, destructive: true, body: reasonBody },
  ] },
  audit: { eyebrow: "Audit trail", title: "변경 감사 로그", description: "actor·action·before·after·reason·request ID를 확인합니다.", listPath: "/admin/audit", minimumRole: "reviewer", actions: [] },
  "metrics/efficacy": { eyebrow: "Protected aggregate", title: "효능감 cohort 지표", description: "서버에서 suppression된 집계만 표시합니다.", listPath: "/admin/metrics/efficacy", minimumRole: "analyst", actions: [] },
};
