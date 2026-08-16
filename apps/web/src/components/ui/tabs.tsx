"use client";

export type TabItem<T extends string> = { value: T; label: string; disabled?: boolean };

export function Tabs<T extends string>({ label, value, items, onChange }: { label: string; value: T; items: Array<TabItem<T>>; onChange: (value: T) => void }) {
  return <div className="tabs" role="tablist" aria-label={label}>{items.map((item) => <button key={item.value} role="tab" aria-selected={value === item.value} disabled={item.disabled} onClick={() => onChange(item.value)}>{item.label}</button>)}</div>;
}
