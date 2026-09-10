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

type AdminConfig = { eyebrow: string; title: string; description: string; listPath: string; actions: AdminAction[]; minimumRole: Role };
const reasonBody = (reason: string) => ({ reason });

export const adminConfigs: Record<string, AdminConfig> = {
  runtime: { eyebrow: "Runtime control", title: "LLM 사용", description: "수집과 백그라운드 분석의 전체 실행 상태를 제어합니다.", listPath: "/admin/runtime/llm-usage", minimumRole: "analyst", actions: [] },
  sources: { eyebrow: "출처 등록부", title: "출처와 수집 정책", description: "서버에 저장된 수집 정책과 실행 상태입니다.", listPath: "/admin/sources", minimumRole: "analyst", actions: [
    { label: "수집 실행", level: "operate", method: "POST", path: (id) => `/admin/sources/${id}/crawl`, body: reasonBody },
    { label: "정책 수정", level: "publish", method: "PATCH", path: (id) => `/admin/sources/${id}`, needsValues: true, ifMatch: true, body: (reason, values) => ({ reason, values }) },
  ] },
  crawls: { eyebrow: "수집 기록", title: "수집 실행과 오류", description: "실제 수집 실행과 오류를 읽기 전용으로 확인합니다.", listPath: "/admin/crawls", minimumRole: "analyst", actions: [] },
  issues: { eyebrow: "이슈 검수", title: "이슈 군집 검수", description: "기사 관계 변경은 작업 큐와 감사 로그에 남습니다.", listPath: "/issues", minimumRole: "analyst", actions: [
    { label: "Merge", level: "operate", method: "POST", path: (id) => `/admin/issues/${id}/merge`, needsValues: true, body: (reason, values) => ({ reason, target_issue_id: values.target_issue_id }) },
    { label: "Split", level: "operate", method: "POST", path: (id) => `/admin/issues/${id}/split`, needsValues: true, body: (reason, values) => ({ reason, article_ids: values.article_ids }) },
  ] },
  models: { eyebrow: "분석 모델", title: "모델 상태와 불일치", description: "서버에 등록된 모델 alias 상태를 확인하고 수정합니다.", listPath: "/admin/models", minimumRole: "analyst", actions: [
    { label: "모델 수정", level: "publish", method: "PATCH", path: (id) => `/admin/models/${id}`, needsValues: true, ifMatch: true, body: (reason, values) => ({ reason, values }) },
  ] },
  weights: { eyebrow: "추천 설정", title: "추천 가중치 이력", description: "모의 실행 결과를 확인한 뒤 적용하거나 이전 설정으로 복원합니다.", listPath: "/admin/weights", minimumRole: "analyst", actions: [
    { label: "7일과 30일 시뮬레이션", level: "operate", method: "POST", path: (id) => `/admin/weights/${id}/simulate`, defaultValues: { windows: [7, 30] }, body: (reason, values) => ({ reason, windows: values.windows ?? [7, 30] }) },
    { label: "Publish", level: "publish", method: "POST", path: (id) => `/admin/weights/${id}/publish`, ifMatch: true, ifMatchPath: "/admin/autopilot/settings", body: reasonBody },
    { label: "Rollback", level: "publish", method: "POST", path: (id) => `/admin/weights/${id}/rollback`, destructive: true, needsValues: true, ifMatch: true, ifMatchPath: "/admin/autopilot/settings", body: (reason, values) => ({ reason, target_revision_id: values.target_revision_id }) },
  ] },
  autopilot: { eyebrow: "추천 승인", title: "추천 검토와 승인", description: "서버가 생성한 추천을 승인하거나 거절합니다.", listPath: "/admin/autopilot/recommendations", minimumRole: "analyst", actions: [
    { label: "Approve", level: "review", method: "POST", path: (id) => `/admin/autopilot/recommendations/${id}/approve`, body: reasonBody },
    { label: "Reject", level: "review", method: "POST", path: (id) => `/admin/autopilot/recommendations/${id}/reject`, destructive: true, body: reasonBody },
  ] },
  jobs: { eyebrow: "작업 현황", title: "작업 큐", description: "lease와 attempt 상태를 확인하고 운영 재시도 또는 취소를 실행합니다.", listPath: "/admin/jobs", minimumRole: "analyst", actions: [
    { label: "Retry", level: "review", method: "POST", path: (id) => `/admin/jobs/${id}/retry`, body: reasonBody },
    { label: "Cancel", level: "review", method: "POST", path: (id) => `/admin/jobs/${id}/cancel`, destructive: true, body: reasonBody },
  ] },
  audit: { eyebrow: "변경 기록", title: "변경 감사 로그", description: "행위자, 행동, 변경 전후, 사유, 요청 ID를 확인합니다.", listPath: "/admin/audit", minimumRole: "reviewer", actions: [] },
  "metrics/efficacy": { eyebrow: "집계 통계", title: "집단별 효능감 지표", description: "개인정보 보호 기준을 적용한 집계만 표시합니다.", listPath: "/admin/metrics/efficacy", minimumRole: "analyst", actions: [] },
};
