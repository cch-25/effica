# Base UI 전면 리디자인 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `apps/web`의 자체·네이티브 상호작용 컴포넌트를 Base UI React primitive로 전면 교체하고, 모든 사용자·관리자 화면을 흰 배경의 무채색 UI로 통일한다.

**Architecture:** `@base-ui/react@1.7.0`을 공용 UI adapter 계층에서 조합하고 기능 컴포넌트는 해당 adapter에 도메인 상태만 전달한다. Base UI에 직접 대응하지 않는 카드·표·레이아웃은 시맨틱 HTML과 전역 흑백 recipe를 유지하며, popup과 form control의 구조·상태 스타일은 CSS Modules로 캡슐화한다.

**Tech Stack:** Next.js 16.3.1 App Router, React 19.2.8, TypeScript 5.9, Base UI React 1.7.0, CSS Modules, Vitest, Testing Library, Playwright, axe-core, React Three Fiber

## Global Constraints

- 수정 범위는 `apps/web/**`와 `docs/decisions/mas-a/**`로 제한한다.
- 페이지, 사이드바, 카드, popup의 기본 배경은 `#fff`다.
- 검정, 흰색, 중립 회색만 허용하며 유채색 hex, rgb, hsl, named color를 금지한다.
- 성공, 경고, 오류, OAuth 제공자, 정치 좌표, 2D·3D 데이터 유형에도 유채색을 사용하지 않는다.
- 상태는 아이콘, 문구, 선의 굵기·패턴, 도형으로 구분한다.
- 기존 API 타입, mock fixture, 인증 정책, 권한 정책, 사용자 여정과 관리자 동작을 변경하지 않는다.
- Base UI 외의 pre-styled UI 라이브러리를 추가하지 않는다.
- WCAG 2.2 AA, 키보드 조작, focus visibility, reduced motion, WebGL 2D·표 fallback을 유지한다.
- Base UI 공식 문서의 CSS Modules 예제와 같은 작은 반경, 1px 중립 경계선, 검은 활성 상태, 간결한 sans-serif 톤을 사용한다.

---

## File Structure

### 새 파일

- `apps/web/src/components/ui/primitives.module.css`: Button, Badge, StatePanel, Skeleton의 공용 무채색 recipe.
- `apps/web/src/components/ui/overlays.module.css`: Dialog, Drawer, Toast, Menu, Tooltip과 portal의 상태 스타일.
- `apps/web/src/components/ui/forms.module.css`: Field, Input, Checkbox, Radio, Select, Slider, NumberField의 상태 스타일.
- `apps/web/src/components/ui/navigation.module.css`: Tabs, Toolbar, Menu trigger의 상태 스타일.
- `apps/web/src/components/ui/checkbox-field.tsx`: Base UI Checkbox와 Field.Item 조합.
- `apps/web/src/components/ui/radio-scale.tsx`: Base UI RadioGroup과 Radio 조합.
- `apps/web/src/components/ui/select-field.tsx`: Base UI Select와 Field 조합.
- `apps/web/src/components/ui/text-field.tsx`: Base UI Field.Control/Input/textarea 조합.
- `apps/web/src/components/ui/toolbar.tsx`: Base UI Toolbar adapter.
- `apps/web/tests/component/base-primitives.test.tsx`: Button, Dialog, Drawer, Tabs, Toast의 동작 검증.
- `apps/web/tests/component/base-form-controls.test.tsx`: Checkbox, Radio, Select, Slider, NumberField의 form·keyboard 동작 검증.
- `apps/web/tests/unit/monochrome-ui.test.ts`: UI 소스의 유채색·gradient·금지된 네이티브 컨트롤 잔존 검사.

### 주요 수정 파일

- `apps/web/package.json`, `apps/web/package-lock.json`: Base UI 1.7.0 의존성.
- `apps/web/src/app/layout.tsx`, `apps/web/src/app/providers.tsx`, `apps/web/src/app/globals.css`: portal root, Toast provider, 흑백 토큰과 전체 레이아웃.
- `apps/web/src/components/ui/*.tsx`: 기존 공용 UI의 Base UI 기반 재구현.
- `apps/web/src/components/layout/*.tsx`: 흰색 앱 셸, Base UI Menu 기반 프로필, 페이지 헤더.
- `apps/web/src/features/**/*.tsx`: 네이티브 컨트롤과 수제 상호작용 제거.
- `apps/web/src/app/**/*.tsx`: 색·장식·inline style 제거와 Base UI adapter 사용.
- `apps/web/tests/accessibility/core-routes.spec.ts`, `apps/web/tests/e2e/user-journeys.spec.ts`: Base UI DOM과 keyboard 흐름에 맞춘 검증.

---

### Task 1: Base UI 의존성, portal 기반과 무채색 안전망

**Files:**
- Modify: `apps/web/package.json`
- Modify: `apps/web/package-lock.json`
- Modify: `apps/web/src/app/layout.tsx`
- Modify: `apps/web/src/app/globals.css`
- Create: `apps/web/tests/unit/monochrome-ui.test.ts`

**Interfaces:**
- Produces: `.app-root` isolation context와 `--gray-0`부터 `--gray-950`까지의 무채색 전역 토큰.
- Produces: 소스 내 유채색과 CSS gradient를 파일·값과 함께 보고하는 정적 Vitest.
- Consumes: 승인된 디자인 문서 `docs/decisions/mas-a/2026-08-16-base-ui-redesign-design.md`.

- [ ] **Step 1: 무채색 정책이 현재 코드에서 실패하는 테스트 작성**

```ts
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const sourceRoot = join(process.cwd(), "src");
const files = (directory: string): string[] => readdirSync(directory).flatMap((name) => {
  const path = join(directory, name);
  return statSync(path).isDirectory() ? files(path) : /\.(css|tsx)$/.test(path) ? [path] : [];
});
const expand = (hex: string) => hex.length <= 4
  ? hex.slice(1).split("").slice(0, 3).map((digit) => parseInt(digit + digit, 16))
  : [hex.slice(1, 3), hex.slice(3, 5), hex.slice(5, 7)].map((pair) => parseInt(pair, 16));
const chromaticFunctions = (source: string) => [
  ...source.matchAll(/rgba?\(\s*(\d+)\D+(\d+)\D+(\d+)/gi),
].filter((match) => new Set(match.slice(1, 4).map(Number)).size !== 1).map((match) => match[0]);
const chromaticHsl = (source: string) => [...source.matchAll(/hsla?\(\s*[^, ]+[, ]+([\d.]+)%/gi)]
  .filter((match) => Number(match[1]) !== 0).map((match) => match[0]);
const chromaticNames = /\b(red|blue|green|orange|purple|yellow|teal|navy|maroon|olive|aqua|fuchsia)\b/gi;

describe("monochrome UI policy", () => {
  it("contains no chromatic hex values or gradients", () => {
    const violations = files(sourceRoot).flatMap((path) => {
      const source = readFileSync(path, "utf8");
      const hexes = source.match(/#[0-9a-f]{3,8}\b/gi) ?? [];
      const chromatic = hexes.filter((hex) => new Set(expand(hex)).size !== 1);
      return [...chromatic, ...chromaticFunctions(source), ...chromaticHsl(source), ...(source.match(chromaticNames) ?? []), ...(source.match(/(?:linear|radial|conic)-gradient\(/gi) ?? [])]
        .map((value) => `${path.replace(process.cwd(), "")}: ${value}`);
    });
    expect(violations).toEqual([]);
  });
});
```

- [ ] **Step 2: 테스트가 기존 색과 gradient를 검출하는지 확인**

Run: `cd apps/web && npm test -- tests/unit/monochrome-ui.test.ts`

Expected: FAIL하며 `globals.css`와 `visualization-explorer.tsx` 등의 유채색 값이 목록에 포함된다.

- [ ] **Step 3: Base UI 1.7.0 설치**

Run: `cd apps/web && npm install @base-ui/react@1.7.0 --save-exact`

Expected: `package.json` dependencies에 `"@base-ui/react": "1.7.0"`이 추가되고 lockfile이 갱신된다.

- [ ] **Step 4: 공식 portal 권장 구조 적용**

```tsx
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko" data-scroll-behavior="smooth">
      <body>
        <div className="app-root">
          <Providers><AppShell>{children}</AppShell></Providers>
        </div>
      </body>
    </html>
  );
}
```

- [ ] **Step 5: 전역 색 토큰과 문서 기반 초기 스타일을 무채색으로 교체**

```css
:root {
  --gray-0: #fff;
  --gray-50: #fafafa;
  --gray-100: #f5f5f5;
  --gray-200: #e5e5e5;
  --gray-300: #d4d4d4;
  --gray-500: #737373;
  --gray-700: #404040;
  --gray-900: #171717;
  --gray-950: #000;
  --background: var(--gray-0);
  --foreground: var(--gray-950);
  --muted: var(--gray-500);
  --line: var(--gray-200);
  --focus: var(--gray-950);
  --radius: .5rem;
}

body { position: relative; margin: 0; background: #fff; color: #000; }
.app-root { isolation: isolate; min-height: 100dvh; }
:focus-visible { outline: 2px solid #000; outline-offset: 2px; }
```

Retain the existing semantic layout class names in this task, but replace every chromatic value and gradient with the tokens above so the safety test passes before component migration.

- [ ] **Step 6: 정적 안전망과 기본 빌드 검증**

Run: `cd apps/web && npm test -- tests/unit/monochrome-ui.test.ts && npm run typecheck`

Expected: PASS.

- [ ] **Step 7: 커밋**

```bash
git add apps/web/package.json apps/web/package-lock.json apps/web/src/app/layout.tsx apps/web/src/app/globals.css apps/web/tests/unit/monochrome-ui.test.ts
git commit -m "chore(web): establish Base UI monochrome foundation"
```

---

### Task 2: 공용 Button, 상태, Tabs, Dialog, Drawer, Toast primitive

**Files:**
- Create: `apps/web/src/components/ui/primitives.module.css`
- Create: `apps/web/src/components/ui/overlays.module.css`
- Create: `apps/web/src/components/ui/navigation.module.css`
- Modify: `apps/web/src/components/ui/button.tsx`
- Modify: `apps/web/src/components/ui/badge.tsx`
- Modify: `apps/web/src/components/ui/state-panel.tsx`
- Modify: `apps/web/src/components/ui/skeleton.tsx`
- Modify: `apps/web/src/components/ui/tabs.tsx`
- Modify: `apps/web/src/components/ui/dialog.tsx`
- Modify: `apps/web/src/components/ui/drawer.tsx`
- Modify: `apps/web/src/components/ui/toast.tsx`
- Modify: `apps/web/src/app/providers.tsx`
- Create: `apps/web/tests/component/base-primitives.test.tsx`
- Modify: `apps/web/tests/component/state-panel.test.tsx`

**Interfaces:**
- Produces: `Button({ variant: "primary" | "secondary" | "danger" | "ghost", ...Button.Props })` backed by Base UI Button.
- Produces: `Tabs<T>({ label, value, items, onChange })` backed by Base UI Tabs.
- Produces: `Dialog({ open, title, children, onClose })` and `Drawer({ open, title, children, onClose })` with controlled Base UI roots.
- Produces: `Toast({ message, title? })` which publishes into the global Base UI Toast manager.
- Consumes: `.app-root`, grayscale tokens from Task 1.

- [ ] **Step 1: Base UI behavior tests 작성**

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Tabs } from "@/components/ui/tabs";

describe("Base UI adapters", () => {
  it("keeps button semantics and disabled behavior", () => {
    const onClick = vi.fn();
    render(<Button disabled onClick={onClick}>저장</Button>);
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
    expect(onClick).not.toHaveBeenCalled();
  });

  it("returns focus when a controlled dialog closes", () => {
    function Harness() {
      const [open, setOpen] = useState(false);
      return <><button onClick={() => setOpen(true)}>열기</button><Dialog open={open} title="확인" onClose={() => setOpen(false)}>내용</Dialog></>;
    }
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "열기" }));
    expect(screen.getByRole("dialog", { name: "확인" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "대화상자 닫기" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("changes controlled tabs through Base UI", () => {
    function Harness() {
      const [value, setValue] = useState<"a" | "b">("a");
      return <Tabs label="보기" value={value} items={[{ value: "a", label: "A" }, { value: "b", label: "B" }]} onChange={setValue} />;
    }
    render(<Harness />);
    fireEvent.click(screen.getByRole("tab", { name: "B" }));
    expect(screen.getByRole("tab", { name: "B" })).toHaveAttribute("aria-selected", "true");
  });
});
```

- [ ] **Step 2: adapter 테스트 실패 확인**

Run: `cd apps/web && npm test -- tests/component/base-primitives.test.tsx tests/component/state-panel.test.tsx`

Expected: FAIL because the current components are native or hand-rolled.

- [ ] **Step 3: Button과 Tabs를 Base UI로 교체**

```tsx
import { Button as BaseButton } from "@base-ui/react/button";
import styles from "./primitives.module.css";

type Props = BaseButton.Props & { variant?: "primary" | "secondary" | "danger" | "ghost" };
export function AppButton({ variant = "primary", className, ...props }: Props) {
  return <BaseButton className={`${styles.button} ${styles[variant]} ${className ?? ""}`} {...props} />;
}
export { AppButton as Button };
```

```tsx
import { Tabs as BaseTabs } from "@base-ui/react/tabs";
type TabsProps<T extends string> = {
  label: string;
  value: T;
  items: Array<{ value: T; label: string; disabled?: boolean }>;
  onChange: (value: T) => void;
};
export function Tabs<T extends string>({ label, value, items, onChange }: TabsProps<T>) {
  return <BaseTabs.Root value={value} onValueChange={(next) => onChange(next as T)}>
    <BaseTabs.List aria-label={label} className={styles.tabsList}>
      {items.map((item) => <BaseTabs.Tab key={item.value} value={item.value} disabled={item.disabled} className={styles.tab}>{item.label}</BaseTabs.Tab>)}
      <BaseTabs.Indicator className={styles.tabIndicator} />
    </BaseTabs.List>
  </BaseTabs.Root>;
}
```

- [ ] **Step 4: Dialog와 Drawer를 Base UI portal 구조로 교체**

```tsx
<BaseDialog.Root open={open} onOpenChange={(next) => { if (!next) onClose(); }}>
  <BaseDialog.Portal>
    <BaseDialog.Backdrop className={styles.backdrop} />
    <BaseDialog.Viewport className={styles.viewport}>
      <BaseDialog.Popup className={styles.dialogPopup}>
        <header className={styles.dialogHeader}>
          <BaseDialog.Title>{title}</BaseDialog.Title>
          <BaseDialog.Close render={<Button variant="ghost" aria-label="대화상자 닫기" />}><X aria-hidden="true" /></BaseDialog.Close>
        </header>
        {children}
      </BaseDialog.Popup>
    </BaseDialog.Viewport>
  </BaseDialog.Portal>
</BaseDialog.Root>
```

Use the same controlled contract for `Drawer.Root`; compose `Drawer.Viewport`, `Drawer.Popup`, `Drawer.Content`, and Base UI `ScrollArea` for the body.

- [ ] **Step 5: 전역 Base UI Toast provider와 publisher 구현**

```tsx
export function Toast({ message, title = "알림" }: { message: string; title?: string }) {
  const manager = BaseToast.useToastManager();
  useEffect(() => {
    manager.add({ title, description: message });
  }, [manager, message, title]);
  return null;
}

export function ToastViewport() {
  const { toasts } = BaseToast.useToastManager();
  return <BaseToast.Portal><BaseToast.Viewport className={styles.toastViewport}>
    {toasts.map((toast) => <BaseToast.Root key={toast.id} toast={toast} className={styles.toastRoot}>
      <BaseToast.Content><BaseToast.Title /><BaseToast.Description /></BaseToast.Content>
      <BaseToast.Close aria-label="알림 닫기">닫기</BaseToast.Close>
    </BaseToast.Root>)}
  </BaseToast.Viewport></BaseToast.Portal>;
}
```

Wrap the existing provider body with `<BaseToast.Provider><ToastViewport />…</BaseToast.Provider>`.

- [ ] **Step 6: Badge, StatePanel, Skeleton을 의미 기반 흑백 recipe로 이동**

Use `data-tone` and `data-state` only for icon, border style, and font weight. Use no tone-specific color declarations. Disable shimmer animation in `prefers-reduced-motion`.

```css
.statePanel[data-state="processing"], .statePanel[data-state="stale"] { border-style: dashed; }
.statePanel[data-state="error"], .statePanel[data-state="fatal"] { border-width: 2px; }
.badge { color: #171717; background: #f5f5f5; border: 1px solid #d4d4d4; border-radius: .25rem; }
```

- [ ] **Step 7: 공용 primitive 테스트와 typecheck**

Run: `cd apps/web && npm test -- tests/component/base-primitives.test.tsx tests/component/state-panel.test.tsx && npm run typecheck`

Expected: PASS.

- [ ] **Step 8: 커밋**

```bash
git add apps/web/src/components/ui apps/web/src/app/providers.tsx apps/web/tests/component
git commit -m "feat(web): replace shared controls with Base UI"
```

---

### Task 3: Base UI form adapter와 온보딩 교체

**Files:**
- Create: `apps/web/src/components/ui/forms.module.css`
- Create: `apps/web/src/components/ui/checkbox-field.tsx`
- Create: `apps/web/src/components/ui/radio-scale.tsx`
- Create: `apps/web/src/components/ui/select-field.tsx`
- Create: `apps/web/src/components/ui/text-field.tsx`
- Modify: `apps/web/src/components/ui/slider.tsx`
- Modify: `apps/web/src/features/onboarding/consent-form.tsx`
- Modify: `apps/web/src/features/onboarding/questionnaire-form.tsx`
- Modify: `apps/web/src/features/onboarding/demographics-form.tsx`
- Modify: `apps/web/src/app/login/page.tsx`
- Create: `apps/web/tests/component/base-form-controls.test.tsx`
- Modify: `apps/web/tests/e2e/user-journeys.spec.ts`

**Interfaces:**
- Produces: `CheckboxFieldProps { name, label, description, checked?, onCheckedChange?, required? }`.
- Produces: `RadioScaleProps { name, label, options: Array<{ value: string; label: string }> }`.
- Produces: `SelectFieldProps<T> { id, label, value, items, onValueChange, optional? }`.
- Produces: `TextFieldProps { label, value?, defaultValue?, onValueChange?, placeholder?, hideLabel?, startIcon?, multiline?, required?, error? }`; `multiline` renders `Field.Control render={<textarea />}`.
- Produces: existing `Slider({ id, label, value, min, max, onChange })` API backed by Base UI Slider and NumberField.
- Consumes: Button and feedback primitives from Task 2.

- [ ] **Step 1: form adapter의 제출값과 조작 테스트 작성**

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CheckboxField } from "@/components/ui/checkbox-field";
import { SelectField } from "@/components/ui/select-field";
import { Slider } from "@/components/ui/slider";

describe("Base UI form adapters", () => {
  it("submits a named checked value", () => {
    render(<form data-testid="form"><CheckboxField name="privacy" label="개인정보 처리" description="설명" /></form>);
    fireEvent.click(screen.getByRole("checkbox", { name: "개인정보 처리" }));
    expect(new FormData(screen.getByTestId("form") as HTMLFormElement).has("privacy")).toBe(true);
  });

  it("changes slider and number field through one callback", () => {
    const onChange = vi.fn();
    render(<Slider id="economy" label="경제" value={0} min={-100} max={100} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("경제 숫자 입력"), { target: { value: "24" } });
    expect(onChange).toHaveBeenLastCalledWith(24);
  });

  it("opens a select popup and chooses a value", () => {
    const onValueChange = vi.fn();
    render(<SelectField id="age" label="연령대" value="" onValueChange={onValueChange} items={[{ value: "none", label: "응답하지 않음" }, { value: "25-34", label: "25–34" }]} />);
    fireEvent.click(screen.getByRole("combobox", { name: "연령대" }));
    fireEvent.click(screen.getByRole("option", { name: "25–34" }));
    expect(onValueChange).toHaveBeenCalledWith("25-34");
  });
});
```

- [ ] **Step 2: form 테스트 실패 확인**

Run: `cd apps/web && npm test -- tests/component/base-form-controls.test.tsx`

Expected: FAIL because the new adapters do not exist.

- [ ] **Step 3: Checkbox, Radio, Select adapter 구현**

```tsx
<Field.Item className={styles.choiceItem}>
  <BaseCheckbox.Root name={name} checked={checked} onCheckedChange={onCheckedChange} className={styles.checkbox}>
    <BaseCheckbox.Indicator className={styles.checkboxIndicator}><Check aria-hidden="true" /></BaseCheckbox.Indicator>
  </BaseCheckbox.Root>
  <div><Field.Label>{label}</Field.Label><Field.Description>{description}</Field.Description></div>
</Field.Item>
```

Radio options use `RadioGroup name={name}` and `Radio.Root value={option.value}`. Select uses `Select.Root`, `Select.Trigger`, `Select.Value`, `Select.Portal`, `Select.Positioner`, `Select.Popup`, `Select.List`, and `Select.Item` with a hidden form value supplied by Base UI.

- [ ] **Step 4: Slider와 NumberField를 하나의 controlled field로 조합**

```tsx
<Field.Root className={styles.field}>
  <Field.Label>{label}</Field.Label>
  <div className={styles.scoreControls}>
    <BaseSlider.Root value={[value]} min={min} max={max} onValueChange={(next) => onChange(next[0])} className={styles.slider}>
      <BaseSlider.Control><BaseSlider.Track><BaseSlider.Indicator /></BaseSlider.Track><BaseSlider.Thumb aria-label={label} /></BaseSlider.Control>
    </BaseSlider.Root>
    <NumberField.Root value={value} min={min} max={max} onValueChange={(next) => next !== null && onChange(next)}>
      <NumberField.Group><NumberField.Input aria-label={`${label} 숫자 입력`} /></NumberField.Group>
    </NumberField.Root>
  </div>
</Field.Root>
```

- [ ] **Step 5: 온보딩과 로그인 네이티브 control 교체**

Replace consent inputs with `CheckboxField`, questionnaire fieldsets with `RadioScale`, demographics selects with `SelectField`, and provider buttons with monochrome Button/link recipes. Preserve Korean copy and route transitions.

- [ ] **Step 6: E2E selector를 Base UI roles로 갱신**

```ts
for (const label of ["서비스 이용약관", "개인정보 처리", "정치 민감정보 처리"]) {
  await page.getByRole("checkbox", { name: new RegExp(label) }).click();
}
for (const group of ["경제적 불평등", "사회 제도", "국제 문제"]) {
  await page.getByRole("group", { name: new RegExp(group) }).getByRole("radio", { name: "3" }).click();
}
```

- [ ] **Step 7: form, onboarding, typecheck 검증**

Run: `cd apps/web && npm test -- tests/component/base-form-controls.test.tsx && npm run typecheck && npm run lint`

Expected: PASS.

- [ ] **Step 8: 커밋**

```bash
git add apps/web/src/components/ui apps/web/src/features/onboarding apps/web/src/app/login apps/web/tests
git commit -m "feat(web): migrate forms and onboarding to Base UI"
```

---

### Task 4: 흰색 앱 셸, 탐색 Menu와 콘텐츠 표면

**Files:**
- Modify: `apps/web/src/components/layout/app-shell.tsx`
- Modify: `apps/web/src/components/layout/page-header.tsx`
- Modify: `apps/web/src/app/globals.css`
- Modify: `apps/web/src/app/page.tsx`
- Modify: `apps/web/src/app/issues/page.tsx`
- Modify: `apps/web/src/app/issues/[issueId]/page.tsx`
- Modify: `apps/web/src/app/articles/[articleId]/page.tsx`
- Modify: `apps/web/src/features/feed/article-card.tsx`
- Modify: `apps/web/src/features/issues/issue-card.tsx`

**Interfaces:**
- Produces: desktop and mobile navigation with the same route list and `aria-current="page"` behavior.
- Produces: Base UI `Menu` profile trigger with `/login`, `/settings/privacy`, `/admin/sources` links as appropriate.
- Consumes: Button, Badge, Menu/overlay CSS from Tasks 1–3.

- [ ] **Step 1: 앱 셸 role·active-state Playwright assertion 추가**

```ts
test("application shell exposes monochrome navigation state", async ({ page }) => {
  await page.goto("/issues");
  await expect(page.getByRole("navigation", { name: "주요 메뉴" }).getByRole("link", { name: "이슈" })).toHaveAttribute("aria-current", "page");
  await expect(page.locator("body")).toHaveCSS("background-color", "rgb(255, 255, 255)");
});
```

- [ ] **Step 2: 기존 셸에서 assertion 실패 확인**

Run: `cd apps/web && npx playwright test tests/accessibility/core-routes.spec.ts --grep "application shell"`

Expected: FAIL because the desktop navigation lacks the requested accessible name and the old surface is tinted.

- [ ] **Step 3: 흰색 셸과 Base UI Menu 프로필 구현**

```tsx
<aside className="sidebar">
  <Link href={admin ? "/admin/sources" : "/"} className="brand">사이 <span>Perspective index</span></Link>
  <nav aria-label={admin ? "관리자 메뉴" : "주요 메뉴"}>{/* existing mapped links */}</nav>
  <BaseMenu.Root>
    <BaseMenu.Trigger className="profile-trigger"><UserRound aria-hidden="true" /> 김사이</BaseMenu.Trigger>
    <BaseMenu.Portal><BaseMenu.Positioner sideOffset={8}><BaseMenu.Popup className={overlayStyles.menuPopup}>
      <BaseMenu.Item render={<Link href="/login" />}>계정 전환</BaseMenu.Item>
      <BaseMenu.Item render={<Link href={admin ? "/" : "/admin/sources"} />}>{admin ? "사용자 웹" : "관리자 웹"}</BaseMenu.Item>
    </BaseMenu.Popup></BaseMenu.Positioner></BaseMenu.Portal>
  </BaseMenu.Root>
</aside>
```

- [ ] **Step 4: 홈 banner와 카드의 장식 제거**

Keep the current headings and links, but remove `.orbit`, pseudo-element circles, gradients, colored badges, tinted cards, and serif display font. Use one white editorial header with a bottom border, a two-column feed, and restrained card separators.

```css
.feature-banner { display: grid; gap: 2rem; min-height: 0; padding: 3rem 0; color: #000; background: #fff; border: 0; border-bottom: 1px solid #d4d4d4; box-shadow: none; }
.news-card { background: #fff; border: 1px solid #e5e5e5; border-radius: .5rem; }
.news-card::after, .feature-banner::before { content: none; }
```

- [ ] **Step 5: 이슈·기사 화면을 흑백 axis와 구획으로 통일**

Replace colored axis tracks with a solid gray track and black marker; replace notices with left black rules; preserve original-source links, comparison content, model states, vote form placement, and sticky article sidebar.

- [ ] **Step 6: 셸·콘텐츠 검증**

Run: `cd apps/web && npm run typecheck && npm run lint && npx playwright test tests/accessibility/core-routes.spec.ts --grep "application shell|/|issues|articles"`

Expected: PASS.

- [ ] **Step 7: 커밋**

```bash
git add apps/web/src/components/layout apps/web/src/app apps/web/src/features/feed apps/web/src/features/issues apps/web/tests/accessibility
git commit -m "feat(web): redesign shell and editorial content in monochrome"
```

---

### Task 5: 투표, 효능감, 진행도와 개인정보 control 교체

**Files:**
- Create: `apps/web/src/components/ui/toolbar.tsx`
- Modify: `apps/web/src/features/voting/vote-form.tsx`
- Modify: `apps/web/src/features/efficacy/efficacy-form.tsx`
- Modify: `apps/web/src/features/auth/privacy-actions.tsx`
- Modify: `apps/web/src/app/efficacy/page.tsx`
- Modify: `apps/web/src/app/progress/page.tsx`
- Modify: `apps/web/src/app/settings/privacy/page.tsx`
- Modify: `apps/web/src/components/ui/score-axis.tsx`
- Modify: `apps/web/tests/e2e/user-journeys.spec.ts`

**Interfaces:**
- Produces: `Toolbar({ label, children })` backed by Base UI Toolbar.Root.
- Consumes: Slider/NumberField, Dialog, Toast, Button, Meter/Progress from earlier tasks.

- [ ] **Step 1: score control 연동과 toast E2E assertion 강화**

```ts
test("vote slider and number field stay synchronized", async ({ page }) => {
  await page.goto("/articles/article-01");
  const number = page.getByLabel("경제 숫자 입력");
  await number.fill("24");
  await expect(page.getByRole("slider", { name: "경제 (평등·재분배 ↔ 시장·경쟁)" })).toHaveAttribute("aria-valuenow", "24");
  await page.getByRole("button", { name: "투표 저장·수정" }).click();
  await expect(page.getByRole("region", { name: "알림" })).toContainText("revision 2");
});
```

- [ ] **Step 2: 강화된 동기화 테스트 실패 확인**

Run: `cd apps/web && npx playwright test tests/e2e/user-journeys.spec.ts --grep "synchronized"`

Expected: FAIL because current range and toast are not Base UI components.

- [ ] **Step 3: 투표와 효능감 control을 Base UI Slider/NumberField로 교체**

Render one shared `Slider` adapter for every X/Y/Z/sensationalism value, keep Zod validation, keep delete/reset messages, and publish mutations through the global Toast manager.

- [ ] **Step 4: 진행도·신뢰도에 Meter와 Progress 적용**

```tsx
<Meter.Root value={confidence * 100} min={0} max={100} className={styles.meter}>
  <div className={styles.meterHeader}><Meter.Label>분석 신뢰도</Meter.Label><Meter.Value /></div>
  <Meter.Track><Meter.Indicator /></Meter.Track>
</Meter.Root>
```

Use `Meter` for scalar confidence and efficacy values; use `Progress` only for pending export/deletion work. Keep tables semantic.

- [ ] **Step 5: 개인정보 작업을 Base UI Dialog와 Toolbar로 교체**

Keep export, consent withdrawal, profile deletion state transitions. Destructive actions remain visually monochrome and use explicit icon, label, and confirmation copy.

- [ ] **Step 6: 관련 테스트와 typecheck 검증**

Run: `cd apps/web && npm test && npm run typecheck && npx playwright test tests/e2e/user-journeys.spec.ts --grep "vote|efficacy"`

Expected: PASS.

- [ ] **Step 7: 커밋**

```bash
git add apps/web/src/components/ui apps/web/src/features/voting apps/web/src/features/efficacy apps/web/src/features/auth apps/web/src/app/efficacy apps/web/src/app/progress apps/web/src/app/settings apps/web/tests/e2e
git commit -m "feat(web): migrate scoring and privacy workflows to Base UI"
```

---

### Task 6: 시각화 Tabs, Toolbar, Tooltip과 흑백 도형 체계

**Files:**
- Modify: `apps/web/src/features/visualization/visualization-explorer.tsx`
- Modify: `apps/web/src/app/visualization/page.tsx`
- Modify: `apps/web/src/app/globals.css`
- Modify: `apps/web/tests/accessibility/core-routes.spec.ts`
- Modify: `apps/web/tests/e2e/user-journeys.spec.ts`

**Interfaces:**
- Consumes: `Tabs`, `Toolbar`, `Button`, `Tooltip`, Badge, StatePanel.
- Produces: shape mapping `{ article: "circle", source: "square", user: "diamond" }` used by 2D points and legend.
- Produces: Three.js grayscale material mapping with `#fff`, `#737373`, `#000` only.

- [ ] **Step 1: 모드, toolbar와 형태 범례 접근성 테스트 작성**

```ts
test("visualization exposes shape-based monochrome legend", async ({ page }) => {
  await page.goto("/visualization?webgl-off=1");
  await expect(page.getByRole("tab", { name: "2D 투영" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByLabel("포인트 범례")).toContainText("기사 · 원");
  await expect(page.getByLabel("포인트 범례")).toContainText("언론사 · 사각형");
  await expect(page.getByLabel("포인트 범례")).toContainText("사용자 응답 결과 · 마름모");
});
```

- [ ] **Step 2: 형태 범례 테스트 실패 확인**

Run: `cd apps/web && npx playwright test tests/accessibility/core-routes.spec.ts --grep "shape-based"`

Expected: FAIL because the current legend relies on colored dots.

- [ ] **Step 3: 수제 tabs와 button group을 Base UI로 교체**

Use shared `Tabs` for `3d | 2d | table`, `Tabs` or `ToggleGroup` for `xy | xz | yz`, `Toolbar` for zoom/reset, and Tooltip for icon-only zoom controls. Preserve disabled 3D behavior when WebGL is unavailable.

- [ ] **Step 4: Three.js points를 grayscale 재질로 교체**

```tsx
const material = {
  article: { color: "#fff", wireframe: false },
  source: { color: "#000", wireframe: false },
  user: { color: "#737373", wireframe: true },
} as const;

<meshStandardMaterial
  color={material[point.type].color}
  wireframe={material[point.type].wireframe}
  emissive={selected === point.id ? "#737373" : "#000"}
  emissiveIntensity={selected === point.id ? .25 : 0}
/>
```

- [ ] **Step 5: 2D points와 legend를 도형·텍스트 기반으로 교체**

Use circle, square, and diamond geometry; selection uses a 3px black outline and larger dimensions. Use a plain white plotting area, solid gray grid lines, and black axis lines.

- [ ] **Step 6: 시각화 fallback, accessibility, typecheck 검증**

Run: `cd apps/web && npm run typecheck && npx playwright test tests/accessibility/core-routes.spec.ts tests/e2e/user-journeys.spec.ts --grep "visualization|fallback|shape-based"`

Expected: PASS.

- [ ] **Step 7: 커밋**

```bash
git add apps/web/src/features/visualization apps/web/src/app/visualization apps/web/src/app/globals.css apps/web/tests
git commit -m "feat(web): convert visualization to monochrome Base UI controls"
```

---

### Task 7: 공유 카드의 Base UI 폼과 흑백 preview

**Files:**
- Modify: `apps/web/src/features/share-cards/share-card-creator.tsx`
- Modify: `apps/web/src/features/share-cards/share-card-status.tsx`
- Modify: `apps/web/src/app/share/new/page.tsx`
- Modify: `apps/web/src/app/share/[shareCardId]/page.tsx`
- Modify: `apps/web/src/app/globals.css`
- Modify: `apps/web/tests/e2e/user-journeys.spec.ts`

**Interfaces:**
- Consumes: SelectField, TextField, CheckboxField, Dialog, Toast, Button.
- Produces: share preview variants `coordinate` and `editorial`, both restricted to grayscale tokens.

- [ ] **Step 1: 공유 폼과 폐기 확인 흐름 테스트 작성**

```ts
test("share creation uses accessible Base UI controls and confirms revoke", async ({ page }) => {
  await page.goto("/share/new");
  await page.getByRole("combobox", { name: "템플릿" }).click();
  await page.getByRole("option", { name: "에디토리얼" }).click();
  await page.getByRole("checkbox", { name: /정치 좌표가 공개/ }).click();
  await page.getByRole("button", { name: "공유 카드 생성" }).click();
  await page.getByRole("button", { name: "즉시 폐기" }).click();
  await expect(page.getByRole("dialog", { name: "공유 카드 폐기" })).toBeVisible();
});
```

- [ ] **Step 2: 현재 즉시 폐기 동작에서 테스트 실패 확인**

Run: `cd apps/web && npx playwright test tests/e2e/user-journeys.spec.ts --grep "confirms revoke"`

Expected: FAIL because revoke currently has no confirmation dialog and template is native select.

- [ ] **Step 3: 생성 폼을 Base UI adapter로 교체**

Replace native select, input, and checkbox with SelectField, TextField, and CheckboxField. Preserve busy, error, public exposure confirmation, generated card ID, and ready transition.

- [ ] **Step 4: 흑백 공유 preview 구현**

Remove the colored orbit and grid gradient. Render three axis rows with labels, tabular values, and black marker positions. The editorial variant uses a serif-free typographic hierarchy, thin rules, and the same white background.

```css
.share-preview { color: #000; background: #fff; border: 1px solid #171717; border-radius: .5rem; box-shadow: 0 8px 24px rgb(0 0 0 / .08); }
.share-preview__axis { border-top: 1px solid #d4d4d4; }
.share-preview__marker { width: .625rem; height: .625rem; border: 2px solid #000; background: #fff; }
```

- [ ] **Step 5: 폐기 확인 Dialog와 결과 Toast 적용**

The first click opens a dialog titled `공유 카드 폐기`; the confirm button performs the existing `setStatus("revoked")` transition. Download and Web Share behavior remain unchanged.

- [ ] **Step 6: 공유 흐름 검증**

Run: `cd apps/web && npm run typecheck && npx playwright test tests/e2e/user-journeys.spec.ts --grep "share"`

Expected: PASS.

- [ ] **Step 7: 커밋**

```bash
git add apps/web/src/features/share-cards apps/web/src/app/share apps/web/src/app/globals.css apps/web/tests/e2e
git commit -m "feat(web): rebuild sharing workflow with Base UI"
```

---

### Task 8: 관리자 검색, Menu, Toolbar와 변경 Dialog

**Files:**
- Modify: `apps/web/src/features/admin/admin-resource-page.tsx`
- Modify: `apps/web/src/app/admin/layout.tsx`
- Modify: `apps/web/src/app/admin/[...section]/page.tsx`
- Modify: `apps/web/src/app/globals.css`
- Modify: `apps/web/tests/e2e/user-journeys.spec.ts`
- Modify: `apps/web/tests/accessibility/core-routes.spec.ts`

**Interfaces:**
- Consumes: TextField, Menu, Toolbar, Dialog, Toast, Button, Badge, StatePanel.
- Preserves: `canPerform(role, level)`, reason field, idempotency key reuse, first-submit conflict, reload-and-retry behavior.

- [ ] **Step 1: 관리자 filter와 dialog keyboard 흐름 테스트 작성**

```ts
test("admin controls use menu and preserve dialog reason", async ({ page }) => {
  await page.goto("/admin/weights");
  await page.getByRole("button", { name: "상태 필터" }).click();
  await expect(page.getByRole("menu")).toBeVisible();
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Publish" }).first().click();
  await page.getByLabel("변경 사유 (필수)").fill("guardrail 검토 완료");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
});
```

- [ ] **Step 2: 현재 수제 filter에서 테스트 실패 확인**

Run: `cd apps/web && npx playwright test tests/e2e/user-journeys.spec.ts --grep "admin controls"`

Expected: FAIL because status filter is currently a plain button without a menu.

- [ ] **Step 3: 검색 Field, 상태 Menu와 action Toolbar 구현**

```tsx
<Toolbar label="관리자 목록 도구">
  <TextField label="검색" hideLabel placeholder="이름·ID 검색" startIcon={<Search aria-hidden="true" />} />
  <BaseMenu.Root>
    <BaseMenu.Trigger render={<Button variant="secondary" />}><Filter aria-hidden="true" /> 상태 필터</BaseMenu.Trigger>
    <BaseMenu.Portal><BaseMenu.Positioner><BaseMenu.Popup className={overlayStyles.menuPopup}>
      <BaseMenu.CheckboxItem checked={showActive} onCheckedChange={setShowActive}>활성</BaseMenu.CheckboxItem>
      <BaseMenu.CheckboxItem checked={showFailed} onCheckedChange={setShowFailed}>실패</BaseMenu.CheckboxItem>
    </BaseMenu.Popup></BaseMenu.Positioner></BaseMenu.Portal>
  </BaseMenu.Root>
</Toolbar>
```

- [ ] **Step 4: 행 동작과 변경 확인을 Base UI에 맞춤**

Use Toolbar for visible actions and Menu for overflow actions. Keep disabled permission buttons visible with Lock icon and title/Tooltip. Use the shared Base UI Dialog for confirmation and `TextField multiline` for the reason.

- [ ] **Step 5: 관리자 표면을 흑백 행 구획으로 변경**

Remove admin-specific dark sidebar and tone-colored status badges. Use white rows, 1px separators, tabular metadata, monochrome status icons, and 2px borders for failed/blocked states.

- [ ] **Step 6: 권한, conflict, 접근성 검증**

Run: `cd apps/web && npm run typecheck && npm run lint && npx playwright test tests/e2e/user-journeys.spec.ts tests/accessibility/core-routes.spec.ts --grep "admin|analyst|weight"`

Expected: PASS, including reason preservation after 409 conflict.

- [ ] **Step 7: 커밋**

```bash
git add apps/web/src/features/admin apps/web/src/app/admin apps/web/src/app/globals.css apps/web/tests
git commit -m "feat(web): migrate admin operations to Base UI"
```

---

### Task 9: 잔여 화면, native control 제거와 전체 회귀 검증

**Files:**
- Modify: `apps/web/src/app/error.tsx`
- Modify: `apps/web/src/app/loading.tsx`
- Modify: `apps/web/src/app/not-found.tsx`
- Modify: `apps/web/src/app/onboarding/consent/page.tsx`
- Modify: `apps/web/src/app/onboarding/questionnaire/page.tsx`
- Modify: `apps/web/src/app/onboarding/demographics/page.tsx`
- Modify: `apps/web/src/components/ui/empty.tsx`
- Modify: `apps/web/src/components/ui/error-boundary.tsx`
- Modify: `apps/web/src/app/globals.css`
- Modify: `apps/web/tests/unit/monochrome-ui.test.ts`
- Modify: `apps/web/tests/accessibility/core-routes.spec.ts`
- Modify: `apps/web/tests/e2e/user-journeys.spec.ts`

**Interfaces:**
- Consumes: all shared Base UI adapters and grayscale tokens.
- Produces: a complete source audit that allows native semantic tables, links, textareas composed through Field, and canvas, while rejecting hand-rolled interactive primitives requested for migration.

- [ ] **Step 1: 금지 primitive 잔존 검사를 정적 테스트에 추가**

```ts
it("does not leave replaceable native or hand-rolled controls in features", () => {
  const interactiveSources = files(join(sourceRoot, "features")).map((path) => [path, readFileSync(path, "utf8")] as const);
  const forbidden = [
    /<dialog\b/,
    /<select\b/,
    /type=["']checkbox["']/,
    /type=["']radio["']/,
    /type=["']range["']/,
    /role=["']tablist["']/,
  ];
  const violations = interactiveSources.flatMap(([path, source]) => forbidden
    .filter((pattern) => pattern.test(source))
    .map((pattern) => `${path.replace(process.cwd(), "")}: ${pattern.source}`));
  expect(violations).toEqual([]);
});
```

- [ ] **Step 2: 잔여 native control이 있으면 실패 확인**

Run: `cd apps/web && npm test -- tests/unit/monochrome-ui.test.ts`

Expected: FAIL if any feature still contains a replaceable native control; otherwise PASS and continue to source audit.

- [ ] **Step 3: 전체 source audit로 inline color와 장식 제거**

Run: `cd apps/web && rg -n "#[0-9a-fA-F]{3,8}|rgb\(|hsl\(|gradient\(|accent-color|color:\s*(red|blue|green|orange|purple)" src`

Expected: only grayscale values remain. Replace any chromatic match; remove inline color styles and move layout-only inline styles into named classes.

- [ ] **Step 4: 잔여 페이지 상태를 공용 primitive에 맞춤**

Ensure loading uses Skeleton, empty/not-found use StatePanel/Empty, errors use ErrorBoundary/StatePanel, and onboarding page wrappers use the white form card recipe. Preserve headings and route links.

- [ ] **Step 5: reduced motion과 responsive CSS 확인**

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { scroll-behavior: auto !important; animation-duration: .01ms !important; animation-iteration-count: 1 !important; transition-duration: .01ms !important; }
}
@media (max-width: 760px) {
  .main-content { margin-left: 0; padding: 1.25rem 1rem 6rem; }
  .grid--2, .grid--3, .grid--4, .article-layout { grid-template-columns: 1fr; }
}
```

- [ ] **Step 6: 모든 자동 검증 실행**

Run: `cd apps/web && npm run typecheck && npm run lint && npm test && npm run build`

Expected: all commands exit 0.

Run: `cd apps/web && npm run test:a11y && npm run test:e2e`

Expected: all Playwright tests pass, including keyboard controls, WebGL fallback, user journeys, admin permissions, conflict retry, share revoke confirmation, and zero critical axe violations.

- [ ] **Step 7: 데스크톱·모바일 시각 검증**

Run the app with `cd apps/web && npm run dev`, then inspect `/`, `/login`, `/onboarding/consent`, `/articles/article-01`, `/visualization?webgl-off=1`, `/share/new`, and `/admin/weights` at 1440×900 and 390×844.

Expected: white background throughout; no chromatic pixels in UI surfaces or canvas; popup layering is correct; long Korean copy does not overflow; focus rings are visible; tables remain horizontally scrollable.

- [ ] **Step 8: 최종 커밋**

```bash
git add apps/web
git commit -m "test(web): verify complete Base UI monochrome migration"
```

---

## Completion Checklist

- [ ] `@base-ui/react@1.7.0` is the only newly added UI dependency.
- [ ] Every replaceable interactive component uses a Base UI primitive.
- [ ] All backgrounds are white and every visible color is black, white, or neutral gray.
- [ ] OAuth, status, charts, 2D and 3D visualization contain no chromatic colors.
- [ ] Dialog, Drawer, Menu, Select, Tooltip and Toast render through portals above `.app-root`.
- [ ] Keyboard focus, Escape close, focus return, slider arrows, radio selection, checkbox toggling and select navigation work.
- [ ] User, share and admin workflows preserve existing data and permission semantics.
- [ ] Typecheck, lint, unit, component, build, accessibility and E2E suites pass.
