import { RefreshCw, Wand2 } from "lucide-react";

interface FieldAiActionsProps {
  label: string;
  disabled?: boolean;
  busyAction?: "improve" | "regen" | null;
  onImprove: () => void;
  onRegen: () => void;
  compact?: boolean;
}

export function FieldAiActions({
  label,
  disabled = false,
  busyAction = null,
  onImprove,
  onRegen,
  compact = false,
}: FieldAiActionsProps) {
  const padClass = compact ? "p-1" : "p-1.5";
  const iconClass = compact ? "h-2.5 w-2.5" : "h-3 w-3";
  return (
    <div className="inline-flex shrink-0 items-center gap-1">
      <button
        type="button"
        disabled={disabled}
        onClick={onImprove}
        title={`Improve ${label}`}
        aria-label={`Improve ${label}`}
        className={`inline-flex items-center justify-center border border-[var(--hud-warn)]/45 bg-[var(--hud-warn)]/10 ${padClass} text-[var(--hud-warn)] transition hover:border-[var(--hud-warn)] hover:bg-[var(--hud-warn)]/20 disabled:opacity-45`}
      >
        <Wand2 className={`${iconClass} ${busyAction === "improve" ? "animate-pulse" : ""}`} />
      </button>
      <button
        type="button"
        disabled={disabled}
        onClick={onRegen}
        title={`Regenerate ${label}`}
        aria-label={`Regenerate ${label}`}
        className={`inline-flex items-center justify-center border border-[var(--hud-accent-line)]/50 bg-[var(--hud-accent-navy)] ${padClass} text-[var(--hud-accent)] transition hover:border-[var(--hud-accent-line)] disabled:opacity-45`}
      >
        <RefreshCw className={`${iconClass} ${busyAction === "regen" ? "animate-spin" : ""}`} />
      </button>
    </div>
  );
}
