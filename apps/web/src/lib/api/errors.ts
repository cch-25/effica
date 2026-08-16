export const ERROR_MESSAGES: Record<string, string> = {
  AUTH_PROVIDER_DISABLED: "현재 사용할 수 없는 로그인 방식입니다.",
  CONSENT_REQUIRED: "정치 민감정보 별도 동의가 필요합니다.",
  QUESTIONNAIRE_VERSION_STALE: "설문이 갱신되었습니다. 최신 문항을 확인해 주세요.",
  VERSION_CONFLICT: "다른 변경이 먼저 반영되었습니다. 최신 데이터를 다시 불러와 주세요.",
  RATE_LIMITED: "요청이 많습니다. 안내된 시간 뒤 다시 시도해 주세요.",
  UNAUTHORIZED: "로그인이 필요합니다.",
};

export function mapErrorCode(code: string): string {
  return ERROR_MESSAGES[code] ?? "요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.";
}
