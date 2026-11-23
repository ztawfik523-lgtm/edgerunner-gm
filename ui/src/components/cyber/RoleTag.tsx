import type { HTMLAttributes } from "react";

export type RoleTagTone = "warn" | "accent" | "muted";

export interface RoleTagProps extends HTMLAttributes<HTMLSpanElement> {
  role?: string;
  rank?: number | string | null;
  separator?: string;
  tone?: RoleTagTone;
}

const TONE_CLASSES: Record<RoleTagTone, string> = {
  warn: "text-[var(--hud-warn)]",
  accent: "text-[var(--hud-accent)]",
  muted: "text-[var(--hud-muted)]",
};

/**
 * Bracketed telemetry badge for Cyberpunk roles and ranks (e.g. [MEDTECH · R4]).
 */
export function RoleTag({
  role,
  rank,
  separator = " · ",
  tone = "accent",
  className = "",
  children,
  ...rest
}: RoleTagProps) {
  let content = children;

  if (content === undefined || content === null) {
    const cleanRole = role?.trim();
    const rawRank = rank !== undefined && rank !== null ? String(rank).trim() : "";
    const cleanRank = rawRank
      ? rawRank.toUpperCase().startsWith("R")
        ? rawRank
        : `R${rawRank}`
      : "";
    const joined = [cleanRole, cleanRank].filter(Boolean).join(separator);
    if (!joined) return null;
    content = `[${joined}]`;
  }

  return (
    <span
      className={`font-cyber-data text-[10px] uppercase tracking-wider ${TONE_CLASSES[tone]} ${className}`.trim()}
      {...rest}
    >
      {content}
    </span>
  );
}
