# 정치 관점 균형 뉴스 플랫폼 - Master Plan & Specification

문서 상태: 병렬 개발 기준선 v1.0  
기준: 기존 Q&A와 `.agent/plan_seed.pdf`  
실행 지침: [`MAS_1.md`](./MAS_1.md), [`MAS_2.md`](./MAS_2.md)

## 0. 문서 권위와 구현 분담

이 문서는 제품·데이터·API·운영의 단일 기준이다. `MAS_1.md`와 `MAS_2.md`는 이 명세를 구현하기 위한 작업 분담 문서이며 제품 요구사항을 임의로 바꾸지 않는다.

- **MAS_1**: `apps/web/**`의 Next.js 사용자·관리자 웹
- **MAS_2**: FastAPI, MariaDB, Worker, 계약, 루트 설정과 최종 통합
- 계약의 실행 원본: FastAPI route와 Pydantic schema
- 공유 계약: 생성된 `contracts/openapi.json`
- 실제 환경값의 단일 원본: 저장소 루트 `.env`
- 현재 배포 경계: 로컬에서 전체 수직 슬라이스 검증까지. EC2 변경은 별도 작업이다.

요구사항 강도:

- **MUST**: 출시 또는 통합을 위해 필수
- **SHOULD**: 특별한 사유가 없다면 구현
- **MAY**: 품질과 일정에 따라 선택

---

## 1. 제품 정의

### 1.1 한 문장

여러 언론과 AI·사용자 평가를 결합해 기사의 정치적 관점과 과장성을 다축으로 설명하고, 사용자가 같은 이슈의 다른 관점을 실제로 읽도록 돕는 참여형 뉴스 플랫폼이다.

### 1.2 문제

- 추천 알고리즘은 사용자가 이미 선호하는 관점의 기사만 반복적으로 보게 할 수 있다.
- 같은 사건도 출처에 따라 의제, 단어, 인용 주체와 책임 귀속이 달라지지만 이를 한 화면에서 비교하기 어렵다.
- 단일 진보-보수 라벨은 경제, 사회문화와 국가·대외관의 차이를 과도하게 단순화한다.
- 반대 관점 소비는 자발적으로 잘 일어나지 않으며 단순 클릭 보상은 어뷰징되기 쉽다.
- 언론사 또는 AI 하나의 판단만 공개하면 점수의 근거와 정정 가능성에 대한 신뢰가 낮다.

### 1.3 핵심 가치

> 같은 이슈를 여러 관점에서 읽고, 근거를 비교하고, 판단은 사용자에게 돌려준다.

### 1.4 제품 원칙

1. **이슈 비교 우선**: 언론사 낙인보다 같은 사건의 보도 차이를 먼저 보여준다.
2. **다면 좌표**: 정치 관점을 3축으로 표현하고 과장성은 별도 축으로 분리한다.
3. **사실성과 이념 분리**: 팩트체크 결과는 이념 좌표 방향을 직접 바꾸지 않는다.
4. **근거와 불확실성**: 점수, 근거, 모델별 평가, confidence와 버전을 함께 제공한다.
5. **인접 관점부터**: 사용자의 정반대보다 현재 관점과 가까우면서 다른 기사를 우선 제안한다.
6. **실제 소비 보상**: 클릭이 아니라 검증 가능한 읽기 복귀 행동에 활동 크레딧을 준다.
7. **민감정보 보호**: 자기보고·행동 정치 좌표는 별도 동의와 철회가 가능한 민감정보다.
8. **가중치 통제**: Auto Pilot은 기본적으로 제안만 하며 자동 적용에는 강한 guardrail이 필요하다.
9. **접근 가능한 시각화**: 3D와 동일한 정보를 2D와 표로도 제공한다.
10. **운영 변경 추적**: 가중치, 모델, 점수, 관리자 조치는 버전과 감사 로그를 남긴다.

### 1.5 비목표

- 가장 중립적이거나 올바른 언론사의 절대 순위
- 정치 관점 점수로 기사의 진실성 또는 품질을 단정
- 사용자의 공개 정치 성향 프로필 생성
- 자유 댓글 중심의 정치 커뮤니티
- 체류 시간만으로 완독을 단정
- 크레딧을 정치적 정답에 대한 보상으로 표현
- 사용자 투표가 공식 점수를 즉시 덮어쓰는 구조
- 무검토 완전 자동 가중치 운영
- 기사 전문을 복제해 원문을 대체

### 1.6 학술·제도 근거와 제품 함의

- 온라인 뉴스 노출은 추천 알고리즘뿐 아니라 사용자의 선택에도 영향을 받는다. 피드 다양성 보정과 사용자의 능동적 비교 행동을 함께 설계한다. [Bakshy, Messing, Adamic, Science 2015](https://doi.org/10.1126/science.aaa1160)
- 검색·소셜 경로는 이념적 거리와 반대 관점 노출을 동시에 높일 수 있다. 단순 노출량보다 이슈 단위 비교 완료와 관점 분산을 측정한다. [Flaxman, Goel, Rao, Public Opinion Quarterly 2016](https://doi.org/10.1093/poq/nfw006)
- 반대 견해를 강제로 노출한 현장 실험에서 일부 집단의 양극화가 증가했다. 정반대 극점만 추천하지 않고 인접 관점, 공통 사실과 프레이밍 차이부터 제시한다. [Bail et al., PNAS 2018](https://doi.org/10.1073/pnas.1804840115)
- 내부 정치 효능감은 정치 신뢰와 분리해 측정한다. 반복 설문은 검증된 내부 효능감 문항 구조를 참고하고 한국어 파일럿을 거친다. [Niemi, Craig, Mattei, APSR 1991](https://doi.org/10.2307/1963953)
- 정치적 견해는 개인정보 보호법 제23조의 민감정보다. 일반 개인정보와 별도 동의하고 안전성 확보 조치를 적용한다. [국가법령정보센터, 개인정보 보호법 제23조](https://law.go.kr/LSW/lsSideInfoP.do?docCls=jo&joBrNo=00&joNo=0023&lsiSeq=270351&urlMode=lsScJoRltInfoR)
- 행동 기반 좌표는 자동화된 개인정보 처리다. 첫 버전은 좌표를 권리·의무·가격·접근 제한에 사용하지 않는다. 해당 용도로 확장할 때 설명·거부 요구권을 재검토한다. [개인정보 보호법 제37조의2](https://www.law.go.kr/LSW/lsLinkCommonInfo.do?chrClsCd=010202&lsJoLnkSeq=1029334889)
- 기사·검색 API 데이터는 공급자 약관과 저작권 조건을 소스별로 검토한다. 공개 웹이라는 이유만으로 장기 저장·가공·재배포를 허용한다고 가정하지 않는다. [NAVER API 서비스 이용약관](https://developers.naver.com/products/terms/), [국가법령정보센터, 저작권법](https://www.law.go.kr/LSW/lsInfoP.do?lsId=000798)

이 절은 제품·기술 설계 기준이며 법률 자문을 대체하지 않는다. 공개 베타 전에 개인정보·저작권 전문 검토를 완료한다.

---

## 2. 사용자와 권한

### 2.1 사용자 유형

- **Guest**: 공개 이슈·기사·방법론·공유 카드 열람
- **Member**: 동의, 설문, 읽기 세션, 투표, 크레딧, 개인 리포트와 공유 카드
- **Analyst**: 수집·이슈·모델·작업 상태 조회 및 허용된 검수
- **Reviewer**: 가중치 추천과 시뮬레이션 승인·거부
- **Admin**: 정책, 역할, 모델, 가중치 publish·rollback을 포함한 전체 운영

### 2.2 핵심 사용자 여정

1. Kakao, Naver 또는 Google OAuth로 로그인한다.
2. 서비스 동의와 정치 민감정보 별도 동의를 확인한다.
3. 필수 정치 설문과 선택형 인구통계 설문을 완료한다.
4. 자기보고 좌표를 확정적 정체성이 아닌 현재 응답 결과로 확인한다.
5. 홈의 다양성 보정 피드 또는 이슈별 균형 묶음에서 기사를 선택한다.
6. 이슈 내 출처, 핵심 주장, 3축 좌표와 과장성 차이를 비교한다.
7. 읽기 세션을 시작해 원문으로 이동하고 플랫폼에 복귀한다.
8. 자격을 충족하면 활동 크레딧을 받고 기사에 투표한다.
9. 활동 레벨·티어와 정치적 효능감 변화를 확인한다.
10. 원할 경우 공개 경고를 확인한 뒤 정치 좌표 공유 카드를 만들고 언제든 폐기한다.

### 2.3 운영자 여정

1. 수집 정책과 출처 상태를 확인한다.
2. 실패 crawl을 재시도하고 이슈를 merge·split한다.
3. 모델별 비용, 지연, 불일치와 점수 버전을 검토한다.
4. 가중치 draft와 7일·30일 shadow simulation을 비교한다.
5. reviewer가 추천을 승인 또는 거부한다.
6. admin이 `If-Match`와 `Idempotency-Key`를 사용해 publish 또는 rollback한다.
7. 모든 변경의 before·after·reason을 감사 로그에서 확인한다.

---

## 3. 제품 범위

### 3.1 사용자 기능

- OAuth 로그인과 세션
- 버전된 동의와 정치 설문
- 선택형 인구통계
- 다양성 보정 뉴스 피드
- 이슈별 균형 기사 묶음
- 기사·언론사·사용자 3축 좌표
- 기사 과장성 평가
- 멀티 LLM 결과의 제한 공개 요약
- confidence와 score version
- 원문 읽기 세션과 복귀 판정
- 활동 크레딧, 레벨과 티어
- 사용자 투표와 집계
- 정치적 효능감 기준선·후속 설문
- 개인 추이와 관점 소비 리포트
- 3D, 2D projection과 표
- 정치 좌표 공유 카드 생성·다운로드·폐기
- 데이터 내보내기, 동의 철회와 계정 삭제

### 3.2 관리자 기능

- 출처 정책과 수집 상태
- crawl 실행·오류·재시도
- 이슈 merge·split
- LLM provider/model 상태, 비용, 지연과 불일치
- 가중치 revision, draft, simulation, publish와 rollback
- Auto Pilot 모드와 guardrail
- 작업 큐 retry·cancel
- 사용자 효능감 aggregate
- 역할 기반 접근 제어
- 변경 감사 로그

### 3.3 초기 콘텐츠 범위

- 대한민국·한국어 정치, 정책과 주요 사회 이슈
- API·RSS 우선, 정책 승인된 출처만 crawler 사용
- 기사 전문을 공개하지 않고 제목, 출처, 자체 요약, 제한 근거와 원문 링크 제공
- 외부 네트워크 없이도 fixture와 deterministic LLM stub으로 전체 흐름 재현

---

## 4. 정치 좌표와 평가 모델

### 4.1 3축

각 축의 저장·API·UI 범위는 정수 `-100 ~ +100`이다. `0`은 진실·중립 판정이 아니라 가치 쌍의 중앙 또는 판단 불충분이다.

| 축 | - 방향 | + 방향 | 대표 주제 |
|---|---|---|---|
| X 경제 | 평등·재분배·복지·국가 개입 | 시장·경쟁·규제 완화·개인 책임 | 세금, 복지, 노동, 규제 |
| Y 사회문화 | 질서·전통·규범·권위 | 개인 자유·다양성·변화 개방 | 젠더, 교육, 집회, 치안 |
| Z 국가·대외 | 국제협력·다자주의 | 국가 우선·주권·안보 | 외교, 국방, 이민, 국제기구 |

### 4.2 과장성

`sensationalism`은 이념 좌표와 독립된 정수 `0 ~ 100` 값이다.

분석 요소:

- 제목과 본문의 정서·강도 차이
- 공포, 분노, 위기감의 과도한 유발
- 근거보다 단정이 앞서는 표현
- 선택적 수치와 맥락 생략
- 클릭을 유도하는 과도한 제목

과장성은 허위 판정이 아니며 팩트체크와 분리한다.

### 4.3 기사 분석 루브릭

- 의제 선택
- 원인과 책임 귀속
- 강조한 정치·사회 가치
- 인용한 주체와 비중
- 어휘와 정서
- 포함하거나 생략한 맥락
- 제안·암시한 정책 방향
- 과장성 근거

### 4.4 단일 OpenAI GPT 분석

- 외부 LLM 호출은 OpenAI Responses API와 `OPENAI_API_KEY`만 사용한다.
- 기본 모델은 `gpt-5.6-luna`, reasoning effort는 `xhigh`이다.
- 관리자는 활성 GPT model id와 reasoning effort를 변경할 수 있다.
- content-first 평가 시 언론사 이름을 가린다.
- 각 결과는 `model_alias`, 실제 model id, prompt version, latency, token, error와 연결한다.
- 근거 위치는 분석한 기사 원문 버전에 연결한다.
- 단일 성공 평가가 공식 점수 후보가 되며 기존 ensemble 필드는 호환성을 위해 유지한다.
- 공개 rationale은 개인·시크릿·긴 원문을 포함하지 않는 제한 요약이다.
- 외부 호출이 없는 테스트에서는 단일 deterministic stub provider를 쓴다.

### 4.5 점수 구성

공식 기사 점수는 최소 다음 component를 버전과 함께 보존한다.

- 단일 GPT content assessment
- 기사 간 상대 framing 차이
- 사용자 투표 aggregate
- shrinkage가 적용된 언론사 prior
- 품질·표본·모델 spread 기반 confidence
- 별도 sensationalism

팩트체크 결과는 화면에 병기할 수 있지만 이념축 방향을 직접 변경하지 않는다.

개념식:

```text
article_axis_score = clamp(
  w_model * llm_ensemble
  + w_relative * issue_relative_assessment
  + w_crowd * qualified_vote_aggregate
  + w_source * shrunk_source_prior,
  -100, +100
)

confidence = f(
  successful_model_count,
  inverse_model_spread,
  evidence_quality,
  qualified_vote_count,
  source_prior_sample_size
)
```

정확한 가중치는 immutable `WeightProfileRevision`에 저장한다.

### 4.6 언론사 좌표

- 언론사의 고정 낙인으로 기사에 점수를 복사하지 않는다.
- 일정 기간 검증된 기사 분포에서 shrinkage prior를 계산한다.
- 표본이 적으면 전체 평균 방향으로 수축한다.
- 화면에는 기간, 기사 수, confidence와 분포를 함께 표시한다.

### 4.7 사용자 좌표

- `self_reported_profile`: 가입 설문으로 생성
- `behavioral_profile`: 소비·투표로 갱신하며 기본 비활성
- 두 프로필을 섞기 전에 별도 동의와 정책 버전이 필요하다.
- 사용자에게는 관찰값과 불확실성으로 표현하고 정치적 정체성으로 단정하지 않는다.
- 공개 공유는 별도 확인을 거친 snapshot만 사용한다.

### 4.8 점수 버전과 정정

- 공식 점수는 immutable `ScoreVersion` snapshot으로 재현 가능해야 한다.
- 기사 수정 시 기존 분석은 stale이 되고 새 원문 버전을 분석한다.
- 모델·prompt·가중치 변경은 새 버전을 만든다.
- rollback도 과거 행을 수정하지 않고 새 revision을 만든다.
- 사용자 화면에 confidence, score version과 마지막 계산 시각을 표시한다.

---

## 5. 데이터 모델

모든 ID는 애플리케이션 생성 ULID `CHAR(26)`, 시각은 UTC를 사용한다. enum은 애플리케이션과 DB 제약에서 함께 검증한다.

### 5.1 인증·사용자·동의

```text
users
  id, role, status, display_name, created_at, deleted_at

oauth_accounts
  id, user_id, provider, provider_subject, created_at

sessions
  id, user_id, token_hash, csrf_hash, expires_at, revoked_at

consent_versions
  id, purpose, version, body_hash, active_from

user_consents
  id, user_id, consent_version_id, granted_at, withdrawn_at

questionnaire_versions
  id, kind, version, schema_json, scoring_json, active_from

questionnaire_responses
  id, user_id, questionnaire_version_id, encrypted_payload, submitted_at

user_demographics
  user_id, age_band, gender_response, consent_version_id, updated_at

user_profiles
  id, user_id, kind, x, y, z, confidence, source_version, active, created_at
```

### 5.2 콘텐츠·이슈·수집

```text
sources
  id, name, source_type, canonical_url, policy_status, active

source_adapters
  id, source_id, adapter_type, config_json, rate_limit, active

crawl_runs
  id, source_id, status, started_at, finished_at, stats_json, error_json

articles
  id, source_id, canonical_url, title, author, published_at, current_version_id, status

article_versions
  id, article_id, content_hash, normalized_text_ref, fetched_at, modified_at

issues
  id, title, summary, status, opened_at, last_activity_at, version

issue_memberships
  issue_id, article_id, confidence, created_at

fact_check_references
  id, article_id, provider, verdict, url, published_at
```

### 5.3 모델·점수·투표

```text
model_aliases
  id, alias, provider, actual_model_id, status, config_json

model_assessments
  id, article_version_id, model_alias_id, prompt_version
  x, y, z, sensationalism, confidence, evidence_json
  raw_response_ref, token_usage, latency_ms, status, created_at

weight_profile_revisions
  id, revision, status, weights_json, guardrails_json
  based_on_revision_id, created_by, created_at, published_at

score_versions
  id, article_version_id, weight_revision_id
  x, y, z, sensationalism, confidence
  components_json, status, created_at

votes
  id, user_id, article_id, revision
  x, y, z, sensationalism
  quality_status, active, created_at, updated_at

vote_aggregate_snapshots
  id, article_id, version, aggregate_json, segment_json, created_at
```

### 5.4 피드·읽기·크레딧·효능감

```text
feed_impressions
  id, user_id, article_id, issue_id, reason_code, rank, created_at

read_sessions
  id, user_id, article_id, token_hash, status
  outbound_at, returned_at, client_elapsed_ms, policy_version

credit_ledger
  id, user_id, event_type, event_key, delta, policy_version
  status, reversed_ledger_id, created_at

tier_snapshots
  id, user_id, credit_total, level, tier, policy_version, created_at

efficacy_responses
  id, user_id, questionnaire_version_id, normalized_score, submitted_at

efficacy_aggregate_snapshots
  id, cohort_key, period, aggregate_json, created_at
```

### 5.5 Auto Pilot·작업·공유·감사

```text
weight_recommendations
  id, base_revision_id, proposed_weights_json, evidence_snapshot_id
  provider_assessment_ref, status, created_at

weight_simulations
  id, recommendation_id, window_days, metrics_json, guardrail_result, created_at

autopilot_settings
  id, mode, guardrails_json, version, updated_by, updated_at

jobs
  id, job_type, dedupe_key, status, priority, available_at
  lease_owner, lease_expires_at, attempts, max_attempts, payload_json, last_error_json

share_cards
  id, user_id, public_token_hash, template, display_name
  snapshot_json, status, blob_id, expires_at, revoked_at, created_at

stored_blobs
  id, sha256, mime_type, byte_size, payload, expires_at, created_at

audit_logs
  id, actor_id, action, target_type, target_id
  before_json, after_json, reason, request_id, created_at
```

### 5.6 핵심 제약

- 공유된 migration은 수정하지 않고 새 migration으로 정정한다.
- `article_versions`와 score snapshot은 과거 결과를 보존한다.
- 한 사용자의 기사별 active vote는 하나이며 revision history를 가진다.
- `jobs(job_type, dedupe_key)`는 중복 side effect를 막는다.
- `credit_ledger.event_key`는 idempotent하며 정정은 reversal 행으로 처리한다.
- `stored_blobs`는 애플리케이션에서 10 MiB 이하, SHA-256 중복 검사를 한다.
- 작은 인구통계·효능감 cohort는 공개하지 않는다.
- 정치 설문 원응답과 동의 데이터는 일반 콘텐츠 데이터보다 엄격히 분리한다.

### 5.7 물리 타입·FK·인덱스 기준

| 대상 | 타입·제약 |
|---|---|
| 모든 id | `CHAR(26) PRIMARY KEY`, 애플리케이션 ULID |
| 모든 created_at·updated_at | `DATETIME(6)`, UTC |
| x·y·z | `SMALLINT NOT NULL CHECK(value BETWEEN -100 AND 100)` |
| sensationalism | `TINYINT UNSIGNED CHECK(value BETWEEN 0 AND 100)` |
| confidence | `DECIMAL(5,4) CHECK(value BETWEEN 0 AND 1)` |
| URL hash·token hash·checksum | `BINARY(32)`, SHA-256 |
| JSON | MariaDB `JSON` + `CHECK(JSON_VALID(column))` |
| BLOB | `LONGBLOB`, 애플리케이션 10 MiB 상한 |

필수 unique·index:

- `oauth_accounts(provider, provider_subject)` UNIQUE
- `sessions(token_hash)` UNIQUE, `sessions(user_id, expires_at)` INDEX
- `articles(canonical_url_hash)` UNIQUE, `articles(source_id, published_at)` INDEX
- `article_versions(article_id, content_hash)` UNIQUE
- `issue_memberships(issue_id, article_id)` PRIMARY KEY
- `model_assessments(article_version_id, model_alias_id, prompt_version)` UNIQUE
- `weight_profile_revisions(revision)` UNIQUE
- `votes(user_id, article_id, revision)` UNIQUE, 활성 vote는 transaction으로 하나만 유지
- `credit_ledger(user_id, event_type, event_key)` UNIQUE
- `jobs(job_type, dedupe_key)` UNIQUE, `jobs(status, available_at, priority)` INDEX
- `share_cards(public_token_hash)` UNIQUE
- `audit_logs(target_type, target_id, created_at)` INDEX

FK는 사용자가 탈퇴해도 운영·점수 재현성에 필요한 익명 집계가 깨지지 않도록 파기 정책을 구분한다. 세션·공유 token은 즉시 revoke하고, 개인 좌표·설문·투표·읽기 이력은 별도 삭제 job이 법적 보존 조건을 확인한 뒤 파기 또는 비식별화한다.

---

## 6. 기능 명세

### 6.1 인증과 동의

- Kakao, Naver, Google OAuth adapter와 로컬 mock provider
- callback `state`, `nonce`, redirect allowlist 검증
- opaque session token; DB에는 SHA-256 hash만 저장
- CSRF 보호, session rotation과 revoke
- OAuth access token은 최소 보존 또는 즉시 폐기
- 민감정보 별도 동의 버전
- 동의 철회 시 behavioral profile과 개인화 중지
- 데이터 export와 계정 삭제를 비동기 작업으로 처리

### 6.2 온보딩 설문

- 정치 설문은 현재 자기보고 좌표 계산에 필요한 필수 단계다.
- 인구통계는 선택이며 거부해도 서비스를 이용할 수 있다.
- 설문 문항과 정규화 산식은 버전된다.
- 결과는 확정적 정치 정체성이 아닌 응답 기반 좌표와 confidence로 표시한다.

### 6.3 수집과 이슈

- source adapter는 `API | RSS | CRAWLER`를 지원한다.
- robots·약관 상태가 승인되지 않으면 crawler job을 거부한다.
- URL canonicalization, 본문 hash, 기사 versioning을 수행한다.
- 기사 수정 후 이전 분석은 stale 처리한다.
- 이슈 군집은 자동 후보와 관리자 merge·split을 지원한다.
- parser 테스트는 실시간 외부 사이트 대신 HTML·RSS·API fixture를 사용한다.

### 6.4 피드

후보 점수 요소:

- 사용자 관련성
- 최신성
- 출처 다양성
- 사용자 좌표와의 거리
- 분석 품질과 confidence
- 동일 이슈 내 관점 보완성

규칙:

- 같은 출처 연속 노출을 제한한다.
- 정반대 관점보다 인접 관점을 우선한다.
- 개인화 불가 시 비개인화 균형 피드를 제공한다.
- 모든 추천은 안정된 `reason_code`를 가진다.
- 이슈별 균형 조건이 부족하면 결과를 조작하지 않고 "준비 중"으로 표시한다.

### 6.5 읽기 세션

1. `POST /articles/{id}/read-sessions`가 signed redirect token과 `redirect_url`을 반환한다.
2. 서버가 outbound 시각을 기록하고 사용자를 원문으로 보낸다.
3. 복귀 시 `POST /read-sessions/{id}/return`을 호출한다.
4. 서버 outbound·return 시간, 겹침·반복·만료를 검증한다.
5. browser visibility와 client elapsed는 보조 신호일 뿐 완독 증명이 아니다.
6. 결과는 `eligible | rejected | expired`와 reason code로 반환한다.

### 6.6 활동 크레딧·레벨·티어

- immutable ledger로 적립·취소를 기록한다.
- 동일 event의 중복 적립을 막는다.
- 정책 변경은 새 policy version을 만든다.
- 잘못 지급된 크레딧은 기존 행 수정이 아닌 reversal로 취소한다.
- 티어는 credit snapshot이며 정치적 우열을 의미하지 않는다.

### 6.7 투표

- 기사별 3축과 과장성 슬라이더
- revisioned active vote
- 작은 인구통계 segment 숨김
- quality status와 비정상 패턴 hook
- 투표 aggregate와 공식 score component는 버전 snapshot
- 제출·수정·삭제가 가능하며 투표가 공식 점수를 즉시 교체하지 않는다.

### 6.8 정치적 효능감

- 버전된 baseline과 follow-up 설문
- 정규화 산식과 개인 delta
- due survey 정책
- 개인 추이 화면
- 작은 cohort aggregate 숨김
- 상관관계를 인과로 표현하지 않으며 제품 실험에서 별도 검증

### 6.9 시각화

- 기사·언론사·사용자 point 유형 구분
- X·Y·Z 3D 좌표, confidence, 범례와 선택 상세
- 날짜·score version 시계열
- 2축씩 보는 2D projection
- 동일 데이터의 정렬 가능한 표
- WebGL 실패와 reduced motion을 위한 fallback
- 3D를 사용하지 않아도 모든 정보와 기능에 접근 가능

### 6.10 공유 카드

- 생성 시 사용자 좌표, 티어와 활동의 snapshot을 저장한다.
- 정치 좌표 공개에 대한 별도 확인이 필요하다.
- `queued | rendering | ready | failed | revoked` 상태
- Worker가 PNG를 만들고 MariaDB BLOB에 저장한다.
- public token은 hash만 저장한다.
- ETag와 conditional GET 지원
- revoke 즉시 공개 접근 차단
- 만료 BLOB 파기
- 이메일, OAuth subject, 상세 설문·투표를 이미지에 포함하지 않는다.

### 6.11 Auto Pilot 가중치

상태:

- Weight revision: `draft | simulation | active | archived`
- Auto Pilot mode: `OFF | RECOMMEND | LIMITED_AUTO`

흐름:

1. 시계열 evidence snapshot을 만든다.
2. LLM이 새 가중치를 추천한다.
3. 7일·30일 shadow simulation을 실행한다.
4. 정확도, 다양성, 급격한 이동, 집단별 오류 guardrail을 평가한다.
5. reviewer가 승인 또는 거부한다.
6. admin이 publish한다.
7. 문제 발생 시 새 revision으로 rollback한다.

동시성:

- publish는 `If-Match` version이 필요하다.
- active profile 교체는 단일 transaction이다.
- 같은 `Idempotency-Key` 재호출은 같은 결과를 반환한다.
- LIMITED_AUTO는 사전 승인된 작은 범위와 즉시 rollback 조건에서만 허용한다.

### 6.12 작업 큐

MariaDB만 사용하며 별도 Redis를 요구하지 않는다.

상태:

```text
PENDING | LEASED | SUCCEEDED | FAILED | DEAD | CANCELLED
```

필수 동작:

- priority와 `available_at`
- transaction claim
- `lease_owner`, `lease_expires_at`
- exponential backoff + jitter
- `max_attempts` 후 DEAD
- graceful shutdown
- handler idempotency
- `SKIP LOCKED` 지원 여부에 따른 안전한 대체 claim

---

## 7. API 계약

공통 규칙:

- Prefix `/api/v1`
- JSON, UTC ISO 8601, ULID
- cookie session + CSRF
- cursor는 opaque
- 안정된 error code와 `request_id`
- 관리자 변경 API는 `Idempotency-Key`
- versioned resource 변경은 `If-Match`
- `429`는 `Retry-After`

오류 형식:

```json
{
  "error": {
    "code": "CONSENT_REQUIRED",
    "message": "별도 동의가 필요합니다.",
    "request_id": "01...",
    "retryable": false,
    "details": {}
  }
}
```

### 7.1 인증·사용자

| Method | Path | Auth | Request | Response |
|---|---|---|---|---|
| GET | `/auth/{provider}/start` | 없음 | `redirect_uri` | 302 provider 이동 |
| GET | `/auth/{provider}/callback` | 없음 | provider callback params | 302 onboarding 또는 home |
| POST | `/auth/logout` | Member | 없음 | 204 |
| GET | `/me` | Member | 없음 | 사용자, role, consent·onboarding 상태 |
| GET | `/consents` | Member | 없음 | 활성 동의 문서와 사용자 동의 상태 |
| POST | `/me/consents` | Member | `consent_version_id`, `granted` | 저장된 동의 |
| POST | `/me/questionnaire-responses` | Member | `questionnaire_version_id`, `answers` | 자기보고 좌표 |
| PATCH | `/me/demographics` | Member | 선택형 `age_band`, `gender_response` | 저장된 응답 |
| POST | `/me/export` | Member | 없음 | 202, `job_id` |
| DELETE | `/me` | Member | 확인 문구 | 202, `job_id` |

주요 오류: `AUTH_PROVIDER_DISABLED`, `CONSENT_REQUIRED`, `QUESTIONNAIRE_VERSION_STALE`.

### 7.2 피드·이슈·기사

| Method | Path | Auth | Request | Response |
|---|---|---|---|---|
| GET | `/feed` | 선택 | `mode`, `cursor` | `FeedItem[]`, `next_cursor` |
| GET | `/issues` | 선택 | `topic`, `from`, `to`, `sort`, `cursor` | `IssueSummary[]` |
| GET | `/issues/{issueId}` | 선택 | 없음 | 이슈 요약·상태·분포 |
| GET | `/issues/{issueId}/articles` | 선택 | `perspective`, `cursor` | `ArticleCard[]` |
| GET | `/articles/{articleId}` | 선택 | 없음 | 메타데이터·요약·원문 URL |
| GET | `/articles/{articleId}/assessments` | 선택 | 없음 | 모델별 공개 해석·confidence |
| GET | `/articles/{articleId}/score` | 선택 | 없음 | 3축·과장성·component·version |
| GET | `/articles/{articleId}/score-history` | 선택 | `cursor` | 공개 score snapshot 이력 |
| GET | `/compare` | 선택 | `article_ids` 2부터 4개 | 정규화 비교 행 |
| GET | `/sources/{sourceId}` | 선택 | 없음 | 기간·기사 수·분포·confidence |

### 7.3 읽기·투표·진행도

| Method | Path | Auth | Request | Response |
|---|---|---|---|---|
| POST | `/articles/{articleId}/read-sessions` | Member | `return_path` | `read_session_id`, signed `redirect_url` |
| GET | `/r/{token}` | Member | 없음 | 302 원문 이동 |
| POST | `/read-sessions/{readSessionId}/return` | Member | 선택 `client_elapsed_ms` | `eligible|rejected|expired`, 서버 경과시간, credit 결과 |
| GET | `/articles/{articleId}/votes/aggregate` | 선택 | 없음 | raw·qualified 분포와 표본 수 |
| PUT | `/articles/{articleId}/vote` | Member | `x`, `y`, `z` -100부터 100, `sensationalism` 0부터 100 | 활성 vote revision |
| DELETE | `/articles/{articleId}/vote` | Member | 없음 | 204, 기존 revision 이력 보존 |
| GET | `/me/credits` | Member | `cursor` | 범주·증감·시각, 세부 산식 제외 |
| GET | `/me/progress` | Member | 없음 | credit total, level, tier |
| GET | `/me/efficacy` | Member | 없음 | baseline·follow-up 추이와 due survey |
| POST | `/me/efficacy-responses` | Member | questionnaire version, answers | normalized score, baseline delta |

### 7.4 시각화·공유

| Method | Path | Auth | Request | Response |
|---|---|---|---|---|
| GET | `/visualization/points` | 선택 | `type`, `issue_id`, `from`, `to`, `cursor` | 3D·2D point 목록 |
| GET | `/visualization/timeline` | 선택 | `entity_type`, `entity_id` | 좌표 snapshot 이력 |
| POST | `/share-cards` | Member | `template`, 선택 `display_name`, `political_data_publication_confirmed=true` | 202, card id |
| GET | `/share-cards/{shareCardId}` | Owner | 없음 | 상태·preview metadata |
| GET | `/public/share/{publicToken}` | 없음 | 없음 | 공개 snapshot metadata |
| GET | `/public/share/{publicToken}/image` | 없음 | 선택 `If-None-Match` | PNG 또는 304 |
| DELETE | `/share-cards/{shareCardId}` | Owner | 없음 | 204, token 즉시 폐기 |

### 7.5 관리자

| Method | Path | Role | Request / Response |
|---|---|---|---|
| GET/POST/PATCH | `/admin/sources[/{id}]` | Analyst 조회, Admin 변경 | 소스와 versioned 정책 |
| POST | `/admin/sources/{id}/crawl` | Analyst | 202 crawl job |
| GET | `/admin/crawls` | Analyst | 실행·오류·통계 목록 |
| POST | `/admin/issues/{id}/merge` | Analyst | `target_issue_id` -> 202 |
| POST | `/admin/issues/{id}/split` | Analyst | `article_ids` -> 202 |
| PATCH | `/admin/issues/{id}` | Analyst | 제목·요약·상태 |
| GET/POST/PATCH | `/admin/models[/{id}]` | Analyst 조회, Admin 변경 | alias·provider·secret env 이름 |
| POST | `/admin/articles/{id}/analyze` | Analyst | 202 analysis job |
| GET | `/admin/analysis-runs/{id}` | Analyst | 내부 run·오류 |
| GET/POST | `/admin/weights` | Analyst 조회, Admin 생성 | immutable revision |
| POST | `/admin/weights/{id}/simulate` | Analyst | 7일·30일 simulation job |
| POST | `/admin/weights/{id}/publish` | Admin | `If-Match`, reason |
| POST | `/admin/weights/{id}/rollback` | Admin | target revision, reason |
| GET | `/admin/autopilot/recommendations` | Analyst | 추천 inbox |
| POST | `/admin/autopilot/recommendations/generate` | Reviewer | evidence window |
| POST | `/admin/autopilot/recommendations/{id}/approve` | Reviewer | reason |
| POST | `/admin/autopilot/recommendations/{id}/reject` | Reviewer | reason |
| PUT | `/admin/autopilot/settings` | Admin | mode·guardrail·manual locks |
| GET | `/admin/jobs` | Analyst | queue filter·cursor |
| POST | `/admin/jobs/{id}/retry` | Reviewer | idempotent retry |
| POST | `/admin/jobs/{id}/cancel` | Reviewer | pending cancel |
| GET | `/admin/audit` | Reviewer | actor·action·target·cursor |
| GET | `/admin/metrics/efficacy` | Analyst | 보호된 cohort aggregate |
| GET | `/health/live` | 없음 | FastAPI 프로세스 생존 |
| GET | `/health/ready` | 없음 | MariaDB·필수 서버 설정 준비 상태 |

세부 Pydantic schema와 FastAPI OpenAPI가 실행 원본이지만, method·경로·권한·의미는 이 표와 달라질 수 없다.

---

## 8. 화면과 UX

### 8.1 경로

공개·사용자:

- `/`, `/issues`, `/issues/[issueId]`, `/articles/[articleId]`
- `/login`
- `/onboarding/consent`
- `/onboarding/questionnaire`
- `/onboarding/demographics`
- `/progress`, `/efficacy`
- `/visualization`
- `/share/new`, `/share/[shareCardId]`
- `/settings/privacy`

관리자:

- `/admin/sources`, `/admin/crawls`, `/admin/issues`
- `/admin/models`, `/admin/weights`, `/admin/autopilot`
- `/admin/jobs`, `/admin/audit`, `/admin/metrics/efficacy`

### 8.2 공통 상태

모든 핵심 화면은 다음 상태를 가져야 한다.

- loading
- empty
- partial data
- recoverable error
- fatal error
- unauthorized
- consent required
- stale score
- processing / 준비 중
- version conflict
- rate limited

### 8.3 접근성·표현

- 모바일 우선, 데스크톱 확장
- WCAG 2.2 AA 목표
- focus 항상 표시
- 슬라이더는 키보드와 숫자 입력 지원
- 색상만으로 정치축·상태를 구분하지 않음
- reduced motion 지원
- WebGL 실패 시 2D·표 fallback
- 원문 링크를 내부 기사처럼 보이게 하지 않음
- 자기보고 좌표를 확정적 정체성으로 표현하지 않음
- 체류 시간을 완독으로 표현하지 않음
- 활동 크레딧을 정치적 우열이나 정답으로 표현하지 않음

---

## 9. 시스템 구조

### 9.1 기술 기준

- Web: Next.js App Router, TypeScript strict
- API: Python 3.12+, FastAPI, Pydantic v2
- ORM: SQLAlchemy 2 async
- DB: MariaDB + async driver
- Migration: Alembic
- Worker queue: MariaDB
- Test: pytest, unit/component, accessibility, Playwright E2E
- API type: OpenAPI에서 생성
- 3D: React Three Fiber 계열 가능, 2D·표 필수

로컬 기본 실행:

| 프로세스 | 주소·포트 | 역할 |
|---|---|---|
| Next.js | `http://localhost:3000` | 사용자·관리자 웹 |
| FastAPI | `http://localhost:8000` | `/api/v1`, OAuth, health |
| MariaDB | `localhost:3306` | 영속 데이터, 작업 큐, BLOB |
| Python Worker | 수신 포트 없음 | MariaDB job lease·handler 실행 |

EC2에서는 같은 네 프로세스를 호스트 프로세스로 실행하고 리버스 프록시가 `/`를 Next.js, `/api/`를 FastAPI로 전달한다. 실제 프록시·TLS·systemd·도메인·시크릿 주입은 별도 배포 작업이다.

### 9.2 저장소

```text
apps/
  web/
  api/
  worker/
contracts/
  openapi.json
  CHANGELOG.md
  checksum.txt
db/
  alembic/
  seeds/
scripts/
  dev/
  verify/
tests/
  integration/
docs/
  decisions/
```

### 9.3 환경변수

- 실제 로컬·서버 값의 단일 원본은 루트 `.env`
- `.env`는 Git 제외, 파일 권한 600
- `.env.example`은 이름·설명·형식만 포함
- 서비스별 `.env` 파일 금지
- 브라우저에는 `NEXT_PUBLIC_` allowlist만 노출
- DB, session, OAuth client secret과 LLM key는 서버 전용
- 로그에서 token, secret, OAuth subject와 설문 원문 redaction

### 9.4 OpenAPI

- FastAPI가 실행 원본
- `contracts/openapi.json`은 정렬·정규화된 생성 산출물
- 수동 편집 금지
- checksum과 CHANGELOG 유지
- operationId 유일성, 안정 오류 code, 관리자 동시성 조건 검사
- 호환 불가능한 변경은 새 API version 또는 migration window 필요

---

## 10. 보안·개인정보·법적 원칙

### 10.1 보안

- OAuth state·nonce·redirect allowlist
- session rotation, revoke, CSRF
- role 기반 route와 action guard
- 관리자 변경의 confirmation, reason과 감사 로그
- 속도 제한과 provider circuit breaker
- BLOB public token hash와 revoke 즉시 차단
- secret redaction과 최소 접근

### 10.2 개인정보

- 정치 설문과 행동 좌표를 민감정보로 취급
- 목적별·버전별 별도 동의
- 선택 인구통계 거부 가능
- 작은 segment·cohort 숨김
- 데이터 내보내기, 철회와 계정 삭제
- 행동 프로필은 기본 비활성
- 공유 카드는 명시적 공개 확인과 즉시 폐기

### 10.3 콘텐츠·법적 위험

- API·RSS를 우선하고 crawler는 정책 승인 후 사용
- 기사 전문을 사용자 화면이나 공개 API에 제공하지 않음
- 관점·과장성·사실성을 구분하는 문구
- 언론사와 사용자가 오류를 신고하고 정정 이력을 볼 수 있는 운영 경로
- 공개 전 저작권, 개인정보, 명예훼손과 선거 관련 법률 검토

---

## 11. Auto Pilot guardrail

최소 guardrail:

- 축별 가중치 허용 범위
- 한 revision당 최대 변화량
- 7일·30일 simulation 모두 통과
- 골드 라벨 오차 악화 제한
- 관점·출처·집단별 오류 악화 제한
- 급격한 피드 분포 변화 제한
- 최소 모델 성공률
- 최대 provider 비용·지연
- reviewer 승인
- 즉시 rollback 가능

`LIMITED_AUTO`에서도 guardrail 실패, 데이터 부족, 모델 불일치 급증 또는 비용 한도 초과 시 추천만 생성하고 publish하지 않는다.

---

## 12. 테스트와 품질 게이트

### 12.1 외부 의존성 없는 통합 흐름

다음 흐름은 실제 시크릿과 외부 네트워크 없이 재현돼야 한다.

1. mock OAuth 가입·동의·설문
2. RSS/API/HTML fixture 수집과 기사 버전 생성
3. 이슈 clustering
4. 단일 deterministic stub model 분석
5. 점수 계산과 score version
6. 다양성 보정 feed 조회
7. 원문 read session 복귀와 credit
8. vote·aggregate·score recalculation
9. efficacy follow-up과 개인 delta
10. share render·public get·revoke
11. weight recommendation·simulation·approve·publish·rollback

### 12.2 필수 테스트

- URL canonicalization과 기사 versioning
- 이슈 merge·split idempotency
- 단일 GPT 평가, confidence와 schema rejection
- score clamp, weight validation과 byte-stable 계산
- vote revision과 aggregate
- read eligibility, overlap·repeat·expiry rejection
- credit idempotency와 reversal
- efficacy scoring과 작은 cohort 보호
- Auto Pilot guardrail, version conflict와 rollback
- 공유 public token, BLOB limit·dedupe·expiry
- fresh migration, FK·unique·check와 account deletion
- OpenAPI checksum, auth·role matrix, cursor, stable error code
- 관리자 `Idempotency-Key` replay와 `If-Match` conflict
- WebGL 실패, reduced motion, 키보드와 접근성

### 12.3 품질 게이트

- lint, typecheck, unit, DB, contract, integration, E2E 통과
- 치명 접근성 오류 0
- 실제 secret과 개인정보 fixture 포함 0
- 실행 OpenAPI와 committed checksum 불일치 0
- migration fresh 적용 실패 0
- 같은 job·credit event의 중복 side effect 0
- 관리자 변경 감사 누락 0
- 2D·표 없는 3D 전용 데이터 0

정확도, 수집 성공률, LLM 비용·지연과 어뷰징 오탐의 수치 기준은 대표 fixture를 만든 뒤 릴리스 기준표에 확정한다.

---

## 13. 구현·통합 순서

1. MAS_2가 루트, FastAPI stub, MariaDB migration과 OpenAPI 기준선을 만든다.
2. MAS_1은 mock API로 독립 부트스트랩하고 생성 OpenAPI를 소비한다.
3. MAS_2가 인증·수집·분석·점수·피드·참여 API를 순차 구현한다.
4. MAS_1이 사용자·관리자 화면을 실제 API에 연결한다.
5. API 변경은 문서 기반 contract request/response로 조정한다.
6. MAS_2가 소유 경로를 검사하고 integration에 병합한다.
7. 전체 로컬 수직 슬라이스와 E2E를 실행한다.
8. 알려진 제한, 보안·법률 미해결과 배포 요구사항을 완료 보고서에 남긴다.

## 14. 완료 정의

- [ ] Q&A에서 합의한 사용자·관리자 기능이 동작하거나 명시적 feature flag 상태다.
- [ ] 3축·과장성 점수에 component, confidence와 version이 있다.
- [ ] 팩트체크가 이념 좌표를 직접 변경하지 않는다.
- [ ] OAuth, 동의, 설문, 데이터 권리가 동작한다.
- [ ] 피드·이슈·읽기 복귀·credit·vote가 연결된다.
- [ ] 효능감 baseline·follow-up과 개인 추이가 동작한다.
- [ ] 3D와 동등한 2D·표가 있다.
- [ ] 공유 카드가 공개 확인·render·revoke 전체 흐름을 갖는다.
- [ ] 가중치 추천·simulation·승인·publish·rollback이 감사 가능하다.
- [ ] OpenAPI, migration과 통합 테스트가 재현 가능하다.
- [ ] 외부 네트워크와 실제 시크릿 없이 전체 로컬 흐름을 실행할 수 있다.
- [ ] 민감정보·저작권·접근성·관리자 변경 보호 원칙을 통과한다.
- [ ] EC2 배포는 수행하지 않고 별도 작업에 필요한 실행 계약만 문서화한다.
