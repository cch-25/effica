# MAS_A - Next.js 사용자·관리자 웹 실행 지침

> 함께 읽을 문서: MASTERPLAN_AND_SPECIFICATION.md  
> 역할: 프론트엔드 단독 소유자  
> 브랜치: dev/mas-a  
> 핵심 원칙: apps/web 밖의 구현 파일을 수정하지 않는다.

## 1. 임무

MASTERPLAN_AND_SPECIFICATION.md에 정의된 사용자 웹과 관리자 웹을 Next.js로 구현한다. 초기에는 명세 기반 mock으로 독립 개발하고, MAS_B가 게시한 OpenAPI 기준선이 준비되면 생성 API 타입과 실제 FastAPI에 연결한다.

완료 상태는 단순 화면 모음이 아니다. 모바일 우선 사용자 여정, 관리자 운영 여정, 접근성, 오류·부분 실패 상태와 실제 API 연동 E2E가 함께 동작해야 한다.

## 2. 배타적 소유권

### 수정 가능

- apps/web/**
- apps/web/tests/**
- docs/decisions/mas-a/**

### 읽기만 가능

- MASTERPLAN_AND_SPECIFICATION.md
- MAS_B.md
- contracts/**
- apps/api/**
- apps/worker/**
- db/**
- scripts/**
- 루트 설정과 환경 예제

### 금지

- FastAPI route나 Pydantic schema를 프론트 편의 때문에 직접 수정
- contracts/openapi.json을 수동 편집
- DB migration 또는 seed 수정
- 루트 package, Python 설정, 공통 스크립트 수정
- 실제 시크릿 저장
- apps/web/.env.local 또는 apps/web/.env 생성
- MAS_B 소유 파일의 formatting-only 변경

필요한 API가 없거나 계약이 모순되면 docs/decisions/mas-a/CR-YYYYMMDD-NNN.md를 새 파일로 만든다. 상대 파일은 수정하지 않는다.

## 3. 기술 기준

- Next.js App Router
- TypeScript strict
- 서버 상태: TanStack Query 또는 동등한 단일 라이브러리
- 로컬 UI 상태: React 기본 상태를 우선하고 전역 상태는 인증·공통 설정에만 사용
- 폼: schema 기반 검증
- API 타입: contracts/openapi.json에서 생성
- mock: MSW 또는 동등한 네트워크 계층 mock
- 3D: React Three Fiber 계열 사용 가능, 2D·표 fallback 필수
- 테스트: unit, component, accessibility, Playwright E2E

라이브러리 선택은 apps/web 내부에서 끝나야 한다. 루트 설정 변경이 필요하면 B에게 변경 요청한다.

## 4. 권장 내부 구조

    apps/web/
      src/
        app/
          (public)/
          (app)/
          admin/
        features/
          auth/
          onboarding/
          feed/
          issues/
          articles/
          reading/
          voting/
          progress/
          efficacy/
          visualization/
          share-cards/
          admin-sources/
          admin-models/
          admin-weights/
          admin-jobs/
          admin-audit/
        components/
          ui/
          layout/
          charts/
        lib/
          api/
          auth/
          accessibility/
          analytics/
        mocks/
          handlers/
          fixtures/
      tests/
        e2e/
        accessibility/

기능 전용 컴포넌트는 features 아래에 두고 범용 UI만 components/ui로 승격한다. API 응답 타입을 화면 모델로 직접 오염시키지 말고 features별 mapper를 둔다.

## 5. 구현 순서

## A0. 독립 부트스트랩

1. apps/web 안에 독립 실행 가능한 Next.js 프로젝트를 구성한다.
2. TypeScript strict, lint, unit test, Playwright 명령을 apps/web 내부에 둔다.
3. MASTERPLAN_AND_SPECIFICATION.md의 API 타입을 기준으로 mock handler와 fixture를 만든다.
4. loading, empty, partial, error, unauthorized, consent-required fixture를 공통 제공한다.
5. 루트 파일이 아직 없더라도 apps/web 디렉터리에서 실행 가능해야 한다.

완료 기준:

- 앱이 mock 모드로 실행된다.
- unit, typecheck, lint가 apps/web 내부 명령으로 통과한다.
- 상대방 소유 파일 변경이 없다.

## A1. 애플리케이션 셸·디자인 시스템

구현:

- 모바일 하단 탐색과 데스크톱 탐색
- 사용자 영역과 /admin 영역의 명확한 분리
- typography, spacing, color, focus, elevation token
- 정치 방향을 좋음·나쁨으로 암시하지 않는 중립 색 체계
- Toast, Dialog, Drawer, Tabs, Slider, Skeleton, Empty, ErrorBoundary
- 축 설명과 confidence 표현을 위한 공통 컴포넌트

접근성:

- WCAG 2.2 AA 목표
- 키보드 focus가 항상 보일 것
- 슬라이더는 방향키와 숫자 입력 지원
- 색상만으로 정치축·상태를 구분하지 않을 것
- reduced motion 지원

## A2. 인증·온보딩

화면:

- /login
- /onboarding/consent
- /onboarding/questionnaire
- /onboarding/demographics
- /settings/privacy

요구사항:

- OAuth provider 활성 상태에 따라 버튼 표시
- 정치 민감정보 별도 동의와 철회 효과 설명
- 필수 정치 설문과 선택 인구통계 구분
- 자기보고 좌표 결과를 확정적 정체성으로 표현하지 않음
- 계정 삭제·데이터 내보내기의 pending·complete 상태

## A3. 홈·이슈·기사 비교

화면:

- /
- /issues
- /issues/[issueId]
- /articles/[articleId]

요구사항:

- 홈에 다양성 보정 피드와 이슈별 균형 묶음 혼합
- 추천 reason code를 사람에게 이해되는 짧은 문구로 표시
- 같은 이슈의 기사들을 좌표·출처·핵심 주장 기준으로 비교
- 균형 조건 미충족 시 "준비 중"을 명확히 표시
- 모델별 제한 공개 요약, 투표 분포, confidence, score version 제공
- 원문 링크는 내부 기사처럼 위장하지 않음

## A4. 읽기·투표·진행도

구현:

- POST /articles/{id}/read-sessions 호출 뒤 redirect_url로 이동
- 복귀 시 POST /read-sessions/{id}/return 호출
- browser visibility와 client elapsed는 보조 UX에만 사용
- eligible, rejected, expired 상태별 정확한 메시지
- 3축과 과장성 투표 슬라이더
- 활동 크레딧 원칙, 레벨, 티어, credit history
- 효능감 후속 설문과 개인 추이

표현 금지:

- 체류시간을 실제 완독으로 표현
- 크레딧 획득을 정치적 정답으로 표현
- 투표가 즉시 공식 점수를 교체한다고 표현

## A5. 3D·2D 시각화

구현:

- 기사·언론사·사용자 point 유형 구분
- 3축 라벨, 범례, confidence
- drag, zoom, reset, 선택 상세
- 날짜·score version 시계열
- 2축씩 보는 2D projection
- 동일 데이터의 정렬 가능한 표

3D 기능과 관계없이 2D·표만으로 모든 좌표와 상세에 접근할 수 있어야 한다. WebGL 실패를 의도적으로 발생시키는 테스트를 추가한다.

## A6. 공유 카드

화면:

- /share/new
- /share/[shareCardId]

요구사항:

- 생성 전에 정치 좌표가 공개된다는 별도 확인
- template, 표시 이름, preview
- queued, rendering, ready, failed, revoked 상태
- 다운로드·Web Share API와 fallback
- 즉시 폐기
- 공개 페이지에서 민감한 원응답·이메일·실명을 노출하지 않음

## A7. 관리자 패널

경로:

- /admin/sources
- /admin/crawls
- /admin/issues
- /admin/models
- /admin/weights
- /admin/autopilot
- /admin/jobs
- /admin/audit
- /admin/metrics/efficacy

요구사항:

- role 기반 route guard와 action guard
- source 정책·수집 오류
- 이슈 merge·split
- 모델 상태·비용·지연·불일치
- weight draft 편집, 영향 시뮬레이션, publish, rollback
- 추천 approve·reject와 LIMITED_AUTO guardrail
- job retry·cancel
- 감사 로그 before·after와 reason
- 모든 관리자 변경에 confirmation, reason, Idempotency-Key
- version 충돌 409 발생 시 새 데이터를 불러와 재검토

## A8. 실제 API 연결

1. MAS_B가 게시한 contracts/openapi.json을 읽는다.
2. apps/web 내부 생성 설정으로 API 타입·클라이언트를 생성한다.
3. 생성 결과는 수동 편집하지 않는다.
4. mock과 실제 API가 동일한 contract test fixture를 사용하게 한다.
5. 개발 서버에서는 /api 경계를 통해 쿠키와 CSRF를 검증한다.
6. partial backend failure가 전체 화면 white screen으로 이어지지 않게 한다.

계약이 문서와 다르면 구현을 추측하지 말고 변경 요청을 만든다.

## 6. API 소비 규칙

- 환경변수의 실제 값은 루트 .env만 사용한다. apps/web 아래에 별도 env 파일을 만들지 않는다.
- 브라우저 코드에서는 NEXT_PUBLIC_ 접두사의 공개 변수만 읽는다.
- DATABASE_URL, SESSION_SECRET, OAuth client secret, LLM API key를 import하거나 브라우저 번들에 포함하지 않는다.
- 화면 컴포넌트에서 fetch를 직접 호출하지 않는다.
- features별 query/mutation hook에서 생성 클라이언트를 감싼다.
- stable error code를 사용자 메시지로 mapping한다.
- cursor는 URL에 노출할 필요가 없는 opaque 값으로 취급한다.
- 401은 로그인 복귀 경로를 보존하고, 403 CONSENT_REQUIRED는 동의 화면으로 보낸다.
- 409는 사용자 입력을 잃지 않고 재시도 안내를 제공한다.
- 429 Retry-After를 존중한다.
- 관리자 POST는 UUID/ULID 기반 Idempotency-Key를 한 사용자 동작 동안 재사용한다.

## 7. 테스트 의무

### Unit·component

- 좌표·confidence formatter
- error code mapping
- API response to view model mapper
- 투표 validation
- 권한별 관리자 action
- 공유 카드 상태 전이

### Accessibility

- 로그인, 온보딩, 홈, 이슈, 투표, 2D 표, 관리자 가중치의 axe 검사
- 키보드 전용 핵심 흐름
- reduced motion과 WebGL fallback

### E2E

1. mock 로그인 -> 별도 동의 -> 설문 -> 홈
2. 이슈 묶음 -> 기사 분석 -> 원문 이탈·복귀 -> credit
3. 투표 제출·수정·삭제
4. 효능감 설문 -> 진행도
5. 공유 카드 생성 -> ready -> 공개 이미지 -> revoke
6. analyst와 admin 권한 차이
7. weight simulation -> version conflict -> reload -> publish
8. LLM partial failure와 준비 중 이슈

## 8. 병렬 협업 규칙

### 계약 변경 요청 템플릿

docs/decisions/mas-a/CR-YYYYMMDD-NNN.md:

    # Contract change request
    - Feature:
    - Current contract:
    - Blocking user flow:
    - Requested change:
    - Backward-compatible alternative:
    - UI deadline impact:

파일을 만든 뒤 B의 response 파일을 기다린다. 승인 전에 mock에서 새 필드를 필수로 만들지 않는다.

### 동기화

- integration의 OpenAPI 기준선만 신뢰한다.
- B의 backend commit을 가져올 때 apps/web 밖 충돌을 해결하지 않는다.
- A의 브랜치에 루트·backend 변경을 복사하지 않는다.
- merge 직전 소유 경로 검사 결과를 B에게 제공한다.

## 9. 완료 보고서

완료 시 다음을 전달한다.

- 구현한 route와 기능 목록
- 미구현 또는 feature flag 기능
- 실제 API 연결 상태
- 생성 클라이언트의 기준 contract checksum
- unit, accessibility, E2E 결과
- 알려진 모바일·브라우저 제약
- A가 생성한 변경 요청과 해결 상태
- apps/web 밖을 수정하지 않았다는 경로 검사 결과
