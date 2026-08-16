# MAS_B - FastAPI·MariaDB·Worker·통합 실행 지침

> 함께 읽을 문서: MASTERPLAN_AND_SPECIFICATION.md  
> 역할: 백엔드·데이터·계약 단독 소유자 및 최종 통합자  
> 브랜치: dev/mas-b  
> 핵심 원칙: apps/web을 수정하지 않고 공통 계약과 통합을 책임진다.

## 1. 임무

MASTERPLAN_AND_SPECIFICATION.md의 API, DB, 수집, LLM, 점수, 비동기 처리와 운영 계약을 구현한다. OpenAPI와 DB schema의 단독 소유자이며, A가 실제 API에 연결할 수 있도록 안정된 contract 기준선을 조기에 게시한다.

최종적으로 B가 integration 브랜치의 병합, 전체 로컬 수직 슬라이스, migration, contract, integration, E2E 연동 검증을 담당한다.

## 2. 배타적 소유권

### 수정 가능

- apps/api/**
- apps/worker/**
- db/**
- contracts/**
- scripts/**
- tests/integration/**
- docs/decisions/mas-b/**
- 루트 설정
- .env.example
- .gitignore

### 읽기만 가능

- apps/web/**
- apps/web/tests/**
- docs/decisions/mas-a/**
- MASTERPLAN_AND_SPECIFICATION.md
- MAS_A.md

### 금지

- UI 오류를 고치기 위해 apps/web을 직접 수정
- A의 contract request 원문 편집
- 실제 OAuth·LLM·DB 시크릿을 Git, seed, fixture, 로그에 기록
- apps/web/.env.local, apps/api/.env, apps/worker/.env 등 서비스별 env 파일 생성
- 배포 자격정보를 받기 전에 EC2에 접속하거나 서비스를 변경
- migration history 재작성 또는 이미 공유된 migration 파일 수정

## 3. 기술 기준

- Python 3.12 이상 호환
- FastAPI, Pydantic v2
- SQLAlchemy 2 async
- MariaDB async driver
- Alembic
- pytest
- HTTP client는 timeout과 retry 정책을 명시
- API와 Worker가 도메인·repository·schema 코드를 공유
- Worker queue는 MariaDB만 사용
- 모든 ID는 애플리케이션 생성 ULID CHAR(26)
- 모든 시각은 UTC

버전은 루트 Python dependency 파일에서 고정한다. 실제 안정 버전은 구현 시 호환 테스트 후 기록한다.

## 4. 권장 구조

    apps/api/
      app/
        main.py
        api/
          v1/
        core/
          config.py
          security.py
          errors.py
          logging.py
        domains/
          auth/
          users/
          content/
          issues/
          analysis/
          scoring/
          feed/
          engagement/
          efficacy/
          sharing/
          admin/
        db/
          session.py
          models/
        jobs/
          producer.py
          types.py
      tests/
    apps/worker/
      worker/
        main.py
        queue.py
        handlers/
          crawl.py
          cluster.py
          analyze.py
          aggregate_votes.py
          calculate_score.py
          recommend_weights.py
          simulate_weights.py
          render_share_card.py
          export_user.py
          delete_user.py
      tests/
    db/
      alembic/
      seeds/
    contracts/
      openapi.json
      CHANGELOG.md
      checksum.txt
    scripts/
      dev/
      verify/
    tests/integration/

순환 import를 피하기 위해 domain은 다른 domain의 DB model을 직접 조작하지 않고 공개 service 또는 event/job 입력을 사용한다.

## 5. 구현 순서

## B0. 저장소·계약 기준선

가장 먼저 수행한다.

1. 루트에 Python·Node·공통 실행 기준을 만든다.
2. apps/api, apps/worker, db, contracts, scripts, tests/integration 경로를 만든다.
3. 실제 값은 루트 .env 하나에서만 읽도록 config loader를 만든다. .env.example에는 변수명과 형식만 기록하고 값은 넣지 않는다.
4. FastAPI 기본 앱, /health/live, /health/ready를 구현한다.
5. MASTERPLAN_AND_SPECIFICATION.md의 endpoint와 schema를 FastAPI stub으로 선언한다.
6. openapi.json을 생성해 contracts에 게시한다.
7. contracts/checksum.txt와 CHANGELOG.md를 만든다.
8. integration에 기준선을 먼저 병합해 A가 소비하게 한다.

완료 기준:

- 실제 FastAPI openapi.json과 committed contract가 byte-normalized checksum 기준으로 일치
- 모든 endpoint가 stub이라도 인증·입출력·오류 schema를 노출
- A 소유 경로를 수정하지 않음

## B1. MariaDB·migration

1. 공통 ULID, UTC, enum·check convention을 만든다.
2. MASTERPLAN_AND_SPECIFICATION.md 5장의 테이블을 migration으로 구현한다.
3. FK 생성 순서와 삭제 정책을 테스트한다.
4. 개발용 seed는 가짜 뉴스 소스, 기사, 이슈, 모델 alias, tier만 포함한다.
5. 정치 설문 원응답과 동의 데이터를 민감 영역으로 분리한다.
6. stored_blobs의 10 MiB 애플리케이션 제한과 SHA-256 중복 검사를 구현한다.

Migration 규칙:

- 공유된 migration 파일은 수정하지 않고 새 migration으로 정정
- upgrade는 무중단 가능성을 고려해 add -> backfill -> enforce 순서
- downgrade가 데이터 손실을 일으키면 명시적 경고와 테스트 fixture 제공

## B2. 인증·동의·사용자 데이터 권리

구현:

- Kakao, Naver, Google OAuth adapter
- 로컬 mock provider
- opaque session token과 DB에는 SHA-256 hash
- CSRF token
- role 검사
- 민감정보 별도 동의 version
- 가입 설문 제출과 self-reported profile
- 행동 profile 비활성 초기 상태
- 동의 철회, 계정 삭제, 데이터 export job

보안:

- callback state, nonce, redirect allowlist
- session rotation과 revoke
- OAuth access token 최소 보존 또는 즉시 폐기
- 로그 redaction

## B3. 수집·정규화·이슈

구현:

- source adapter interface: API, RSS, crawler
- source policy 강제
- robots·약관 상태가 미승인이면 crawler job 거부
- URL canonicalization과 hash
- 기사 versioning과 stale 분석 표시
- 원시 payload 보존 정책
- issue clustering 후보와 membership
- 관리자 merge·split idempotent job

테스트 fixture는 외부 사이트를 실시간 호출하지 않는다. HTML·RSS·API 응답 fixture로 parser를 검증한다.

## B4. MariaDB 작업 큐

상태:

- PENDING
- LEASED
- SUCCEEDED
- FAILED
- DEAD
- CANCELLED

필수 기능:

- job_type + dedupe_key unique
- priority와 available_at
- lease_owner와 lease_expires_at
- transaction claim
- exponential backoff + jitter
- max_attempts 후 DEAD
- structured last error
- graceful shutdown 시 lease 처리
- handler idempotency

MariaDB 버전이 SKIP LOCKED를 지원하면 사용하고, 그렇지 않으면 조건부 UPDATE claim을 사용한다. 동시 Worker 테스트로 한 job이 한 번만 side effect를 내는지 확인한다.

## B5. 단일 OpenAI GPT 분석

Provider interface:

    analyze_article(input, prompt_version) -> ModelAssessment

요구사항:

- OpenAI Responses API timeout, retry, rate limit, circuit state
- `OPENAI_API_KEY` 단일 자격정보와 `gpt-5.6-luna`/`xhigh` 기본값
- 관리자 model id와 reasoning effort 변경 및 작업별 동적 반영
- model_alias와 실제 model id 분리
- 구조 출력 schema 엄격 검증
- content-first 분석에서 source identity masking
- evidence 위치가 원문 version과 연결
- prompt, raw response, token, latency, error 저장
- 공개 rationale_summary에 개인·시크릿·긴 원문 유출 방지
- 단일 성공 모델 규칙과 기존 ensemble 응답 호환성

외부 호출이 없는 테스트에서는 단일 deterministic stub provider로 전체 수직 슬라이스를 실행한다.

## B6. 투표·점수·사용자 행동 좌표

구현:

- 사용자·기사당 revisioned vote
- active vote 변경과 aggregate snapshot
- quality status와 비정상 패턴 hook
- 작은 demographic segment 숨김
- article score component 계산
- source prior shrinkage
- score version snapshot과 재현
- 사용자의 consumption·vote 기반 behavioral profile 갱신

점수 계산기는 순수 함수로 분리하고 동일 입력의 byte-stable 결과를 테스트한다. fact-check는 이념축 방향을 직접 변경하지 않는다.

## B7. 피드·읽기·크레딧·효능감

피드:

- 후보 생성
- relevance, recency, diversity, distance, quality
- 동일 소스 연속 제한
- 인접 관점 우선
- 비개인화 fallback
- reason code

읽기:

- signed redirect token
- 서버 outbound·return time
- 세션 상태 전이
- 겹침·반복·비정상 elapsed rejection

크레딧:

- immutable ledger
- 정책 version
- event idempotency
- reversal
- tier snapshot

효능감:

- questionnaire version
- normalized scoring
- baseline delta
- due survey 정책
- 작은 cohort aggregate 숨김

## B8. 가중치·Auto Pilot

구현:

- immutable weight profile revision
- draft, simulation, active, archived 상태
- 시계열 evidence snapshot
- LLM recommendation
- 7일·30일 shadow simulation
- guardrail evaluation
- OFF, RECOMMEND, LIMITED_AUTO
- reviewer approve·reject
- admin publish·rollback
- audit trail

Concurrency:

- publish는 If-Match version 요구
- active profile 교체는 단일 transaction
- 동일 Idempotency-Key 재호출은 같은 결과 반환
- rollback도 새 revision을 만들고 과거 행을 수정하지 않음

## B9. 공유 카드·BLOB

구현:

- 생성 시 user coordinate·tier·activity snapshot
- 공개 경고 확인 여부 저장
- Worker image render
- PNG BLOB 저장
- public token hash
- ETag와 conditional GET
- revoke 즉시 공개 접근 차단
- 만료 BLOB 파기 job

이미지에는 이메일, OAuth subject, 상세 설문, 상세 투표가 들어가지 않아야 한다.

## B10. 관리자·관측성

구현:

- source, crawl, issue, model, weights, autopilot, jobs, audit, efficacy metrics API
- analyst, reviewer, admin 역할 행렬
- 모든 변경 action의 audit log
- request_id와 job_id 연결
- JSON structured logging
- provider metrics
- health live·ready

관리자 API 응답에서도 secret은 항상 redacted하고 secret_env_name만 노출한다.

## 6. OpenAPI 단독 소유 규칙

- FastAPI route와 Pydantic schema가 실행 원본이다.
- contracts/openapi.json은 정렬·정규화된 생성 산출물이다.
- 생성 산출물을 수동 편집하지 않는다.
- API 변경마다 CHANGELOG에 added, changed, deprecated, removed와 A 영향도를 기록한다.
- 호환 가능한 필드 추가도 A에게 알린다.
- 필드 삭제·타입 변경은 새 API version 또는 명시적 migration window 없이는 금지한다.

검증 명령은 다음을 실패시켜야 한다.

- 실행 OpenAPI와 committed contract checksum 불일치
- 문서에 없는 endpoint
- operationId 중복
- 안정 오류 code 누락
- 관리자 변경 API의 Idempotency-Key·If-Match 조건 누락

## 7. A의 변경 요청 처리

docs/decisions/mas-a/CR-*.md를 읽되 수정하지 않는다. 같은 번호로 docs/decisions/mas-b/CR-*-response.md를 만든다.

응답 템플릿:

    # Contract change response
    - Decision: accepted | modified | rejected
    - Rationale:
    - Final contract:
    - Compatibility:
    - Migration:
    - OpenAPI revision:
    - Available in integration commit:

승인된 경우:

1. API schema·route를 변경한다.
2. migration이 필요하면 새 파일을 만든다.
3. contract와 checksum을 재생성한다.
4. CHANGELOG에 A 영향도를 기록한다.
5. response에 integration commit을 남긴다.

## 8. 테스트 의무

### Unit

- URL canonicalization
- 정치축 clamp와 weight validation
- 단일 GPT 평가·confidence
- vote aggregate
- read eligibility
- credit idempotency·reversal
- Auto Pilot guardrail
- share public token

### DB

- fresh migration
- upgrade·downgrade
- FK·unique·check
- concurrent vote, job claim, credit event
- blob limit·dedupe·expiry
- account deletion

### Contract

- OpenAPI checksum
- success·error envelope
- auth·role matrix
- cursor stability
- Idempotency-Key replay
- If-Match conflict

### Integration

1. mock OAuth 가입·동의·설문
2. RSS fixture 수집·기사 version
3. issue clustering
4. 3개 stub model 분석
5. score calculation
6. feed 조회
7. read return·credit
8. vote·aggregate·recalculate
9. efficacy response
10. share render·public get·revoke
11. recommendation·simulation·approve·rollback

외부 네트워크와 실제 시크릿 없이 위 흐름이 재현되어야 한다.

## 9. 통합 책임

### 병합 순서

1. B backend 변경을 dev/mas-b에서 검증한다.
2. contract와 migration을 integration에 병합한다.
3. A가 최신 contract로 클라이언트와 UI를 갱신하도록 commit을 알린다.
4. A 브랜치가 준비되면 B가 apps/web 변경만 포함하는지 검사한다.
5. A를 integration에 병합한다.
6. 전체 로컬 서비스를 실행하고 실제 API E2E를 수행한다.

### 충돌 규칙

- apps/web 충돌은 A에게 해결 요청하며 B가 임의로 고치지 않는다.
- root, contracts, db, backend 충돌은 B가 해결한다.
- 상대 소유 경로를 건드린 commit은 병합 전에 분리하거나 되돌리도록 요청한다.
- generated artifact 충돌은 원본에서 재생성하며 hand merge하지 않는다.

### 경로 검사

병합 전 각 브랜치 diff가 허용 경로만 포함하는지 자동 검사한다. 예외는 사전에 기록된 contract change response가 있을 때만 허용한다.

## 10. 로컬 실행 계약

scripts/dev 안에 다음 목적의 비파괴적 명령을 제공한다.

- MariaDB 연결 확인
- migration 적용
- 개발 seed
- FastAPI 실행
- Worker 실행
- OpenAPI 생성·검증
- backend test
- full integration test

호스트에 MariaDB가 없으면 설치 방법을 문서화하되 Docker를 필수 전제로 만들지 않는다. 각 프로세스는 Ctrl-C와 SIGTERM에 정상 종료해야 한다.

환경변수 원칙:

- 실제 로컬·EC2 값의 단일 원본은 저장소 루트 .env다.
- FastAPI, Worker, Next.js 서버 실행 스크립트는 같은 루트 파일을 명시적으로 로드한다.
- 서비스 디렉터리별 env 파일은 만들지 않는다.
- NEXT_PUBLIC_ allowlist만 Next.js 브라우저 번들에 전달한다.
- DATABASE_URL, SESSION_SECRET, OAuth client secret과 LLM API key는 서버 프로세스 전용이다.
- 루트 .env는 Git에서 제외하고 파일 권한 600을 요구한다.
- .env.example은 키 이름·설명·예시 형식만 담고 실제 값은 절대 담지 않는다.

## 11. 배포 경계

현재 작업에서는 로컬 구현까지만 수행한다.

문서화할 것:

- 실행 명령
- 내부 포트
- health endpoint
- 환경변수 이름
- migration 선행조건
- 프로세스 시작·종료 순서
- DB·BLOB 백업 요구사항

수행하지 않을 것:

- EC2 접속
- systemd 설치·재시작
- MariaDB 운영 migration
- TLS·리버스 프록시·방화벽 설정
- 실제 시크릿 주입

별도 EC2 인프라 작업 결과와 자격정보가 전달된 뒤 배포 단계를 새 작업으로 시작한다.

## 12. 완료 보고서

완료 시 다음을 전달한다.

- 구현 endpoint와 미구현 endpoint
- 최종 OpenAPI checksum
- migration head revision
- 사용한 MariaDB 버전과 호환성
- unit, DB, contract, integration 결과
- stub·OpenAI Responses API 전환 방법
- queue 처리량과 알려진 한계
- 보안·개인정보 미해결 항목
- A의 변경 요청 처리 상태
- A 소유 경로를 수정하지 않았다는 경로 검사 결과
- integration 브랜치 전체 수직 슬라이스 결과
