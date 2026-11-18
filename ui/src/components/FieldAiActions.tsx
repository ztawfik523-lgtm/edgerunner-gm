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
  const padClass = compact ? "px-1.5 py-0.5 text-[10px]" : "px-2 py-0.5 text-[10px]";
  return (
    <div className="inline-flex shrink-0 items-center gap-1">
      <button
        type="button"
        disabled={disabled}
        onClick={onImprove}
        title={`Improve ${label}`}
        aria-label={`Improve ${label}`}
        className={`inline-flex items-center gap-1 rounded border border-amber-500/40 bg-amber-500/10 ${padClass} font-semibold text-amber-200 transition hover:border-amber-400/70 hover:bg-amber-500/20 disabled:opacity-45`}
      >
        <Wand2 className="h-2.5 w-2.5" />
        <span>{busyAction === "improve" ? "Improving…" : "Improve"}</span>
      </button>
      <button
        type="button"
        disabled={disabled}
        onClick={onRegen}
        title={`Regenerate ${label}`}
        aria-label={`Regenerate ${label}`}
        className={`inline-flex items-center gap-1 rounded border border-cyan-500/40 bg-cyan-500/10 ${padClass} font-semibold text-cyan-200 transition hover:border-cyan-400/70 hover:bg-cyan-500/20 disabled:opacity-45`}
      >
        <RefreshCw className={`h-2.5 w-2.5 ${busyAction === "regen" ? "animate-spin" : ""}`} />
        <span>{busyAction === "regen" ? "Regen…" : "Regen"}</span>
      </button>
    </div>
  );
}
