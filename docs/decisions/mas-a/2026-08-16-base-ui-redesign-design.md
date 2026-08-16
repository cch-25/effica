# Base UI 전면 리디자인 설계

작성일: 2026-08-16  
대상: `apps/web` 사용자·관리자 웹 전체

## 1. 목표

현재 자체 구현 UI와 색 중심 표현을 Base UI React primitive 기반의 흑백 인터페이스로 전면 교체한다. 기존 사용자 여정, 관리자 기능, 반응형 동작과 접근성 요구사항은 유지한다.

완료된 화면은 Base UI 공식 CSS Modules 예제와 같은 절제된 톤을 사용한다. 배경은 흰색이며 검정, 흰색, 중립 회색만 허용한다. 성공, 경고, 오류, OAuth 제공자, 정치 좌표, 데이터 유형에도 유채색을 사용하지 않는다.

## 2. 구현 전략

선택한 접근은 전면 Primitive 교체다.

1. `@base-ui/react`를 `apps/web`의 직접 의존성으로 추가한다.
2. 공용 UI 컴포넌트를 Base UI primitive로 재구현한다.
3. 기능 컴포넌트에 남아 있는 네이티브 상호작용 요소를 Base UI 기반 공용 컴포넌트로 교체한다.
4. Base UI에 직접 대응하지 않는 카드, 표, 페이지 레이아웃은 시맨틱 HTML을 유지하고 동일한 흑백 토큰과 공식 예제의 CSS 문법으로 다시 스타일링한다.
5. 기능·상태 모델과 API 코드는 변경하지 않는다.

공용 래퍼의 외부 API는 기능 회귀를 줄일 수 있을 때 유지한다. 다만 Base UI의 상태 모델이나 접근성 구조를 방해하는 래퍼는 명확한 composition API로 교체한다.

## 3. 시각 언어

### 색과 표면

- 페이지, 사이드바, 카드, 팝업의 기본 배경은 `#fff`다.
- 전경은 `#000`과 중립 회색 단계만 사용한다.
- 활성 상태는 검정 채움, 비활성 상태는 흰 채움과 회색 테두리로 구분한다.
- 유채색 변수, 그라디언트, 컬러 그림자, 컬러 선택 영역, 장식용 광원과 발광 효과를 제거한다.
- 그림자는 팝업의 레이어 구분에 필요한 낮은 강도의 중립 회색만 사용한다.

### 형태와 타이포그래피

- Base UI 예제와 유사한 작은 모서리 반경, 1px 경계선, 촘촘하고 일관된 컨트롤 높이를 사용한다.
- 본문과 제목은 현대적인 sans-serif 계열로 통일하고 크기, 굵기, 여백으로 위계를 만든다.
- 장식용 serif 제목, 원형 궤도, 대형 컬러 배너를 제거한다.
- 수치와 표 데이터는 tabular figures를 사용한다.

### 상태 표현

색을 상태의 유일하거나 보조적인 단서로도 사용하지 않는다.

- 성공: 체크 아이콘, `완료` 문구, 실선 테두리
- 경고·처리 중: 삼각형 또는 시계 아이콘, 상태 문구, 점선 테두리
- 오류·차단: 원형 느낌표 또는 X 아이콘, 직접적인 오류 문구, 굵은 테두리
- 비활성: 낮은 대비와 비활성 커서, `disabled` 속성
- 포커스: 검은색 이중 outline 또는 outline과 offset 조합

## 4. Base UI 컴포넌트 매핑

| 현재 구현 | 교체 대상 |
| --- | --- |
| 자체 `Button`과 버튼 모양 링크 | Base UI `Button`; 링크는 링크 의미를 유지하고 같은 CSS recipe 적용 |
| 네이티브 `<dialog>` | Base UI `Dialog` |
| 자체 고정 드로어 | Base UI `Drawer`와 `ScrollArea` |
| 자체 탭과 화면 내 수제 tablist | Base UI `Tabs`와 `Tabs.Indicator` |
| 고정 `<div role="status">` 토스트 | 전역 Base UI `Toast.Provider`, `Viewport`, `Root` |
| 네이티브 체크박스 | Base UI `Checkbox`, 필요 시 `CheckboxGroup` |
| 네이티브 라디오 설문 | Base UI `Radio`와 `RadioGroup` |
| 네이티브 `<select>` | Base UI `Select` |
| 네이티브 range | Base UI `Slider` |
| 숫자 입력 | Base UI `NumberField` |
| 텍스트 입력, textarea, 레이블, 오류 문구 | Base UI `Field`, `Input`; textarea는 `Field.Control render={<textarea />}` composition |
| 검색·필터·시각화 버튼 묶음 | Base UI `Toolbar`, 필요 시 `Menu` |
| 프로필·행 단위 동작 메뉴 | Base UI `Menu` |
| 아이콘 전용 버튼 설명 | Base UI `Tooltip` |
| 구분선 | Base UI `Separator` |
| 진행률·신뢰도·측정값 | 의미에 따라 Base UI `Progress` 또는 `Meter` |
| 로딩 | 기존 시맨틱 Skeleton 유지, 흑백 shimmer와 reduced-motion 적용 |
| 카드·표·배지·빈 상태 | 시맨틱 HTML 유지, Base UI 문서 톤의 공용 CSS recipe 적용 |

## 5. 애플리케이션 구조

### 전역 구성

- 앱 루트에 Base UI 포털이 콘텐츠 위에 안정적으로 표시되도록 격리 stacking context를 추가한다.
- iOS 26+ Safari의 backdrop 동작을 위해 공식 권장 `body { position: relative; }`를 반영한다.
- 전역 Toast provider와 viewport를 `providers.tsx`에 둔다.
- 전역 CSS에는 흑백 토큰, 문서 레이아웃, 시맨틱 카드·표 recipe만 둔다.
- 상호작용 컴포넌트의 구조와 상태 selector는 컴포넌트별 CSS Module에 둔다.

### 공용 UI 계층

`src/components/ui`는 Base UI primitive를 앱에서 일관되게 사용하는 얇은 adapter 계층이 된다. 각 adapter는 접근 가능한 이름, disabled 상태, 포커스, 키보드 사용과 popup portal을 보존한다.

### 기능 계층

기능 컴포넌트는 도메인 상태를 소유하고 공용 UI adapter에 value와 callback을 전달한다. Base UI 도입을 이유로 API 타입, mock fixture, 권한 검사, 투표 검증 또는 공유 카드 상태 전이를 변경하지 않는다.

## 6. 화면별 변화

### 앱 셸과 탐색

- 어두운 고정 사이드바를 흰 사이드바와 오른쪽 회색 경계선으로 바꾼다.
- 활성 경로는 검은 전경·밑줄 또는 검은 채움으로 명확히 표시한다.
- 모바일 하단 탐색도 흰 배경과 상단 경계선을 사용한다.
- 프로필 영역은 Base UI Menu trigger가 되며 관리자·사용자 이동을 제공한다.

### 홈, 이슈, 기사

- 녹색 feature banner와 궤도 장식을 제거하고 정보 중심의 흰색 editorial header로 교체한다.
- 추천 이유와 상태 배지는 모두 회색조 label로 표시한다.
- 축, 신뢰도, 기사 비교는 구획선·타이포그래피·패턴으로 구분한다.

### 로그인과 온보딩

- OAuth 제공자 브랜드색을 제거하고 제공자 이름과 흑백 아이콘만 사용한다.
- 동의는 Base UI Checkbox, 설문은 RadioGroup, 인구통계는 Select를 사용한다.
- 검증 오류는 Field.Error와 상태 아이콘·문구로 연결한다.

### 투표, 진행도, 효능감

- 투표는 Base UI Slider와 NumberField를 한 필드로 묶는다.
- 크레딧과 효능감은 색 없는 Meter·Progress 및 표로 표시한다.
- 저장·삭제 결과는 전역 Base UI Toast로 알린다.

### 시각화

- 3D 포인트는 기사=흰 구체+검은 외곽선, 언론사=검은 구체, 사용자=회색 구체+선 패턴으로 구분한다.
- 2D 포인트는 기사=원, 언론사=사각형, 사용자=마름모로 구분한다.
- 범례에는 도형과 텍스트를 함께 제공한다.
- 선택 상태는 크기와 외곽선 두께로 표시한다.
- 2D·표 fallback과 drag, zoom, reset 기능은 유지한다.

### 공유 카드

- 컬러 궤도형 미리보기를 흑백 좌표 카드로 재설계한다.
- 템플릿 선택은 Base UI Select, 공개 동의는 Checkbox를 사용한다.
- 폐기는 다른 버튼과 동일한 무채색이지만 X 아이콘, `즉시 폐기` 문구, 확인 Dialog로 위험성을 전달한다.

### 관리자

- 검색은 Field와 Input, 상태 필터와 행 동작은 Menu, 액션 묶음은 Toolbar를 사용한다.
- 변경 확인은 Base UI Dialog를 사용하며 사유 필드와 idempotency key를 명확히 구획한다.
- 권한 부족과 version conflict는 색이 아닌 잠금·충돌 아이콘과 문구로 표시한다.

## 7. 데이터 흐름과 상태

도메인 데이터 흐름은 유지한다.

1. 페이지와 feature가 fixture 또는 API client에서 데이터를 받는다.
2. feature가 도메인 상태와 검증을 관리한다.
3. Base UI adapter는 controlled 또는 uncontrolled primitive 상태를 화면 상호작용으로 변환한다.
4. 저장·삭제·관리자 변경 결과는 공용 Toast manager에 메시지를 추가한다.
5. dialog, drawer, select, menu는 Base UI portal을 통해 렌더링한다.

기존 UI의 로컬 `message` 상태는 가능한 범위에서 toast manager 호출로 축소한다. 비동기 요청 실패는 기존 error mapping을 사용하며 입력 주변에는 Field.Error, 화면 수준에는 StatePanel을 표시한다.

## 8. 접근성과 반응형

- WCAG 2.2 AA 수준의 대비를 회색조 안에서 충족한다.
- 색상에 의존하지 않고 아이콘, 도형, 패턴, 텍스트를 중복 단서로 제공한다.
- 모든 popup과 form control은 Base UI의 키보드 상호작용과 focus management를 사용한다.
- 아이콘 전용 버튼에는 접근 가능한 이름과 Tooltip을 제공한다.
- 모션은 transform과 opacity만 사용하고 `prefers-reduced-motion`에서 shimmer와 전환을 중지한다.
- 2열·4열 그리드는 좁은 화면에서 한 열로 축소하고 popup은 viewport 안에서 스크롤 가능하게 한다.

## 9. 오류와 예외 처리

- loading, empty, partial, stale, unauthorized, consent-required, conflict, fatal 상태를 흑백 StatePanel recipe로 표현한다.
- popup의 바깥 클릭, Escape, focus return은 Base UI에 위임한다.
- WebGL을 사용할 수 없으면 기존과 같이 2D 투영으로 전환하고 그 이유를 텍스트로 표시한다.
- destructive action은 확인 Dialog를 거치고 사유가 필요한 관리자 작업은 빈 입력 상태에서 실행할 수 없다.
- CSS가 로드되지 않아도 DOM 순서와 시맨틱 요소만으로 핵심 흐름을 이해할 수 있어야 한다.

## 10. 검증 계획

### 정적 검증

- TypeScript typecheck
- ESLint
- 유채색 hex, rgb, hsl, named color와 gradient 사용 여부를 소스 검색으로 검사
- 네이티브 `dialog`, `select`, checkbox, radio, range와 수제 `role="tab"` 잔존 여부를 검사

### 자동 테스트

- 기존 unit·component 테스트
- 핵심 경로 접근성 Playwright 테스트
- 사용자 여정과 관리자 여정 E2E
- WebGL 비활성화 fallback
- 키보드로 Dialog, Drawer, Select, Menu, Tabs, Slider, Radio, Checkbox 조작

### 시각 검증

- 홈, 로그인, 온보딩, 기사, 시각화, 공유 카드, 관리자 화면을 데스크톱과 모바일에서 확인한다.
- 모든 화면에서 흰 배경과 회색조만 보이는지 확인한다.
- popup layering, 긴 한국어 문구, 빈 상태, 오류 상태와 가로 스크롤 표를 확인한다.

## 11. 범위 제외

- API 계약, mock 데이터 내용, 인증 정책, 권한 정책 변경
- 새로운 사용자 기능 추가
- `apps/web` 밖의 구현 파일 수정
- Base UI가 아닌 별도 디자인 시스템 또는 pre-styled UI 라이브러리 도입
