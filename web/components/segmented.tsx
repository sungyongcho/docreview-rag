"use client";

export interface SegmentedProps<T extends string> {
  label: string;
  options: Array<{ value: T; label: string }>;
  value: T;
  disabled?: boolean;
  onChange: (value: T) => void;
}

/** Exclusive button group (`role="group"`, `aria-pressed` per option) shared by Build and the Ask composer. */
export function Segmented<T extends string>({ label, options, value, disabled, onChange }: SegmentedProps<T>) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((option) => (
        <button key={option.value} type="button" aria-pressed={value === option.value} disabled={disabled} onClick={() => onChange(option.value)}>{option.label}</button>
      ))}
    </div>
  );
}
