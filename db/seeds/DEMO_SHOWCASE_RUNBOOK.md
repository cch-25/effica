# 대표 데이터 운영 절차

`demo_showcase.json`은 대표 사건과 원문 URL만 버전 관리한다. 기사 전문, OAuth 정보,
쿠키, 비밀 값은 넣지 않는다. 각 정책 결정에는 공식 HTTPS 근거를 기록한다. 현재 검수에서
허가가 확인되지 않은 항목은 `PENDING`, 자동수집·AI 처리 또는 재이용을 명시적으로
금지한 출처는 `REJECTED`로 기록되어 있다. `REJECTED`를 운영자가 임의로
`APPROVED`로 바꾸면 안 되며, 출처의 서면 허가나 별도 이용 계약을 확보하거나 허용된
대체 출처로 manifest를 교체해야 한다. 정책·robots·약관 세 상태가 모두 `APPROVED`인
기사만 수집 작업이 생성된다. 사건 일치와 선정 이유도 사람 검수 전에는
`editorial_review_status=PENDING`으로 유지한다. 담당자의 식별 가능한 이름 또는 운영자
ID를 `reviewed_by`에 기록하고 `APPROVED`로 바꾸기 전에는 실제 refresh가 실패한다.

## 적용 전

1. 운영 release와 Alembic revision이 배포 대상과 같은지 확인한다.
2. MariaDB 공급자의 스냅샷 또는 `mariadb-dump --single-transaction`으로 백업한다.
3. 백업 식별자, 저장 위치, 생성 시각, 복원 담당자를 release 기록에 남긴다. 백업 파일과
   자격 증명은 저장소에 커밋하지 않는다.
4. 별도 staging DB에서 백업 복원을 실행하고 `alembic current` 및 `/health/ready`를
   확인한다.
5. manifest의 각 `policy_reference`가 해당 원문과 수집 방식에 적용되는지 다시 확인한다.
   `APPROVED`에는 `PENDING` 메모가 아니라 공식 정책 URL과 검수 결론이 필요하다.
6. 세 사건의 기사들이 같은 사건을 다루는지 사람이 확인하고 검수자와 상태를 기록한다.
7. `./.agents/scripts/run.sh demo-refresh --dry-run --manifest db/seeds/demo_showcase.json`을
   실행한다.

DB를 변경하지 않고 현재 schema, 콘텐츠 수, 분석 provider, queue, manifest 정책 상태를
확인하려면 먼저 다음 명령을 실행한다.

```sh
./.agents/scripts/run.sh demo-preflight
```

## 적용

```sh
./.agents/scripts/run.sh migrate
./.agents/scripts/run.sh demo-refresh \
  --manifest db/seeds/demo_showcase.json \
  --backup-reference '<snapshot-or-release-record-id>'
./.agents/scripts/run.sh demo-audit
```

refresh는 canonical URL hash, issue editorial key, job dedupe key와 issue version별 비교
snapshot을 사용한다. 같은 manifest를
반복 적용해도 기사·이슈·작업 row를 중복 생성하지 않는다. 첫 실행은 수집 작업을, 다음
실행은 수집된 기사 membership과 분석 작업을, 분석 완료 뒤 실행은 검수된 score 승격을
완료할 수 있다. 비교 snapshot은 기사별 분석을 조합해 seed가 직접 만들거나 자동 승인하지
않는다. refresh가 `build_issue_comparison` 작업을 생성하면 worker 완료 뒤 각 대표 이슈에
대해 다음 순서로 사람이 검수한다.

1. `GET /api/v1/admin/issues/{issue_id}/comparison`을 ANALYST 이상 권한으로 호출한다.
2. `common_facts`, 기사별 `headline_frame`, `emphasis`, `omissions_note`, `evidence_refs`,
   모델 provenance와 `article_version_ids`를 원문 및 현재 기사 version과 대조한다.
3. 문제가 있으면 승인하지 말고 입력 기사 또는 비교 작업을 수정·재실행한다.
4. 이상이 없으면 ADMIN 권한, CSRF, 새 `Idempotency-Key`, 그리고 조회한 `snapshot_id`를
   `If-Match`에 넣어 `POST /api/v1/admin/issues/{issue_id}/comparison`을 호출한다. 본문에는
   구체적인 검수 사유를 기록한다.

```sh
curl -sS "$API_BASE/api/v1/admin/issues/$ISSUE_ID/comparison" \
  -H "Cookie: session=$ADMIN_SESSION"

curl -sS -X POST "$API_BASE/api/v1/admin/issues/$ISSUE_ID/comparison" \
  -H "Cookie: session=$ADMIN_SESSION; csrf=$CSRF_TOKEN" \
  -H "X-CSRF-Token: $CSRF_TOKEN" \
  -H "Idempotency-Key: comparison-review-$SNAPSHOT_ID" \
  -H "If-Match: $SNAPSHOT_ID" \
  -H "Content-Type: application/json" \
  --data '{"reason":"원문과 공통 사실·프레이밍·누락 사항을 대조 검수함"}'
```

Phase 2에서는 대표 이슈의 현재 version에 이 절차로 검수된 비교 snapshot까지 있어야
audit가 통과한다. 각 단계 뒤 worker queue를 확인하고, 모든 비교를 검수한 뒤 audit가
`0`으로 종료되는지 확인한다.

`demo-audit` 종료 코드는 P0 실패 `1`, 최신성 경고만 있을 때 `2`, 전체 통과 `0`이다.
의도적으로 과거 기준일을 사용하는 리허설에서는 `--allow-stale`을 사용할 수 있지만,
웹에는 `데모 데이터 기준일`과 업데이트 필요 상태가 그대로 표시되어야 한다.

## Rollback

대표 이슈가 아직 외부에 노출되지 않았다면 우선 해당 EVENT 이슈의
`editorial_priority`를 `NULL`로 바꾸어 노출을 차단한다. 데이터 무결성 문제나 잘못된
membership이 있으면 다음 순서로 전체 복원을 수행한다.

1. API와 worker를 중지해 추가 쓰기를 막는다.
2. 적용 전 기록한 release로 API와 worker를 되돌린다.
3. 적용 전 스냅샷 또는 dump를 새 임시 DB에 먼저 복원하고 row count와 Alembic revision을
   검증한다.
4. 검증된 백업으로 운영 DB를 복원한다.
5. `/health/ready`, OpenAPI checksum, `demo-audit`를 다시 실행한다.
6. 실패한 refresh의 request ID(`demo-refresh:<manifest-version>`)와 복원 결과를 release
   기록에 남긴다.

물리 삭제는 기본 rollback 수단이 아니다. 기존 기사와 분석은 보존하고 대표 노출 metadata를
해제하는 방식을 우선한다.

## 운영 실행 기록

### 2026-08-23 / `phase1-20260823-v5`

- 사람 검수자: `johnnybae` (2026-08-23 Codex 작업 스레드에서 manifest와 운영 실행 승인)
- manifest: `2026-08-23-demo-v5`
- 적용 전 백업: `/opt/perspective-news/backups/phase1-20260823-v5.sql.gz`
- 백업 검증: gzip 무결성 통과, 권한 `0600`, 임시 복원 38개 table 및 적용 전 revision
  `0008_efficacy_questionnaire` 확인
- 적용 revision: `0009_issue_editorial_metadata`
- 대표 데이터 결과: 이슈 3개, 기사 9개, 이슈별 서로 다른 출처 3개, OpenAI 성공 분석
  9개, synthetic 분석 0개, score 9개 승격
- queue 결과: 이번 refresh 범위 작업 18개 `SUCCEEDED`, pending/leased/dead 0개
- 감사 결과: `./.agents/scripts/run.sh demo-audit` 종료 코드 `0`, warning/error 없음
- 운영 상태: `perspective-api.service`, `perspective-worker.service` active 및
  `/health/ready` revision 일치 확인
