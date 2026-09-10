# 뉴스 출처 커버리지 QA 근거

검증일은 2026-09-10이다. 이 문서는 요청된 10개 언론사의 공식 피드 또는 공식 뉴스
사이트맵이 실제로 열리고 현재 수집 어댑터로 해석되는지와, 운영 수집을 켜기 전에 남은
이용 조건 검토를 구분해서 기록한다.

HTTP 200과 XML 해석 성공은 기술적으로 기사 목록을 발견할 수 있다는 근거다. 기사 본문을
저장하거나 분석하고 서비스 사용자에게 제공해도 된다는 허가 근거는 아니다. 코드도 이
경계를 그대로 지킨다. 이용 조건 검토가 끝나지 않은 출처는 `PENDING`으로 등록되고,
`policy_status`, `robots_status`, `terms_status`가 모두 `APPROVED`가 되기 전에는 어댑터와
크롤 작업을 자동 생성하지 않는다.

## 실시간 기술 검증

아래 결과는 공식 URL에서 최대 8개 항목을 받아 `RSSAdapter`로 해석한 결과다. RSS 종료나
부재가 확인된 문화일보, 세계일보, 중앙일보에는 해당 사이트의 공식 `robots.txt`가 공개한
Google News 사이트맵을 사용한다. 사이트맵 항목의 본문은 비워 두며, 승인 후 기존의
정책 검사를 거쳐 기사 URL에서 본문을 가져온다.

| 출처 | 공식 발견 URL | 형식 | HTTP | 해석 항목 | 기술 판정 |
| --- | --- | --- | ---: | ---: | --- |
| 뉴시스 | https://nwww.newsis.com/RSS/sokbo.xml | RSS | 200 | 8 | 사용 가능 |
| 이투데이 | https://rss.etoday.co.kr/eto/etoday_news_all.xml | RSS | 200 | 8 | 사용 가능 |
| 조선일보 | https://www.chosun.com/arc/outboundfeeds/rss/?outputType=xml | RSS | 200 | 8 | 사용 가능 |
| 문화일보 | https://www.munhwa.com/sitemap/latest-articles | Google News 사이트맵 | 200 | 8 | 사용 가능 |
| 세계일보 | https://www.segye.com/sitemap_day0.xml | Google News 사이트맵 | 200 | 8 | 사용 가능 |
| 경향신문 | https://www.khan.co.kr/rss/rssdata/total_news.xml | RSS | 200 | 8 | 사용 가능 |
| 한겨레 | https://www.hani.co.kr/rss/ | RSS | 200 | 8 | 사용 가능 |
| 오마이뉴스 | https://rss.ohmynews.com/rss/ohmynews.xml | RSS | 200 | 8 | 사용 가능 |
| 동아일보 | https://rss.donga.com/total.xml | RSS | 200 | 8 | 사용 가능 |
| 중앙일보 | https://www.joongang.co.kr/sitemap/latest-articles | Google News 사이트맵 | 200 | 8 | 사용 가능 |

재현 명령은 다음과 같다. 이 테스트는 명시적으로 환경 변수를 지정했을 때만 외부 네트워크를
사용한다.

```sh
EFFICA_RUN_LIVE_SOURCE_FEEDS=1 ./.ops/run.sh test \
  server/apps/api/tests/test_source_feed_endpoints_live.py -s -q
```

검증 당시 모든 출처가 위 표와 같이 200을 반환했고 각 8개 항목의 제목과 허용 도메인 URL을
해석했다. 이 결과는 시점 의존적이므로 배포 전과 장애 조사 때 같은 테스트를 다시 실행한다.

## 이용 조건 검토 판정

신규 부트스트랩에서 자동 승인되는 언론사는 이투데이 한 곳이다. 나머지 9개는 공식 피드가
열려 있어도 현재 확인한 공개 문서만으로 Effica의 다중 사용자 기사 저장, 분석, 재제공 범위가
허용된다고 단정할 수 없어 검토가 필요하다.

| 출처 | 신규 상태 | 공식 근거 | 운영 전 필요한 조치 |
| --- | --- | --- | --- |
| 뉴시스 | `PENDING` | [저작권 정책](https://nwww.newsis.com/contents/copyright)은 비영리 정보 서비스도 사전 서면 허가 대상으로 안내한다. | Effica의 저장, 분석, 노출 범위를 명시한 서면 허가 또는 계약을 확보한다. `demo_showcase.json`은 `PENDING`으로 바로잡았다. 기존 DB가 `APPROVED`이면 근거를 확인하고, 근거가 없으면 별도로 `PENDING`으로 수정한다. |
| 이투데이 | `APPROVED` | [공식 RSS 안내](https://www.etoday.co.kr/rss/)는 비상업 목적 이용을 허용한다. | 현재 서비스가 비상업 범위를 유지하는지 운영자가 확인한다. 수익화하거나 재배포 범위가 바뀌면 다시 검토한다. |
| 조선일보 | `PENDING` | [조선닷컴 RSS 안내](https://rssplus.chosun.com/)는 개인 이용 범위를 중심으로 설명하고 상업적 이용은 별도 문의 대상으로 둔다. | 다중 사용자 서비스의 저장, 분석, 노출 범위를 서면으로 확인한다. |
| 문화일보 | `PENDING` | [공식 robots.txt](https://www.munhwa.com/robots.txt)가 최신 기사 사이트맵을 공개해 기술적 발견 경로는 확인된다. 공개 사이트맵 자체는 재이용 허가가 아니다. | RSS 또는 사이트맵 항목과 기사 본문의 서비스 이용 허가를 별도로 확인한다. |
| 세계일보 | `PENDING` | [공식 robots.txt](https://www.segye.com/robots.txt)가 사이트맵 인덱스를 공개한다. 기존 `rss.segye.com` 최근기사 RSS는 검증 당시 502였다. | 뉴스 사이트맵과 기사 본문의 서비스 이용 허가를 별도로 확인한다. |
| 경향신문 | `PENDING` | [공식 RSS 도움말](https://www.khan.co.kr/help/help_rss.html)은 개인 구독을 설명하며 공유, 복수 사용자 이용, 영리 이용은 허가 대상으로 안내한다. | Effica의 다중 사용자 이용 범위에 대한 허가를 확보한다. |
| 한겨레 | `PENDING` | [한겨레 저작권 이용 안내](https://company.hani.co.kr/media.html)는 신청, 사용료, 승인 절차를 안내한다. | 기사 텍스트 저장과 분석, 결과 노출 범위를 신청해 승인받는다. |
| 오마이뉴스 | `PENDING` | [공식 RSS 안내](https://www.ohmynews.com/NWS_Web/Help/srv/h_help_rss.aspx)는 개인 이용을 전제로 하며 재배포와 재 RSS 제공을 제한한다. | 서비스 사용 허가 또는 계약을 확보한다. |
| 동아일보 | `PENDING` | [공식 RSS 안내](https://rss.donga.com/)는 개인의 비상업 이용 범위를 설명하고 복수 사용자 또는 상업 이용은 문의 대상으로 둔다. | Effica의 다중 사용자 이용 범위에 대한 허가를 확보한다. |
| 중앙일보 | `PENDING` | [공식 robots.txt](https://www.joongang.co.kr/robots.txt)가 최신 기사 사이트맵을 공개한다. 과거 `rss.joins.com` RSS는 서비스 종료 안내 HTML을 반환했다. | 뉴스 사이트맵과 기사 본문의 서비스 이용 허가를 별도로 확인한다. |

위 판정은 언론사의 정치적 성향을 판단하거나 라벨링하지 않는다. 출처 카탈로그에는 기술적
연결 정보와 이용 조건 검토 상태만 저장한다.

## 안전한 등록과 승인 절차

### 1. 변경 없는 사전 확인

배포 대상 코드와 같은 환경에서 먼저 드라이런을 실행한다. `--bootstrap-news-sources`는
`--repair-pipeline`과 함께 써야 한다. `--generation`은 재실행 시 같은 값을 유지하면 복구
작업의 dedupe 세대가 고정된다.

```sh
./.ops/run.sh seed \
  --repair-pipeline \
  --bootstrap-news-sources \
  --dry-run \
  --generation source-coverage-20260910
```

JSON 보고서에서 10개 출처가 모두 보이는지 확인한다. 이투데이를 제외한 9개 출처는
`REVIEW_REQUIRED`와 `PENDING`이어야 한다. 드라이런에서는 DB를 변경하지 않는다.

### 2. 출처 행 등록

DB 백업과 배포 revision 확인을 마친 뒤에만 드라이런에서 `--dry-run`을 빼고 실행한다.
이 단계는 출처 행을 등록한다. 신규 이투데이에는 승인된 RSS 어댑터와 크롤 작업을 만들 수
있지만, 검토 중인 9개 출처에는 어댑터나 크롤 작업을 만들지 않는다.

```sh
./.ops/run.sh seed \
  --repair-pipeline \
  --bootstrap-news-sources \
  --generation source-coverage-20260910
```

기존 DB 상태는 부트스트랩이 덮어쓰지 않는다. 따라서 기존 뉴시스가 `APPROVED`라면 별도
확인이 필요하다. 서면 허가 근거가 없으면 아래 관리자 변경 절차로 세 상태를 `PENDING`으로
수정한 뒤 복구를 다시 실행한다.

대표 데이터 manifest도 뉴시스 세 기사의 정책 상태를 `PENDING`으로 유지한다. 이 상태에서
`demo-refresh`는 의도적으로 적용을 거부한다. 이미 운영 중인 대표 데이터를 이 변경만으로
삭제하거나 덮어쓰지는 않지만, 새 환경에서 대표 데이터를 다시 만들려면 뉴시스 서면 허가를
확보하거나 각 사건의 최소 2개 언론사 조건을 충족하는 승인된 대체 출처를 manifest에 넣어야
한다. 공개 대표 화면을 유지한다는 이유로 확인되지 않은 권한을 `APPROVED`로 바꾸지 않는다.

### 3. 사람 검토와 승인 기록

승인 판단은 다음 세 항목을 각각 확인한다.

1. `policy_status`: 저작권 정책이나 계약이 실제 저장, 분석, 노출 범위를 허용하는가
2. `robots_status`: 피드, 사이트맵, 기사 URL 접근이 현재 robots 정책에 부합하는가
3. `terms_status`: 서비스 약관과 별도 계약이 자동 처리와 다중 사용자 제공을 허용하는가

허가서 또는 계약 식별자, 공식 정책 URL, 허용 범위, 검토자 ID, 검토일을 변경 사유에 남긴다.
공개 문서가 모호하거나 개인 이용만 허용하면 `PENDING`을 유지한다. 명시적으로 금지되고
별도 허가도 없으면 `REJECTED`로 기록한다.

승인 변경은 인증된 ADMIN 세션으로 다음 API를 사용한다.

1. `GET /api/v1/admin/sources`에서 대상의 `id`와 현재 `version`을 읽는다.
2. `PATCH /api/v1/admin/sources/{source_id}`를 호출한다.
3. `If-Match`에는 현재 `version`을 넣는다.
4. 요청마다 고유한 `Idempotency-Key`를 넣고 세션의 CSRF 값을 `X-CSRF-Token`으로 보낸다.

요청 본문 예시는 다음과 같다. 실제 근거를 확보한 출처에만 사용한다.

```json
{
  "values": {
    "policy_status": "APPROVED",
    "robots_status": "APPROVED",
    "terms_status": "APPROVED",
    "active": true
  },
  "reason": "reviewed_by=<operator-id>; reviewed_at=<ISO-8601>; scope=<approved-use>; evidence=<official-policy-or-contract-reference>"
}
```

세 상태를 한 번에 승인할 근거가 없으면 확인된 상태만 변경하고 나머지는 `PENDING`으로
둔다. 크롤은 세 상태가 모두 `APPROVED`일 때만 허용된다.

### 4. 승인 후 어댑터와 작업 생성

승인 API가 성공한 뒤 같은 generation으로 복구를 다시 실행한다.

```sh
./.ops/run.sh seed \
  --repair-pipeline \
  --bootstrap-news-sources \
  --generation source-coverage-20260910
```

보고서에서 해당 출처의 RSS 어댑터 생성과 크롤 작업 enqueue를 확인한다. 이후
`GET /api/v1/admin/sources/{source_id}`로 세 상태와 `active` 값을 다시 읽고, 수집 결과에서
기사 URL의 도메인과 출처 매핑을 확인한다.

## 현재 결론

10개 언론사의 기술적 발견 경로와 파서는 준비됐다. 신규 환경에서 바로 운영 수집까지 켤 수
있는 출처는 현재 공개 근거상 이투데이 한 곳이다. 뉴시스를 포함한 나머지 9개 출처는 위 표의
근거와 조치가 끝날 때까지 카탈로그에는 등록되지만 공개 수집과 분석은 시작되지 않는다.
