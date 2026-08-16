"use client";

import { NumberField } from "@base-ui/react/number-field";
import { Slider as BaseSlider } from "@base-ui/react/slider";
import { Minus, Plus } from "lucide-react";
import type { ReactNode } from "react";

export function Slider({ id, label, ariaLabel, value, min, max, onChange }: { id: string; label: ReactNode; ariaLabel?: string; value: number; min: number; max: number; onChange: (value: number) => void }) {
  const controlLabel = ariaLabel ?? (typeof label === "string" ? label : id);
  return <div className="slider-field"><label id={`${id}-label`}>{label}</label><BaseSlider.Root id={id} className="base-slider" min={min} max={max} value={value} onValueChange={onChange}><BaseSlider.Control className="base-slider__control"><BaseSlider.Track className="base-slider__track"><BaseSlider.Indicator className="base-slider__indicator" /><BaseSlider.Thumb className="base-slider__thumb" aria-labelledby={`${id}-label`} /></BaseSlider.Track></BaseSlider.Control></BaseSlider.Root><NumberField.Root className="number-field" min={min} max={max} value={value} onValueChange={(nextValue) => { if (nextValue !== null) onChange(nextValue); }}><NumberField.Group className="number-field__group"><NumberField.Decrement className="number-field__step" aria-label={`${controlLabel} 감소`}><Minus size={12} /></NumberField.Decrement><NumberField.Input className="number-field__input" aria-label={`${controlLabel} 숫자 입력`} /><NumberField.Increment className="number-field__step" aria-label={`${controlLabel} 증가`}><Plus size={12} /></NumberField.Increment></NumberField.Group></NumberField.Root></div>;
}
