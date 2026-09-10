# 뉴스 출처 커버리지 QA 근거

검증일은 2026-09-10이다. 이 문서는 요청된 10개 언론사의 공식 피드 또는 공식 뉴스
사이트맵의 기술 검증과 사용자가 승인한 운영 적용 범위를 기록한다.

HTTP 200과 XML 해석 성공은 기술적으로 기사 목록을 발견할 수 있다는 근거다. 별도 언론사 이용 허가가 발급됐다는 근거는 아니다. 기본 카탈로그에서
운영자 검토가 끝나지 않은 출처는 `PENDING`으로 등록되고,
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
  apps/api/tests/test_source_feed_endpoints_live.py -s -q
```

검증 당시 모든 출처가 위 표와 같이 200을 반환했고 각 8개 항목의 제목과 허용 도메인 URL을
해석했다. 이 결과는 시점 의존적이므로 배포 전과 장애 조사 때 같은 테스트를 다시 실행한다.

## 운영자 승인과 적용

2026-09-10 사용자가 QA 해소를 위한 모든 작업을 승인했다. 이 승인을 Effica 운영자의
수집 정책 결정으로 기록하고 요청된 10개 출처의 `policy_status`, `robots_status`,
`terms_status`를 `APPROVED`로 적용했다. 이는 언론사가 별도 이용 허가서나 계약을
발급했다는 주장이 아니다. 각 어댑터의 `operator_review`에 승인 근거와 범위를 기록했다.

승인 범위는 공식 RSS 또는 뉴스 사이트맵의 제한된 수집, 원문 링크, 같은 언론사 도메인의
공개 기사 본문 확보와 내부 분석이다. 인증이나 유료 접근 제한을 우회하지 않는다.
현재 robots 파일과 표본 피드 및 기사 경로는 `perspective-news-worker/1.0` 접근을 허용했다.
런타임은 저장된 robots 검토 상태를 사용하므로 운영자는 정책 변경 시 이를 다시 검토한다.

신규 환경의 기본 부트스트랩은 이투데이를 제외한 출처를 계속 `PENDING`으로 만든다.
이번 운영 승인 기록을 다른 설치나 향후 이용 범위에 자동으로 확대하지 않는다.

## 운영 절차와 검증

아래 순서로 운영 DB에 적용했다. 동일 generation을 사용해 작업 중복을 방지했다.

```sh
./.ops/run.sh seed --repair-pipeline --bootstrap-news-sources \
  --dry-run --generation source-coverage-20260910
./.ops/run.sh seed --repair-pipeline --bootstrap-news-sources \
  --generation source-coverage-20260910
```

출처 등록 후 관리자 저장소의 버전 검사 및 멱등성 처리 경로로 운영자 승인을 적용하고,
같은 명령을 다시 실행해 RSS 어댑터와 수집 작업을 생성했다. 10개 출처에 승인 상태와
활성 RSS 어댑터가 있음을 읽어 확인했다. 기사 분석량 제한과 이미 제출한 LLM 요청의
재실행 방지 정책은 유지했다.

조선일보는 기사 URL 끝의 `/`를 HTTP 요청에서도 지워 정상 리다이렉트가 반복되는 문제가
있었다. 요청 경로에서는 이 문자를 보존하고 저장용 기사 식별 URL만 정규화하도록 수정했다.
실제 worker를 이용한 조선일보 본문 확보 검사도 통과했다. 오마이뉴스의 정상 하위 도메인을
거부하던 실시간 검사의 호스트 비교도 DNS 라벨 경계로 수정했다.

운영 수집 결과는 최종 [QA 기록](qa-resolution-20260910.md)에 기록한다.
피드 해석 성공과 기사 수집 성공, AI 분석 완료는 서로 다른 단계로 확인한다.
