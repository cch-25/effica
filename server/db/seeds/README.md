# 실제 한국어 기사 개발 데이터

`python -m db.seeds.seed`는 `articles.json`에 보관된 검증 완료 기사 스냅샷을
MariaDB에 한 트랜잭션으로 적재합니다. 이 작업은 worker의 웹 크롤링 로직과
독립적인 일회성 수동 수집 경로입니다.

러너는 먼저 과거 합성 시드 네임스페이스의 기사, 본문, 버전, 점수, 이슈,
출처와 그 기사에 종속된 활동 데이터를 제거합니다. 이어서 실제 원문 URL,
한국어 제목, 한국어 원문 본문, 발행일, 발행처를 적재하고 한국어 카탈로그와
연결합니다. 재실행해도 동일한 결과가 되도록 실제 기사 스냅샷에도 별도의
결정적 ULID 네임스페이스를 사용합니다.

각 기사에는 OpenAI GPT가 원문 본문만 보고 평가한 `편향성(-100~100)`과
`과장성(0~100)` 결과가 포함됩니다. 모델명, 프롬프트 버전, 신뢰도, 근거와
처리량도 함께 저장하며 평가가 하나라도 빠진 스냅샷은 적재를 거부합니다.
과거 DB 호환에 필요한 `y`, `z` 물리 필드는 0으로만 기록되고 분석 기준으로
사용되지 않습니다.

실행 방법:

```sh
uv run python -m db.seeds.analyze_articles  # 새 기사 추가 후 LLM 평가 생성
uv run python -m db.seeds.seed --dry-run
uv run python -m db.seeds.seed
```

스냅샷에는 계정, OAuth 주체, 토큰, 설문 응답, 비공개 URL, 비밀 값이 없어야
합니다. 기사 추가 시 직접 원문 HTTPS URL, 한국어 원문 제목과 본문, 시간대가
포함된 ISO 8601 발행일을 반드시 검증해야 합니다.

Phase 1·2 대표 사건과 검수된 비교 snapshot은 이 기존 카테고리 seed와 분리된 `demo_showcase.json` 및
`demo_showcase.py`로 관리한다. 운영 백업, 정책 검수, 멱등 refresh, trust audit,
rollback 절차는 [DEMO_SHOWCASE_RUNBOOK.md](./DEMO_SHOWCASE_RUNBOOK.md)를 따른다.

## 기존 운영 데이터 파이프라인 복구

일반 시드 교체와 분리된 복구 모드는 기존 계정·기사·평가 기록을 삭제하지 않는다. 먼저
같은 세대로 dry-run을 실행해 출처별 기사/본문/신뢰 가능한 OpenAI 평가/공개 가능한 활성
점수와 큐 상태를 확인한다.

```sh
./.ops/run.sh seed --repair-pipeline --generation 2026-08-27-r1 --dry-run
./.ops/run.sh seed --repair-pipeline --generation 2026-08-27-r1
```

복구는 한 DB 트랜잭션에서 다음 작업만 수행한다.

- 잘못되거나 비어 있는 `articles.current_version_id`를 해당 기사의 최신 버전으로 연결한다.
- 신뢰 가능한 OpenAI 평가와 provenance가 일치하는 `draft` 점수만 `active`로 승격한다.
  기존 `active` 점수는 변경하거나 삭제하지 않는다.
- 본문은 있지만 신뢰 평가가 없는 버전은 `analyze`, 평가가 있지만 공개 가능한 점수가
  없는 버전은 `calculate_score` 작업을 재큐잉한다.
- 본문/버전이 없는 출처는 승인 상태와 활성 adapter를 확인한 뒤 제한된 `crawl` 작업을
  큐에 넣는다. 정책이 승인되지 않은 CRAWLER 출처는 절대 실행하지 않는다.
- 검수된 공식 RSS는 정치면 한 곳이 아니라 뉴시스 속보·이투데이 전체뉴스처럼 대주제를
  포괄하는 feed를 사용한다. scheduled RSS는 제목·원문 URL·발행시각·feed 제공 요약만
  수집하며 링크된 기사 페이지를 다시 크롤링하지 않는다.
- `--bootstrap-news-sources`를 명시하면 행정안전부·중소벤처기업부·농림축산식품부·
  국가데이터처·관세청의 공식 보도자료 RSS 출처와 adapter를 멱등 등록한다. 이 옵션은
  기존 자동 클러스터가 만든 공개 불가 candidate TOPIC도 삭제 대신 archive 처리한다.

공식 RSS 출처 확장과 즉시 재수집은 반드시 dry-run을 먼저 확인한 뒤 새 세대로 실행한다.

```sh
./.ops/run.sh seed --repair-pipeline --bootstrap-news-sources \
  --generation 2026-08-28-news-v1 --dry-run
./.ops/run.sh seed --repair-pipeline --bootstrap-news-sources \
  --generation 2026-08-28-news-v1
```

모든 새 작업 dedupe key에는 명시한 generation이 들어간다. 같은 generation 재실행은
중복 작업을 만들지 않는다. 작업이 `SUCCEEDED`했지만 기대 데이터가 여전히 없다면 새
generation으로 다시 진단·복구한다. 실제 변경 실행은 요약과 함께
`PIPELINE_RECOVERY_APPLIED` audit log를 남긴다.
