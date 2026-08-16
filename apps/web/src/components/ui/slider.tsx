"use client";

export function Slider({ id, label, value, min, max, onChange }: { id: string; label: string; value: number; min: number; max: number; onChange: (value: number) => void }) {
  return <div className="slider-field"><label htmlFor={id}>{label}</label><input id={id} type="range" min={min} max={max} value={value} onChange={(event) => onChange(Number(event.target.value))} /><input aria-label={`${label} 숫자 입력`} type="number" min={min} max={max} value={value} onChange={(event) => onChange(Number(event.target.value))} /></div>;
}
