import type { HTMLAttributes } from "react";

export type HazardBadgeTone = "warn" | "danger" | "accent";

export interface HazardBadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: HazardBadgeTone;
}

const TONE_CLASSES: Record<HazardBadgeTone, string> = {
  warn: "border-[var(--hud-warn)]/60 text-[var(--hud-warn)]",
  danger: "border-[var(--hud-primary-bright)]/70 text-[var(--hud-primary-bright)]",
  accent: "border-[var(--hud-accent-line)] text-[var(--hud-accent)]",
};

/**
 * Compact diagonal-striped hazard badge or alert strip.
 */
export function HazardBadge({
  tone = "warn",
  className = "",
  children,
  ...rest
}: HazardBadgeProps) {
  return (
    <span
      className={`cyber-hazard-thin inline-flex items-center gap-1.5 border px-2 py-0.5 font-cyber-data text-[10px] font-semibold uppercase tracking-widest ${TONE_CLASSES[tone]} ${className}`.trim()}
      {...rest}
    >
      {children}
    </span>
  );
}
