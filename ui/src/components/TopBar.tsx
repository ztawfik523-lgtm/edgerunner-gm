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
    <header className="shrink-0 border-b border-rose-500/25 bg-[#0b0f18]/92 backdrop-blur-md shadow-[0_4px_24px_rgba(0,0,0,0.45)]">
      <div className="flex flex-nowrap items-center justify-between gap-1.5 px-2 py-1 sm:px-3 sm:py-1.5">
        {/* Left: Compact Brand */}
        <div className="flex shrink-0 items-center gap-1.5">
          <div className="cyber-cut-sm cyber-brand-badge flex items-center gap-1.5 border border-rose-500/50 bg-gradient-to-r from-rose-600/25 via-rose-950/35 to-cyan-950/30 px-1.5 py-0.5 sm:px-2">
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-rose-500 shadow-[0_0_8px_#f43f5e]" />
            <span
              data-text="Cyberpunk RED"
              className="cyber-glitch-title font-cyber-display text-[10px] font-bold tracking-[0.12em] text-rose-200 uppercase"
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
            className={`inline-flex shrink-0 items-center gap-1 rounded-md border px-1.5 py-1 text-[11px] transition sm:gap-1.5 sm:px-2 sm:text-xs ${
              health?.lan_enabled
                ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20"
                : "border-slate-700 bg-slate-900 text-slate-200 hover:border-cyan-500/60"
            }`}
          >
            {health?.lan_enabled ? <Globe className="h-3.5 w-3.5" /> : <Users className="h-3.5 w-3.5 text-cyan-400" />}
            <span>Party</span>
            {coopCount > 0 && (
              <span className="rounded-full bg-slate-800 px-1.5 font-mono text-[10px] text-cyan-300">
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
            className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-slate-700 bg-slate-900 px-1.5 py-1 text-xs font-medium text-slate-200 transition hover:border-cyan-500/60 hover:text-cyan-200 sm:px-2"
          >
            <Settings className="h-3.5 w-3.5 text-cyan-400" />
            <span className="font-cyber-hud tracking-wide hidden sm:inline">Settings</span>
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
              className={`inline-flex shrink-0 items-center justify-center rounded-md border p-1 transition sm:p-1.5 ${
                viewAsUser
                  ? "border-amber-400/70 bg-amber-500/20 text-amber-200 hover:bg-amber-500/30"
                  : "border-rose-500/45 bg-rose-500/10 text-rose-200 hover:border-rose-400 hover:bg-rose-500/20"
              }`}
            >
              {viewAsUser ? (
                <UserCheck className="h-3.5 w-3.5 text-amber-300" />
              ) : (
                <Shield className="h-3.5 w-3.5 text-rose-400" />
              )}
            </button>
          )}

          {authStatus?.auth_enabled && (authStatus.role === "admin" || authStatus.role === "user") && (
            <div className="inline-flex shrink-0 items-center gap-1 rounded-md border border-slate-700 bg-slate-900 px-1.5 py-1 text-[11px] sm:px-2">
              {authStatus.role === "admin" && !viewAsUser ? (
                <Shield className="h-3 w-3 shrink-0 text-rose-400" aria-hidden="true" />
              ) : (
                <UserCheck className="h-3 w-3 shrink-0 text-cyan-400" aria-hidden="true" />
              )}
              <span className="max-w-[68px] truncate font-semibold text-slate-200 sm:max-w-[110px]">
                {authStatus.username || (authStatus.role === "admin" ? "Admin" : "Player")}
              </span>
              {authStatus.role === "user" && onOpenAuth && (
                <button
                  type="button"
                  onClick={onOpenAuth}
                  className="ml-1 rounded px-1 text-[10px] text-amber-300 hover:bg-slate-800"
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
                  className="ml-0.5 rounded p-0.5 text-slate-400 hover:bg-slate-800 hover:text-rose-300"
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
              className="inline-flex items-center gap-1 rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-[11px] text-slate-300 hover:border-cyan-500/60 hover:text-cyan-200"
            >
              <Shield className="h-3 w-3 text-amber-400" />
              <span className="hidden sm:inline">Accounts</span>
            </button>
          )}

          {health && !health.rules_indexed && (
            canAdminSettings && onOpenCorebookSettings ? (
              <button
                type="button"
                onClick={onOpenCorebookSettings}
                title="BYOC Required: Upload your Corebook PDF in Settings -> BYOC"
                className="inline-flex items-center gap-1 rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-[11px] text-amber-200 hover:bg-amber-500/20"
              >
                <BookOpen className="h-3 w-3" />
                <span className="hidden sm:inline">No BYOC</span>
              </button>
            ) : (
              <span
                title={health.detail ?? "BYOC Required: Upload your Corebook PDF in Settings -> BYOC"}
                className="inline-flex items-center gap-1 rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-[11px] text-amber-200"
              >
                <BookOpen className="h-3 w-3" />
                <span className="hidden sm:inline">No BYOC</span>
              </span>
            )
          )}
        </div>
      </div>

      {revisionMismatch && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-amber-500/30 bg-amber-500/10 px-4 py-1 text-[11px] text-amber-300">
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
              className="rounded border border-amber-400/50 bg-amber-500/20 px-2 py-0.5 font-mono text-[10px] font-semibold text-amber-100 hover:bg-amber-500/30"
            >
              Sync Branch State
            </button>
          )}
        </div>
      )}
    </header>
  );
}
