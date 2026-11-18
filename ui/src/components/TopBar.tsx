import { useState } from "react";
import {
  AlertTriangle,
  BookOpen,
  Cpu,
  Download,
  Globe,
  LogOut,
  Plus,
  Search,
  Shield,
  Sparkles,
  UserCheck,
  Users,
  Wifi,
  WifiOff,
} from "lucide-react";
import type { AuthStatus, CampaignRecord, HealthStatus, LLMSettings } from "../types";

interface TopBarProps {
  health: HealthStatus | null;
  campaigns: CampaignRecord[];
  activeCampaign: CampaignRecord | null;
  llmSettings: LLMSettings | null;
  revisionMismatch: boolean;
  coopCount: number;
  authStatus?: AuthStatus | null;
  onSelectCampaign: (id: string) => void;
  onCreateCampaign: (name: string) => Promise<void>;
  onOpenNewCampaign?: () => void;
  onStartSession: () => Promise<void>;
  onExportChat: () => Promise<void>;
  onOpenCoop: () => void;
  onOpenSettings: () => void;
  onOpenCorebookSettings?: () => void;
  onToggleThinkingMode?: (mode: "quality" | "balanced") => Promise<void>;
  onOpenSearch: () => void;
  onOpenAuth?: () => void;
  onSignOut?: () => void;
}

export function TopBar({
  health,
  campaigns,
  activeCampaign,
  llmSettings,
  revisionMismatch,
  coopCount,
  authStatus,
  onSelectCampaign,
  onCreateCampaign,
  onOpenNewCampaign,
  onStartSession,
  onExportChat,
  onOpenCoop,
  onOpenSettings,
  onOpenCorebookSettings,
  onToggleThinkingMode,
  onOpenSearch,
  onOpenAuth,
  onSignOut,
}: TopBarProps) {
  const canAdminSettings =
    !authStatus ||
    !authStatus.auth_enabled ||
    authStatus.role === "admin" ||
    authStatus.role === "open";
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState(false);
  const [startingSession, setStartingSession] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [switchingMode, setSwitchingMode] = useState(false);

  const handleSwitchThinkingMode = async (next: "quality" | "balanced") => {
    if (!onToggleThinkingMode || switchingMode) return;
    if ((llmSettings?.gm_thinking_mode ?? "quality") === next) return;
    setSwitchingMode(true);
    try {
      await onToggleThinkingMode(next);
    } finally {
      setSwitchingMode(false);
    }
  };

  const handleStartSession = async () => {
    if (startingSession) return;
    setStartingSession(true);
    try {
      await onStartSession();
    } finally {
      setStartingSession(false);
    }
  };

  const handleExport = async () => {
    if (exporting) return;
    setExporting(true);
    try {
      await onExportChat();
    } finally {
      setExporting(false);
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = newName.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    try {
      await onCreateCampaign(trimmed);
      setNewName("");
      setCreating(false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <header className="border-b border-rose-500/25 bg-[#0b0f18]/92 backdrop-blur-md shadow-[0_4px_24px_rgba(0,0,0,0.45)]">
      <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 lg:px-4">
        {/* Left: Brand + Campaign Selector */}
        <div className="flex flex-wrap items-center gap-2">
          <div className="cyber-cut-sm cyber-brand-badge flex items-center gap-2 border border-rose-500/50 bg-gradient-to-r from-rose-600/25 via-rose-950/35 to-cyan-950/30 px-3 py-1">
            <span className="h-2 w-2 rounded-full bg-rose-500 shadow-[0_0_8px_#f43f5e]" />
            <span
              data-text="Cyberpunk RED GM"
              className="cyber-glitch-title font-cyber-display text-[11px] font-bold tracking-[0.14em] text-rose-200 uppercase"
            >
              Cyberpunk RED GM
            </span>
          </div>

          <div className="flex items-center gap-1.5">
            <select
              aria-label="Active campaign"
              value={activeCampaign?.id ?? ""}
              onChange={(e) => e.target.value && onSelectCampaign(e.target.value)}
              className="max-w-[230px] rounded-md border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
            >
              {campaigns.length === 0 && <option value="">No campaigns yet</option>}
              {campaigns.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.is_primary ? "★ " : ""}{c.name} (Session {c.session_number})
                </option>
              ))}
            </select>

            {creating ? (
              <form onSubmit={handleCreate} className="flex items-center gap-1">
                <input
                  autoFocus
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Escape") {
                      setCreating(false);
                      setNewName("");
                    }
                  }}
                  placeholder="Campaign name..."
                  className="w-36 rounded-md border border-cyan-500/60 bg-slate-950 px-2 py-1 text-xs text-slate-100 focus:outline-none"
                />
                <button
                  type="submit"
                  disabled={busy}
                  className="rounded-md bg-cyan-600 px-2 py-1 text-xs font-semibold text-white hover:bg-cyan-500 disabled:opacity-50"
                >
                  Create
                </button>
                <button
                  type="button"
                  onClick={() => setCreating(false)}
                  className="rounded-md px-1.5 py-1 text-xs text-slate-400 hover:text-slate-200"
                >
                  Cancel
                </button>
              </form>
            ) : (
              <button
                type="button"
                onClick={() => (onOpenNewCampaign ? onOpenNewCampaign() : setCreating(true))}
                title="Open Campaign Architect"
                className="inline-flex items-center gap-1 rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs font-medium text-slate-200 hover:border-cyan-500/60 hover:text-cyan-300"
              >
                <Plus className="h-3.5 w-3.5" />
                New
              </button>
            )}
          </div>

          {activeCampaign && (
            <button
              type="button"
              disabled={startingSession}
              onClick={() => void handleStartSession()}
              title="Start next session and refill all party LUCK"
              className="inline-flex items-center gap-1 rounded-md border border-amber-500/40 bg-amber-500/10 px-2.5 py-1 text-xs font-medium text-amber-300 hover:bg-amber-500/20 disabled:opacity-50"
            >
              <Sparkles className="h-3.5 w-3.5" />
              {startingSession ? "Starting..." : "Start Session"}
            </button>
          )}
        </div>

        {/* Right: Utilities & Status */}
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={onOpenSearch}
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs text-slate-300 hover:border-cyan-500/60 hover:text-cyan-200"
          >
            <Search className="h-3.5 w-3.5 text-cyan-400" />
            <span>Rulebook Search</span>
            <kbd className="hidden sm:inline rounded bg-slate-800 px-1 py-0.5 font-mono text-[10px] text-slate-400">
              Ctrl+K
            </kbd>
          </button>

          <button
            type="button"
            onClick={onOpenCoop}
            title="Co-op players & LAN hosting"
            className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs transition ${
              health?.lan_enabled
                ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20"
                : "border-slate-700 bg-slate-900 text-slate-200 hover:border-cyan-500/60"
            }`}
          >
            {health?.lan_enabled ? <Globe className="h-3.5 w-3.5" /> : <Users className="h-3.5 w-3.5 text-cyan-400" />}
            <span>Co-op</span>
            {coopCount > 0 && (
              <span className="rounded-full bg-slate-800 px-1.5 font-mono text-[10px] text-cyan-300">
                {coopCount}
              </span>
            )}
          </button>

          {activeCampaign && (
            <button
              type="button"
              disabled={exporting}
              onClick={() => void handleExport()}
              title="Export active story log as Markdown"
              className="inline-flex items-center gap-1 rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-300 hover:border-cyan-500/60 hover:text-cyan-200 disabled:opacity-50"
            >
              <Download className="h-3.5 w-3.5 text-slate-400" />
              <span className="hidden xl:inline">{exporting ? "Exporting..." : "Export"}</span>
            </button>
          )}

          {canAdminSettings && llmSettings && onToggleThinkingMode && (
            <div
              role="group"
              aria-label="GM thinking mode"
              className="inline-flex items-center rounded-md border border-slate-700 bg-slate-900 p-0.5 text-[11px]"
            >
              {(["quality", "balanced"] as const).map((modeKey) => {
                const active = (llmSettings.gm_thinking_mode ?? "quality") === modeKey;
                const label = modeKey === "quality" ? "GM Quality" : "GM Balanced";
                const tip =
                  modeKey === "quality"
                    ? "GM Quality: Thinking ON for all 3 steps (strictest accuracy & cleanest prose)"
                    : "GM Balanced: Same writing, less waiting — Thinking ON for rules/dice, OFF for story & memory";
                return (
                  <button
                    key={modeKey}
                    type="button"
                    disabled={switchingMode}
                    aria-pressed={active}
                    title={tip}
                    onClick={() => void handleSwitchThinkingMode(modeKey)}
                    className={`rounded px-2 py-0.5 font-medium transition disabled:opacity-50 ${
                      active
                        ? modeKey === "quality"
                          ? "bg-cyan-500/20 text-cyan-200"
                          : "bg-amber-500/20 text-amber-200"
                        : "text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          )}

          {canAdminSettings && (
            <button
              type="button"
              onClick={onOpenSettings}
              className="inline-flex items-center gap-1.5 rounded-md border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs text-slate-200 hover:border-cyan-500/60"
            >
              <Cpu className="h-3.5 w-3.5 text-cyan-400" />
              <span className="max-w-[120px] truncate font-mono">
                {llmSettings?.model ?? "Configure AI"}
              </span>
            </button>
          )}

          {authStatus?.auth_enabled && (authStatus.role === "admin" || authStatus.role === "user") && (
            <div className="inline-flex items-center gap-1 rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-[11px]">
              {authStatus.role === "admin" ? (
                <Shield className="h-3 w-3 text-rose-400" />
              ) : (
                <UserCheck className="h-3 w-3 text-cyan-400" />
              )}
              <span className="font-semibold text-slate-200">
                {authStatus.role === "admin" ? "ADMIN" : "USER"}
              </span>
              {authStatus.username && (
                <span className="hidden lg:inline text-slate-400">({authStatus.username})</span>
              )}
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
                title="Upload your Cyberpunk RED Corebook PDF in Settings (Freeform & Homebrew play works without it)"
                className="inline-flex items-center gap-1 rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-[11px] text-amber-200 hover:bg-amber-500/20"
              >
                <BookOpen className="h-3 w-3" />
                <span className="hidden sm:inline">No Corebook PDF</span>
              </button>
            ) : (
              <span
                title={health.detail ?? "No Corebook uploaded yet (Homebrew & Freeform play still active)"}
                className="inline-flex items-center gap-1 rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-[11px] text-amber-200"
              >
                <BookOpen className="h-3 w-3" />
                <span className="hidden sm:inline">No Corebook PDF</span>
              </span>
            )
          )}

          <span
            title={health?.status === "ok" ? "Backend online" : "Backend unreachable"}
            className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-mono ${
              health?.status === "ok"
                ? "border border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                : "border border-rose-500/30 bg-rose-500/10 text-rose-300"
            }`}
          >
            {health?.status === "ok" ? (
              <Wifi className="h-3 w-3" />
            ) : (
              <WifiOff className="h-3 w-3" />
            )}
            {health?.status === "ok" ? "LIVE" : "OFFLINE"}
          </span>
        </div>
      </div>

      {revisionMismatch && (
        <div className="flex items-center gap-2 border-t border-amber-500/30 bg-amber-500/10 px-4 py-1 text-[11px] text-amber-300">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          <span>
            Branch State Differs — this chat branch points to an earlier game-state revision than your live character/campaign sheet.
          </span>
        </div>
      )}
    </header>
  );
}
