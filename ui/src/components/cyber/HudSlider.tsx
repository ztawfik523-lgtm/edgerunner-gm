import type { InputHTMLAttributes } from "react";

export interface HudSliderProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "value" | "onChange"> {
  value: number;
  min?: number;
  max?: number;
  step?: number;
  onChange?: InputHTMLAttributes<HTMLInputElement>["onChange"];
  onValueChange?: (value: number) => void;
  formatValue?: (val: number) => string;
}

/**
 * Recessed Cyberpunk HUD slider with a dedicated right-hand numeric readout
 * so the thumb bar never obscures the live value.
 */
export function HudSlider({
  value,
  min = 0,
  max = 100,
  step = 1,
  onChange,
  onValueChange,
  formatValue,
  disabled,
  className = "",
  ...rest
}: HudSliderProps) {
  const span = max - min;
  const pct = span > 0 ? Math.min(100, Math.max(0, ((value - min) / span) * 100)) : 0;
  const displayValue = formatValue ? formatValue(value) : String(value);

  return (
    <div className={`flex items-center gap-2.5 ${className}`.trim()}>
      <div
        className={`relative h-6 flex-1 overflow-hidden border border-[var(--hud-accent-line)]/50 bg-[var(--hud-accent-navy)] has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-[var(--hud-accent)] ${
          disabled ? "opacity-45" : ""
        }`.trim()}
      >
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 left-0 bg-[var(--hud-accent)]/25"
          style={{ width: `${pct}%` }}
        />
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 w-1.5 bg-[var(--hud-primary-bright)]"
          style={{ left: `clamp(0px, calc(${pct}% - 3px), calc(100% - 6px))` }}
        />
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          disabled={disabled}
          aria-valuetext={formatValue ? displayValue : rest["aria-valuetext"]}
          onChange={(event) => {
            onChange?.(event);
            onValueChange?.(Number(event.target.value));
          }}
          className="absolute inset-0 m-0 h-full w-full cursor-pointer opacity-0 disabled:cursor-not-allowed"
          {...rest}
        />
      </div>
      <span className="w-14 shrink-0 text-right font-cyber-data text-xs font-semibold text-[var(--hud-accent)]">
        {displayValue}
      </span>
    </div>
  );
}
