import { forwardRef, type ButtonHTMLAttributes } from "react";

export type HudButtonVariant = "cta" | "tactical" | "utility" | "ghost" | "danger";
export type HudButtonSize = "xs" | "sm" | "md";

export interface HudButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: HudButtonVariant;
  active?: boolean;
  size?: HudButtonSize;
  fx?: boolean;
}

const SIZE_CLASSES: Record<HudButtonSize, string> = {
  xs: "px-2 py-0.5 text-[10px]",
  sm: "px-2.5 py-1 text-xs",
  md: "px-4 py-1.5 text-xs",
};

/**
 * Chamfered 2077 / RED tactical HUD button supporting CTA, tactical, utility, ghost, and danger variants.
 */
export const HudButton = forwardRef<HTMLButtonElement, HudButtonProps>(
  function HudButton(
    {
      variant = "tactical",
      active = false,
      size = "sm",
      fx = true,
      type = "button",
      disabled,
      className = "",
      children,
      ...rest
    },
    ref,
  ) {
    const fxClass = fx && !disabled ? "cp-fx-hover" : "";
    const sizeClass = SIZE_CLASSES[size];

    if (variant === "cta") {
      const wrapWidth = className.includes("w-full") ? "w-full" : "";
      const compactWrap = size === "xs" ? "cyber-cta-wrap--compact" : "";
      return (
        <span className={`cyber-cta-wrap ${compactWrap} ${wrapWidth}`.trim()}>
          <button
            ref={ref}
            type={type}
            disabled={disabled}
            className={`cyber-cta inline-flex items-center justify-center gap-1.5 font-cyber-ui font-semibold uppercase tracking-wider ${sizeClass} ${fxClass} ${className}`.trim()}
            {...rest}
          >
            {children}
          </button>
        </span>
      );
    }

    const variantClass =
      variant === "tactical"
        ? `cyber-btn-tac justify-center font-cyber-ui font-medium ${active ? "is-active" : ""}`
        : variant === "utility"
          ? `cyber-btn-util justify-center font-cyber-ui font-medium ${active ? "is-active" : ""}`
          : variant === "danger"
          ? `inline-flex items-center justify-center gap-1.5 border font-cyber-ui font-semibold transition-colors disabled:opacity-45 disabled:cursor-not-allowed ${
              active
                ? "border-[var(--hud-primary-bright)] bg-[var(--hud-primary)] text-white"
                : "border-[var(--hud-primary)]/70 bg-[#5a0b1c]/60 text-rose-100 hover:border-[var(--hud-primary-bright)] hover:bg-[var(--hud-primary)] hover:text-white"
            }`
          : `inline-flex items-center justify-center gap-1.5 border font-cyber-ui font-medium transition-colors disabled:opacity-45 disabled:cursor-not-allowed ${
              active
                ? "border-[var(--hud-accent-line)] bg-[var(--hud-accent-navy)] text-[var(--hud-accent)]"
                : "border-transparent text-[var(--hud-muted)] hover:border-[var(--hud-line-soft)] hover:text-[var(--hud-text)]"
            }`;

    return (
      <button
        ref={ref}
        type={type}
        disabled={disabled}
        className={`${variantClass} ${sizeClass} ${fxClass} ${className}`.trim()}
        {...rest}
      >
        {children}
      </button>
    );
  },
);
