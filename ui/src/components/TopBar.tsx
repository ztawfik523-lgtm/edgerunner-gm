import {
  AlertTriangle,
  BookOpen,
  Globe,
  LogOut,
  Settings,
  Shield,
  UserCheck,
  Users,
} from "lucide-react";
import type { AuthStatus, HealthStatus, LLMSettings } from "../types";

interface TopBarProps {
  health: HealthStatus | null;
  llmSettings: LLMSettings | null;
  revisionMismatch: boolean;
  coopCount: number;
  authStatus?: AuthStatus | null;
  viewAsUser?: boolean;
  onToggleViewAsUser?: () => void;
  onSyncRevisions?: () => Promise<void>;
  onOpenCoop: () => void;
  onOpenSettings: () => void;
  onOpenCorebookSettings?: () => void;
  onOpenAuth?: () => void;
  onSignOut?: () => void;
}

export function TopBar({
  health,
  llmSettings,
  revisionMismatch,
  coopCount,
  authStatus,
  viewAsUser = false,
  onToggleViewAsUser,
  onSyncRevisions,
  onOpenCoop,
  onOpenSettings,
  onOpenCorebookSettings,
  onOpenAuth,
  onSignOut,
}: TopBarProps) {
  const isTrueAdmin =
    !authStatus ||
    !authStatus.auth_enabled ||
    authStatus.role === "admin" ||
    authStatus.role === "open";
  const canAdminSettings = isTrueAdmin && !viewAsUser;

  return (
    <header className="shrink-0 border-b border-[var(--hud-line)] bg-[var(--hud-panel)] backdrop-blur-md shadow-[0_4px_24px_rgba(0,0,0,0.45)]">
      <div className="flex flex-nowrap items-center justify-between gap-1.5 px-2 py-1 sm:px-3 sm:py-1.5">
        {/* Left: Compact Brand */}
        <div className="flex shrink-0 items-center gap-1.5">
          <div className="flex items-center gap-2 border border-[var(--hud-line)] bg-[var(--hud-row)] px-2.5 py-0.5">
            <span className="cp-pulse h-1.5 w-1.5 shrink-0 bg-[var(--hud-primary-bright)]" />
            <span
              data-text="Cyberpunk RED"
              className="cp-glitch font-cyber-display text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--hud-text)]"
            >
              <span className="sm:hidden">CP:RED</span>
              <span className="hidden sm:inline">Cyberpunk RED</span>
            </span>
          </div>
        </div>

        {/* Right: Utilities & Status */}
        <div className="flex min-w-0 items-center gap-1 overflow-x-auto sm:gap-1.5">
          <button
            type="button"
            onClick={onOpenCoop}
            title="Party players & LAN hosting"
            className={`cyber-btn-tac cp-fx-hover shrink-0 px-2 py-1 text-[11px] font-medium sm:px-2.5 sm:text-xs ${
              health?.lan_enabled
                ? "border-[var(--hud-ok)]/60 text-[var(--hud-ok)]"
                : ""
            }`}
          >
            {health?.lan_enabled ? (
              <Globe className="h-3.5 w-3.5 text-[var(--hud-ok)]" />
            ) : (
              <Users className="h-3.5 w-3.5 text-[var(--hud-accent)]" />
            )}
            <span>Party</span>
            {coopCount > 0 && (
              <span className="border border-[var(--hud-accent-line)]/50 bg-[var(--hud-accent-navy)] px-1.5 font-cyber-data text-[10px] text-[var(--hud-accent)]">
                {coopCount}
              </span>
            )}
          </button>

          <button
            type="button"
            onClick={onOpenSettings}
            title={
              canAdminSettings
                ? llmSettings?.model
                  ? `Settings (Model: ${llmSettings.model})`
                  : "Settings"
                : "Display & Account Settings"
            }
            className="cyber-btn-tac cp-fx-hover shrink-0 px-2 py-1 text-xs font-medium sm:px-2.5"
          >
            <Settings className="h-3.5 w-3.5 text-[var(--hud-accent)]" />
            <span className="hidden sm:inline">Settings</span>
          </button>

          {isTrueAdmin && onToggleViewAsUser && (
            <button
              type="button"
              onClick={onToggleViewAsUser}
              aria-label={
                viewAsUser
                  ? "Player Mode (Switch to Admin)"
                  : "Switch to Player Mode"
              }
              title={
                viewAsUser
                  ? "Currently previewing as a Player (GM secrets & admin controls hidden). Click to switch back to Admin."
                  : "Switch to Player view without signing out (hides GM secrets & admin controls)."
              }
              className={`cyber-btn-tac cp-fx-hover shrink-0 justify-center p-1 sm:p-1.5 ${
                viewAsUser
                  ? "border-[var(--hud-warn)]/70 bg-[var(--hud-warn)]/15 text-[var(--hud-warn)]"
                  : ""
              }`}
            >
              {viewAsUser ? (
                <UserCheck className="h-3.5 w-3.5 text-[var(--hud-warn)]" />
              ) : (
                <Shield className="h-3.5 w-3.5 text-[var(--hud-primary-bright)]" />
              )}
            </button>
          )}

          {authStatus?.auth_enabled && (authStatus.role === "admin" || authStatus.role === "user") && (
            <div className="inline-flex shrink-0 items-center gap-1 border border-[var(--hud-line)] bg-black/40 px-2 py-1 text-[11px] text-[var(--hud-text)] sm:px-2.5">
              {authStatus.role === "admin" && !viewAsUser ? (
                <Shield className="h-3 w-3 shrink-0 text-[var(--hud-primary-bright)]" aria-hidden="true" />
              ) : (
                <UserCheck className="h-3 w-3 shrink-0 text-[var(--hud-accent)]" aria-hidden="true" />
              )}
              <span className="max-w-[68px] truncate font-semibold text-[var(--hud-accent)] sm:max-w-[110px]">
                {authStatus.username || (authStatus.role === "admin" ? "Admin" : "Player")}
              </span>
              {authStatus.role === "user" && onOpenAuth && (
                <button
                  type="button"
                  onClick={onOpenAuth}
                  className="ml-1 border border-[var(--hud-warn)]/40 bg-[var(--hud-warn)]/10 px-1.5 py-0.5 text-[10px] text-[var(--hud-warn)] hover:bg-[var(--hud-warn)]/20"
                >
                  Admin Login
                </button>
              )}
              {onSignOut && (
                <button
                  type="button"
                  onClick={onSignOut}
                  title="Sign out"
                  aria-label="Sign out"
                  className="ml-0.5 p-0.5 text-[var(--hud-muted)] hover:text-[var(--hud-primary-bright)]"
                >
                  <LogOut className="h-3 w-3" />
                </button>
              )}
            </div>
          )}

          {authStatus && !authStatus.auth_enabled && authStatus.can_bootstrap && onOpenAuth && (
            <button
              type="button"
              onClick={onOpenAuth}
              title="Enable Admin & Player sign-in accounts"
              className="cyber-btn-tac cp-fx-hover shrink-0 px-2 py-1 text-[11px] font-medium"
            >
              <Shield className="h-3 w-3 text-[var(--hud-warn)]" />
              <span className="hidden sm:inline">Accounts</span>
            </button>
          )}

          {health && !health.rules_indexed && (
            canAdminSettings && onOpenCorebookSettings ? (
              <button
                type="button"
                onClick={onOpenCorebookSettings}
                title="Upload your Cyberpunk RED Corebook PDF under Settings -> BYOC (Freeform & Homebrew play works without it)"
                className="cyber-btn-tac cp-fx-hover shrink-0 border-[var(--hud-warn)]/50 px-2 py-1 text-[11px] font-medium text-[var(--hud-warn)]"
              >
                <BookOpen className="h-3 w-3 text-[var(--hud-warn)]" />
                <span className="hidden sm:inline">No BYOC</span>
              </button>
            ) : (
              <span
                title={health.detail ?? "No Corebook uploaded yet (Homebrew & Freeform play still active)"}
                className="inline-flex shrink-0 items-center gap-1 border border-[var(--hud-warn)]/50 bg-[var(--hud-row)] px-2 py-1 text-[11px] text-[var(--hud-warn)]"
              >
                <BookOpen className="h-3 w-3" />
                <span className="hidden sm:inline">No BYOC</span>
              </span>
            )
          )}
        </div>
      </div>

      {revisionMismatch && (
        <div className="cyber-hazard-thin flex flex-wrap items-center justify-between gap-2 border-t border-[var(--hud-warn)]/50 bg-black/60 px-4 py-1 text-[11px] text-[var(--hud-warn)]">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
            <span>
              Branch State Differs — this chat branch points to an earlier game-state revision than your live character/campaign sheet.
            </span>
          </div>
          {onSyncRevisions && (
            <button
              type="button"
              onClick={() => void onSyncRevisions()}
              className="cyber-btn-tac cp-fx-hover border-[var(--hud-warn)]/60 px-2 py-0.5 text-[10px] font-semibold text-[var(--hud-warn)]"
            >
              Sync Branch State
            </button>
          )}
        </div>
      )}
    </header>
  );
}
