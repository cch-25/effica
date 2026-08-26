"use client";

import { Checkbox } from "@base-ui/react/checkbox";
import { Field } from "@base-ui/react/field";
import { Input } from "@base-ui/react/input";
import { Radio } from "@base-ui/react/radio";
import { RadioGroup } from "@base-ui/react/radio-group";
import { Select } from "@base-ui/react/select";
import { Check, ChevronDown, ChevronUp } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";

export function CheckboxField({ label, description, className = "", ...props }: Omit<Checkbox.Root.Props, "children"> & { label: ReactNode; description?: ReactNode; className?: string }) {
  return <label className={`check-row ${className}`}><Checkbox.Root className="base-checkbox" {...props}><Checkbox.Indicator className="base-checkbox__indicator"><Check size={12} strokeWidth={3} /></Checkbox.Indicator></Checkbox.Root><span><strong>{label}</strong>{description && <small>{description}</small>}</span></label>;
}

export function RadioScale({ name, values, required }: { name: string; values: number[]; required?: boolean }) {
  return <RadioGroup name={name} required={required} className="radio-scale">{values.map((value) => <label className="radio-card" key={value}><Radio.Root value={String(value)} className="base-radio"><Radio.Indicator className="base-radio__indicator" /></Radio.Root><span>{value}</span></label>)}</RadioGroup>;
}

export function TextField({ label, description, className = "", ...props }: ComponentProps<typeof Input> & { label: ReactNode; description?: ReactNode; className?: string }) {
  return <Field.Root className={`field ${className}`}><Field.Label>{label}</Field.Label><Input className="input" {...props} />{description && <Field.Description>{description}</Field.Description>}</Field.Root>;
}

export function TextareaField({ label, className = "", ...props }: ComponentProps<"textarea"> & { label: ReactNode; className?: string }) {
  return <Field.Root className={`field ${className}`}><Field.Label>{label}</Field.Label><Field.Control render={<textarea {...props} />} className="textarea" /></Field.Root>;
}

export type SelectOption = { value: string; label: string };

export function SelectField({ id, name, label, value, options, onValueChange, placeholder = "선택해 주세요", className = "" }: { id: string; name?: string; label: ReactNode; value: string; options: SelectOption[]; onValueChange: (value: string) => void; placeholder?: string; className?: string }) {
  return <div className={`field ${className}`}><Select.Root id={id} name={name} items={options} value={value || null} onValueChange={(nextValue) => onValueChange(nextValue ?? "")}><Select.Label>{label}</Select.Label><Select.Trigger className="select"><Select.Value className="select__value" placeholder={placeholder} /><Select.Icon><ChevronDown size={14} /></Select.Icon></Select.Trigger><Select.Portal><Select.Positioner className="select-positioner" sideOffset={4}><Select.Popup className="select-popup"><Select.ScrollUpArrow className="select-scroll"><ChevronUp size={12} /></Select.ScrollUpArrow><Select.List className="select-list">{options.map((option) => <Select.Item className="select-item" key={option.value} value={option.value}><Select.ItemIndicator className="select-item__indicator"><Check size={12} strokeWidth={3} /></Select.ItemIndicator><Select.ItemText className="select-item__text">{option.label}</Select.ItemText></Select.Item>)}</Select.List><Select.ScrollDownArrow className="select-scroll"><ChevronDown size={12} /></Select.ScrollDownArrow></Select.Popup></Select.Positioner></Select.Portal></Select.Root></div>;
}
