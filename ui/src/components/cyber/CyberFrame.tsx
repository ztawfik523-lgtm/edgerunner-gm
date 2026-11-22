import { forwardRef, type HTMLAttributes, type ReactNode } from "react";

export type CyberFrameVariant = "default" | "hex" | "row" | "modal";

export interface CyberFrameProps extends HTMLAttributes<HTMLDivElement> {
  variant?: CyberFrameVariant;
  header?: ReactNode;
  cornerTicks?: boolean;
}

const VARIANT_CLASSES: Record<CyberFrameVariant, string> = {
  default: "cyber-glass-panel",
  hex: "cyber-glass-panel isolate overflow-hidden",
  row: "border border-[var(--hud-line-soft)] bg-[var(--hud-row)]",
  modal: "cyber-glass-panel bg-[var(--hud-panel)] shadow-2xl",
};

/**
 * Reusable Cyberpunk HUD glass container with optional hex telemetry backdrop,
 * header strip, and 2px crimson L-corner ticks.
 */
export const CyberFrame = forwardRef<HTMLDivElement, CyberFrameProps>(
  function CyberFrame(
    { variant = "default", header, cornerTicks = true, className = "", children, ...rest },
    ref,
  ) {
    const tickClass = variant !== "row" && !cornerTicks ? "cyber-no-ticks" : "";

    return (
      <div
        ref={ref}
        className={`${VARIANT_CLASSES[variant]} ${tickClass} ${className}`.trim()}
        {...rest}
      >
        {variant === "hex" ? (
          <div
            aria-hidden="true"
            className="cyber-hex-overlay pointer-events-none absolute inset-0 -z-10 opacity-55"
          />
        ) : null}
        {header ? (
          <div className="border-b border-[var(--hud-line-soft)] bg-[var(--hud-row)] px-4 py-2">
            {header}
          </div>
        ) : null}
        {children}
      </div>
    );
  },
);
