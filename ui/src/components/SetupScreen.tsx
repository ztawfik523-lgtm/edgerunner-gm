import { BookOpen, Cpu, LogIn, LogOut } from "lucide-react";
import type { AuthStatus, HealthStatus } from "../types";
import { CyberFrame, HudButton } from "./cyber";

interface SetupScreenProps {
  health: HealthStatus | null;
  /** Admin/host who may configure the AI connection and upload the Corebook. */
  canUpload: boolean;
  authStatus: AuthStatus | null;
  onOpenConnection: () => void;
  onOpenCorebook: () => void;
  onOpenAuth: () => void;
  onSignOut: () => void;
}

/**
 * Shown until the server reports an indexed Corebook. The app is not playable
 * without the user's own Corebook PDF, so only sign-in, the AI connection and
 * the Corebook upload are reachable from here.
 */
export function SetupScreen({
  health,
  canUpload,
  authStatus,
  onOpenConnection,
  onOpenCorebook,
  onOpenAuth,
  onSignOut,
}: SetupScreenProps) {
  const signedIn = Boolean(authStatus?.auth_enabled && authStatus.authenticated && authStatus.username);

  return (
    <main className="flex flex-1 items-center justify-center overflow-y-auto p-4 sm:p-8">
      <CyberFrame variant="hex" className="relative w-full max-w-xl p-6 sm:p-8">
        <div className="flex flex-col gap-4">
          <span className="inline-flex w-fit items-center gap-1.5 border border-[var(--hud-line)] bg-[var(--hud-row)] px-2.5 py-0.5 font-cyber-data text-[10px] font-semibold uppercase tracking-[0.2em] text-[var(--hud-label)]">
            <span className="cp-pulse h-1.5 w-1.5 bg-[var(--hud-primary-bright)]" />
            Setup required
          </span>
          <h1 className="font-cyber-display text-xl font-bold uppercase tracking-[0.1em] text-[var(--hud-text)]">
            Bring your own Corebook
          </h1>
          {!health ? (
            <p className="font-cyber-ui text-sm text-[var(--hud-muted)]">Connecting to the GM server...</p>
          ) : canUpload ? (
            <p className="font-cyber-ui text-sm leading-relaxed text-[var(--hud-muted)]">
              Edgerunner GM runs on your own copy of the Cyberpunk RED Corebook. Connect your AI model, then
              upload the Corebook PDF. The file stays on your server; play unlocks as soon as indexing finishes.
            </p>
          ) : (
            <p className="font-cyber-ui text-sm leading-relaxed text-[var(--hud-muted)]">
              The host has not uploaded the Cyberpunk RED Corebook PDF yet. This page unlocks automatically
              once it is indexed.
            </p>
          )}

          <div className="flex flex-wrap gap-2">
            {canUpload && (
              <>
                <HudButton variant="cta" size="md" onClick={onOpenCorebook}>
                  <BookOpen className="h-3.5 w-3.5" />
                  Upload Corebook PDF
                </HudButton>
                <HudButton variant="tactical" size="md" onClick={onOpenConnection}>
                  <Cpu className="h-3.5 w-3.5" />
                  AI Connection
                </HudButton>
              </>
            )}
            {signedIn ? (
              <HudButton variant="ghost" size="md" onClick={onSignOut}>
                <LogOut className="h-3.5 w-3.5" />
                Sign out {authStatus?.username}
              </HudButton>
            ) : (
              !canUpload && (
                <HudButton variant="ghost" size="md" onClick={onOpenAuth}>
                  <LogIn className="h-3.5 w-3.5" />
                  Admin sign-in
                </HudButton>
              )
            )}
          </div>
        </div>
      </CyberFrame>
    </main>
  );
}
