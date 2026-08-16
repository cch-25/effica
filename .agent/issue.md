# PR #1 병합 후속 이슈

대상: `cch-25/effica#1` (`MAS_A` 프런트엔드와 현재 `main` 백엔드 통합)

## P0 — 실제 API 모드에서 요청이 백엔드로 전달되지 않음

- `apps/web/src/lib/api/client.ts`는 모든 요청을 현재 Next.js origin의 `/api/v1`로 보낸다.
- 루트 `.env.example`의 `NEXT_PUBLIC_API_BASE_URL`은 클라이언트에서 사용되지 않으며, Next.js rewrite/proxy도 없다.
- 따라서 `NEXT_PUBLIC_API_MODE=real`로 실행하면 별도 포트의 FastAPI(`localhost:8000`)가 아니라 Next.js(`localhost:3000`)에 요청해 404가 발생한다.
- 후속 수정: API base URL 정책을 하나로 정하고, 권장안으로 Next.js rewrite를 추가해 브라우저에서는 same-origin 요청을 유지한다. 배포 설정과 쿠키 전달도 함께 검증한다.

## P0 — 프런트 타입과 FastAPI 응답 스키마가 다름

- 프런트 `Article`은 `id`, `issueId`, `publishedAt`, 최상위 `x/y/z/confidence`, `dek` 등을 기대한다.
- FastAPI `/feed`는 `article_id`, `issue_id`, 중첩 `coordinate`, `reason_code` 등을 반환하며 reason enum 값도 다르다.
- 프런트 `Issue` 역시 camelCase 필드와 자체 status를 기대하지만 API는 snake_case 계약을 사용한다.
- MSW fixture가 프런트 타입에 맞춰져 있어 현재 단위 테스트와 production build에서는 이 불일치가 드러나지 않는다.
- 후속 수정: `contracts/openapi.json`에서 타입을 생성하고 API DTO → 화면 모델 mapper를 명시적으로 구현한다. `/feed`, `/issues`, `/articles/{id}`, `/visualization/points`의 실제 응답 계약 테스트를 추가한다.

## P1 — 실제 백엔드 통합 검증이 없음

- 현재 Playwright 여정과 단위 테스트는 기본 mock 모드만 검증한다.
- 병합 우선 원칙에 따라 실브라우저 E2E는 이번 병합 전에 실행하지 않았다.
- 후속 수정: memory backend + web real mode를 함께 기동하는 최소 smoke test를 추가하고 홈 피드, 이슈 상세, 투표의 성공/401/동의 필요 흐름을 검증한다.

## 병합 시 확인된 통과 항목

- 백엔드: `pytest` 69개, Ruff, mypy
- 프런트: ESLint, TypeScript, Vitest 11개, Next.js production build
- Git merge: 최신 `main`과 텍스트 충돌 없음
