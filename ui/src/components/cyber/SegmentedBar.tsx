import type { HTMLAttributes } from "react";

export type SegmentedBarTone = "primary" | "accent" | "warn" | "ok";

export interface SegmentedBarProps extends HTMLAttributes<HTMLDivElement> {
  value: number;
  max: number;
  segments?: number;
  tone?: SegmentedBarTone;
  thresholdRatio?: number;
  heightClass?: string;
}

const TONE_CLASSES: Record<SegmentedBarTone, string> = {
  primary: "bg-[var(--hud-primary-bright)]",
  accent: "bg-[var(--hud-accent)]",
  warn: "bg-[var(--hud-warn)]",
  ok: "bg-[var(--hud-ok)]",
};

/**
 * Segmented Cyberpunk telemetry bar for HP, Humanity, Luck, and World Clocks.
 */
export function SegmentedBar({
  value,
  max,
  segments,
  tone = "primary",
  thresholdRatio,
  heightClass = "h-1.5",
  className = "",
  ...rest
}: SegmentedBarProps) {
  const safeMax = max > 0 ? max : 1;
  const segmentCount = Math.max(
    1,
    Math.round(segments ?? (safeMax <= 12 ? safeMax : 20)),
  );
  const clamped = Math.max(0, Math.min(safeMax, value));
  const filledCount =
    clamped > 0
      ? Math.max(1, Math.min(segmentCount, Math.round((clamped / safeMax) * segmentCount)))
      : 0;
  const fillClass = TONE_CLASSES[tone];
  const hasLabel = Boolean(rest["aria-label"] || rest["aria-labelledby"]);

  return (
    <div
      {...(hasLabel
        ? {
            role: "progressbar",
            "aria-valuenow": clamped,
            "aria-valuemin": 0,
            "aria-valuemax": safeMax,
          }
        : {})}
      className={`relative grid gap-0.5 py-0.5 ${className}`.trim()}
      style={{ gridTemplateColumns: `repeat(${segmentCount}, minmax(0, 1fr))` }}
      {...rest}
    >
      {Array.from({ length: segmentCount }, (_, idx) => (
        <div
          key={idx}
          className={`${heightClass} ${idx < filledCount ? fillClass : "bg-white/10"}`}
        />
      ))}
      {thresholdRatio !== undefined ? (
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 w-[1.5px] bg-[var(--hud-warn)]"
          style={{ left: `${Math.min(100, Math.max(0, thresholdRatio * 100))}%` }}
        />
      ) : null}
    </div>
  );
}
