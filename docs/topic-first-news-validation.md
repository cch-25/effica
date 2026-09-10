# 이슈 중심 수집 검증 기록

검증일: 2026-09-10

요구사항: [이슈 중심 뉴스 수집 요구사항](topic-first-news-requirements.md)

| 검사 | 실행 | 결과 |
| --- | --- | --- |
| 서버 전체 | `.ops/run.sh test` | 402 통과, 2 건너뜀 |
| 프런트 전체 | `.ops/run.sh test-web` | 93 통과 |
| 브라우저 | `.ops/run.sh test-browser e2e --grep "today's issues\|home, issue comparison"` | 데스크톱과 모바일 총 4 통과 |
| 정적 검사 | `.ops/run.sh verify` | Python Ruff, ESLint, TypeScript 통과 |
| 프로덕션 빌드 | `.ops/run.sh build-web` | 통과 |
| API 계약 | `.ops/run.sh openapi` | 84 operation 일치 |
| 변경 형식 | `git diff --check` | 통과 |

서버 검증에는 실제 HTML 파서를 사용한 HTTP mock transport 기반 검색 경로가 포함된다. 날짜별 작업 중복, 검색 근거에 없는 URL, 언론사 중복과 수집 승인 상태 및 원문 발행일을 검사한다. 원문이 바뀐 요청의 유료 재시도와 검색 요약을 기사 본문으로 저장하는 경로를 차단하는 회귀 검증도 포함한다.

저장 검증은 이슈별 기사 소속, 전체 소속 기사 분석 예약과 최대 5개 발행을 확인한다. 실패 또는 빈 결과에서는 이전 이슈를 새 데이터인 것처럼 갱신하지 않는다. 공개 API에서는 현재 기사 버전이 없거나 출처가 부족한 이슈가 추천, 상세와 분석 상태에 나타나지 않는지 확인한다.

`v2-fan`으로 화면, 공개 API, 검색 provider와 저장 회귀 검증을 나누어 구현한 뒤 루트 작업에서 통합했다. 중단된 작업은 저장된 코드를 이어받아 검증을 완료했다. 미완료 구현 작업은 없다.

운영 DB 마이그레이션과 배포는 실행하지 않았다. 유료 검색 API를 호출하지 않았으며 운영 환경에서 이슈 3~5개가 실제 발행되었다고 확인하지 않았다. 운영 적용에는 `0022_issue_discovery_budget` 마이그레이션과 API 및 워커 배포, 유효한 검색 API 설정, 서로 다른 언론사 3곳 이상의 유효한 원문 수집 승인이 필요하다. 원문 접근 제한이나 출처 부족은 작업 결과의 거절 이유로 확인한다.

상세 로그는 Git에서 제외된 `output/topic-first-*` 파일에 보관한다.
