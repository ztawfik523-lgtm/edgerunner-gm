import type { ChangeEventHandler, MouseEventHandler, ReactNode } from "react";

export interface HudToggleProps {
  checked: boolean;
  onCheckedChange?: (checked: boolean) => void;
  onChange?: ChangeEventHandler<HTMLInputElement>;
  onClick?: MouseEventHandler<HTMLButtonElement>;
  as?: "checkbox" | "button";
  onLabel?: ReactNode;
  offLabel?: ReactNode;
  disabled?: boolean;
  id?: string;
  name?: string;
  className?: string;
  fx?: boolean;
  "aria-label"?: string;
  "aria-labelledby"?: string;
  "aria-describedby"?: string;
}

/**
 * Cyberpunk dot-matrix ON / crimson OFF toggle supporting both native checkbox-switch
 * semantics (for form labels and getByRole("checkbox")) and standalone button mode.
 */
export function HudToggle({
  checked,
  onCheckedChange,
  onChange,
  onClick,
  as = "checkbox",
  onLabel = "ON",
  offLabel = "OFF",
  disabled = false,
  id,
  name,
  className = "",
  fx = true,
  "aria-label": ariaLabel,
  "aria-labelledby": ariaLabelledBy,
  "aria-describedby": ariaDescribedBy,
}: HudToggleProps) {
  const pillClasses = [
    "inline-flex min-w-16 items-center justify-center border px-2 py-1 font-cyber-data text-[11px] font-semibold uppercase tracking-wider transition-colors",
    checked
      ? "cyber-dot-matrix border-[var(--hud-accent-line)] bg-[var(--hud-accent-navy)] text-[var(--hud-accent)]"
      : "border-[var(--hud-primary)] bg-[#6e0d20]/80 text-white",
    disabled ? "opacity-45 cursor-not-allowed" : fx ? "cp-fx-hover" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  if (as === "button") {
    return (
      <button
        id={id}
        type="button"
        aria-pressed={checked}
        aria-label={ariaLabel}
        aria-labelledby={ariaLabelledBy}
        aria-describedby={ariaDescribedBy}
        disabled={disabled}
        onClick={(event) => {
          onClick?.(event);
          onCheckedChange?.(!checked);
        }}
        className={`${pillClasses} ${disabled ? "" : "cursor-pointer"}`.trim()}
      >
        {checked ? onLabel : offLabel}
      </button>
    );
  }

  return (
    <span className="relative inline-flex items-center">
      <input
        id={id}
        name={name}
        type="checkbox"
        {...({ switch: "" } as Record<string, string>)}
        className="peer absolute inset-0 m-0 h-full w-full cursor-pointer opacity-0 disabled:cursor-not-allowed"
        checked={checked}
        disabled={disabled}
        aria-label={ariaLabel}
        aria-labelledby={ariaLabelledBy}
        aria-describedby={ariaDescribedBy}
        onChange={(event) => {
          onChange?.(event);
          onCheckedChange?.(event.target.checked);
        }}
      />
      <span
        aria-hidden="true"
        className={`${pillClasses} pointer-events-none peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-[var(--hud-accent)]`.trim()}
      >
        {checked ? onLabel : offLabel}
      </span>
    </span>
  );
}
