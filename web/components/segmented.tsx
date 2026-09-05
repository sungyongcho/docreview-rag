"use client";
import { useI18n } from "@/lib/i18n";


export interface SegmentedProps<T extends string> {
  label: string;
  options: Array<{ value: T; label: string }>;
  value: T;
  disabled?: boolean;
  onChange: (value: T) => void;
  /** `data-help` topic id so Help mode can point at the whole group. */
  helpId?: string;
}

/** Exclusive button group (`role="group"`, `aria-pressed` per option) shared by Build and the Ask composer. */
export function Segmented<T extends string>({ label, options, value, disabled, onChange, helpId }: SegmentedProps<T>) {
  const { t, locale } = useI18n();
  return (
    <div className="segmented" role="group" aria-label={t(label)} data-help={helpId}>
      {options.map((option) => (
        <button key={option.value} type="button" aria-pressed={value === option.value} disabled={disabled} onClick={() => onChange(option.value)}>{t(option.label)}</button>
      ))}
    </div>
  );
}
