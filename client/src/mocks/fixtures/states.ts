import type { ResourceState } from "@/lib/api/types";

export const commonStates: Record<ResourceState, { title: string; description: string }> = {
  ready: { title: "준비됨", description: "최신 데이터를 표시합니다." },
  loading: { title: "불러오는 중", description: "정보를 안전하게 불러오고 있습니다." },
  empty: { title: "표시할 내용이 없습니다", description: "조건을 바꾸거나 잠시 후 다시 확인해 주세요." },
  partial: { title: "일부 분석만 도착했습니다", description: "확인 가능한 정보부터 표시합니다." },
  error: { title: "잠시 연결이 불안정합니다", description: "입력 내용은 보존되었습니다. 다시 시도해 주세요." },
  fatal: { title: "화면을 표시할 수 없습니다", description: "요청 ID와 함께 관리자에게 문의해 주세요." },
  unauthorized: { title: "로그인이 필요합니다", description: "로그인 후 원래 화면으로 돌아옵니다." },
  "consent-required": { title: "별도 동의가 필요합니다", description: "정치 민감정보 처리 내용을 확인해 주세요." },
  stale: { title: "새 분석을 준비 중입니다", description: "현재 값은 이전 본문 버전을 기준으로 합니다." },
  processing: { title: "준비 중입니다", description: "완료되면 이 화면에서 상태가 갱신됩니다." },
  conflict: { title: "다른 변경이 먼저 반영됐습니다", description: "최신 데이터를 불러온 뒤 다시 검토해 주세요." },
  "rate-limited": { title: "요청이 잠시 많습니다", description: "Retry-After 시간 뒤 자동으로 다시 시도합니다." },
};
