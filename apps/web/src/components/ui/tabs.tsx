"use client";

import { Tabs as BaseTabs } from "@base-ui/react/tabs";

export type TabItem<T extends string> = { value: T; label: string; disabled?: boolean };

export function Tabs<T extends string>({ label, value, items, onChange, className = "" }: { label: string; value: T; items: Array<TabItem<T>>; onChange: (value: T) => void; className?: string }) {
  return <BaseTabs.Root value={value} onValueChange={(nextValue) => onChange(nextValue as T)} className={`tabs-root ${className}`}><BaseTabs.List className="tabs" aria-label={label}>{items.map((item) => <BaseTabs.Tab key={item.value} value={item.value} disabled={item.disabled}>{item.label}</BaseTabs.Tab>)}<BaseTabs.Indicator className="tabs__indicator" /></BaseTabs.List></BaseTabs.Root>;
}
