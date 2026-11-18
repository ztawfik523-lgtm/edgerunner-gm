import { useEffect, useState } from "react";
import { KeyRound, Loader2, Shield, ShieldCheck, UserCheck, UserPlus, X } from "lucide-react";
import { loginAuth, logoutAuth, registerAuth, setupInitialAuth } from "../api";
import cyberHeroBackdrop from "../assets/cyber-hero-backdrop.jpg";
import type { AuthStatus } from "../types";

interface AuthGateModalProps {
  open: boolean;
  blocking: boolean;
  authStatus: AuthStatus | null;
  onAuthenticated: () => Promise<void> | void;
  onClose?: () => void;
}

export function AuthGateModal({
  open,
  blocking,
  authStatus,
  onAuthenticated,
  onClose,
}: AuthGateModalProps) {
  const canBootstrap = Boolean(authStatus?.can_bootstrap);
  const canSelfSignup = !canBootstrap && authStatus?.allow_self_signup !== false;
  const [tab, setTab] = useState<"user" | "signup" | "admin" | "setup">(
    canBootstrap ? "setup" : "user",
  );
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [setupAdminUser, setSetupAdminUser] = useState("");
  const [setupAdminPass, setSetupAdminPass] = useState("");
  const [setupPlayerUser, setSetupPlayerUser] = useState("");
  const [setupPlayerPass, setSetupPlayerPass] = useState("");
  const [setupRoomPasscode, setSetupRoomPasscode] = useState("");
  const [allowGuests, setAllowGuests] = useState(false);
  const [allowSelfSignup, setAllowSelfSignup] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setPassword("");
    setConfirmPassword("");
    if (authStatus?.can_bootstrap) {
      setTab("setup");
    } else if (authStatus?.role === "user") {
      setTab("admin");
    } else {
      setTab("user");
    }
  }, [open, authStatus?.can_bootstrap, authStatus?.role]);

  useEffect(() => {
    if (!open || blocking || !onClose) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, blocking, onClose]);

  if (!open) return null;

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await loginAuth({
        mode: tab === "admin" ? "admin" : "user",
        username: username.trim(),
        password,
      });
      setPassword("");
      await onAuthenticated();
      onClose?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  };

  const handleSetup = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const adminUname = setupAdminUser.trim();
      if (!adminUname) {
        setError("Choose an Admin username.");
        setBusy(false);
        return;
      }
      await setupInitialAuth({
        admin_username: adminUname,
        admin_password: setupAdminPass,
        user_username: setupPlayerPass.trim() ? (setupPlayerUser.trim() || "player") : "",
        user_password: setupPlayerPass.trim(),
        user_passcode: setupRoomPasscode.trim(),
        allow_guest_users: allowGuests,
        allow_self_signup: allowSelfSignup,
      });
      setSetupAdminPass("");
      setSetupPlayerPass("");
      setSetupRoomPasscode("");
      await onAuthenticated();
      onClose?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to initialize access control");
    } finally {
      setBusy(false);
    }
  };

  const handleQuickGuest = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await logoutAuth();
      await onAuthenticated();
      onClose?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Guest sign-in failed");
    } finally {
      setBusy(false);
    }
  };

  const handleSignup = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    const uname = username.trim();
    if (!uname) {
      setError("Choose a player username.");
      return;
    }
    if (password.length < 4) {
      setError("Password must be at least 4 characters.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await registerAuth({ username: uname, password });
      setPassword("");
      setConfirmPassword("");
      await onAuthenticated();
      onClose?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create account");
    } finally {
      setBusy(false);
    }
  };

  const tabs: Array<{ id: "user" | "signup" | "admin" | "setup"; label: string }> = canBootstrap
    ? [
        { id: "setup", label: "Enable Accounts" },
        { id: "admin", label: "Admin Sign-In" },
        { id: "user", label: "User Sign-In" },
      ]
    : [
        { id: "user", label: "User Sign-In" },
        ...(canSelfSignup ? [{ id: "signup" as const, label: "Create Account" }] : []),
        { id: "admin", label: "Admin Sign-In" },
      ];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/82 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="Cyberpunk RED GM Access"
    >
      <div className="cyber-cut cyber-panel-glow max-h-[92dvh] w-full max-w-md overflow-y-auto border border-cyan-500/35 bg-[#0b1019] shadow-2xl">
        {/* Cyberpunk Banner Header */}
        <div className="relative border-b border-slate-800 px-5 py-4">
          <img
            src={cyberHeroBackdrop}
            alt=""
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 h-full w-full object-cover opacity-35"
          />
          <div className="pointer-events-none absolute inset-0 bg-gradient-to-r from-[#090d16]/95 via-[#0b1019]/85 to-[#090d16]/90" />
          <div className="relative z-10 flex items-start justify-between gap-2">
            <div className="flex items-start gap-2.5">
              <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-cyan-400" />
              <div>
                <div className="mb-1 inline-flex items-center gap-1.5 rounded border border-rose-500/40 bg-rose-500/15 px-1.5 py-0.5 font-mono text-[9px] font-semibold uppercase tracking-widest text-rose-300">
                  {tab === "setup"
                    ? "FIRST-TIME INSTALL // ADMIN SETUP"
                    : tab === "signup"
                      ? "NEW EDGERUNNER // REGISTER"
                      : tab === "admin"
                        ? "ROOT ACCESS // ADMIN"
                        : "NIGHT CITY NET // SIGN IN"}
                </div>
                <h2
                  data-text={
                    tab === "setup"
                      ? "First-Time Setup — Admin Account"
                      : tab === "signup"
                        ? "Create Player Account"
                        : tab === "admin"
                          ? "Admin Sign-In"
                          : "User Sign-In"
                  }
                  className="cyber-glitch-title font-cyber-display text-sm font-bold uppercase tracking-wider text-slate-100"
                >
                  {tab === "setup"
                    ? "First-Time Setup — Admin Account"
                    : tab === "signup"
                      ? "Create Player Account"
                      : tab === "admin"
                        ? "Admin Sign-In"
                        : "User Sign-In"}
                </h2>
                <p className="mt-0.5 text-[11px] text-slate-300">
                  {tab === "admin"
                    ? "Full access: AI provider, Corebook PDF, prompts, network IP/port, and user management."
                    : tab === "signup"
                      ? "Register your own player profile to claim a character and join the table."
                      : tab === "setup"
                        ? "Create the server Admin account first so your AI key, Corebook, and prompts stay protected."
                        : "Normal tabletop access: campaigns, characters, chat, dice, and rulebook."}
                </p>
              </div>
            </div>
            {!blocking && onClose && (
              <button
                type="button"
                onClick={onClose}
                aria-label="Close"
                className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-slate-100"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>

        <div className="p-5">

        <div className="mb-4 flex gap-1.5 rounded-lg bg-slate-950 p-1">
          {tabs.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => {
                setTab(t.id);
                setError(null);
              }}
              className={`flex-1 rounded-md px-2.5 py-1.5 text-xs font-semibold transition ${
                tab === t.id
                  ? "bg-cyan-600/30 text-cyan-200 border border-cyan-500/40"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {tab === "setup" ? (
          <form onSubmit={handleSetup} className="space-y-3">
            <div className="grid grid-cols-2 gap-2">
                <label className="block">
                  <span className="mb-1 block text-[11px] font-medium text-slate-300">Admin username</span>
                  <input
                    type="text"
                    required
                    value={setupAdminUser}
                    onChange={(e) => setSetupAdminUser(e.target.value)}
                    placeholder="e.g. fixer_boss"
                    className="w-full rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                  />
                </label>
              <label className="block">
                <span className="mb-1 block text-[11px] font-medium text-slate-300">
                  Admin password (min 6)
                </span>
                <input
                  type="password"
                  required
                  minLength={6}
                  value={setupAdminPass}
                  onChange={(e) => setSetupAdminPass(e.target.value)}
                  placeholder="Strong password"
                  className="w-full rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                />
              </label>
            </div>

            <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-3 space-y-2.5">
              <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                Normal User Access (Optional)
              </div>
              <div className="grid grid-cols-2 gap-2">
                <label className="block">
                  <span className="mb-1 block text-[11px] text-slate-400">Player username</span>
                  <input
                    type="text"
                    value={setupPlayerUser}
                    onChange={(e) => setSetupPlayerUser(e.target.value)}
                    placeholder="player"
                    className="w-full rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                  />
                </label>
                <label className="block">
                  <span className="mb-1 block text-[11px] text-slate-400">Player password</span>
                  <input
                    type="password"
                    value={setupPlayerPass}
                    onChange={(e) => setSetupPlayerPass(e.target.value)}
                    placeholder="Optional (min 4)"
                    className="w-full rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                  />
                </label>
              </div>
              <label className="block">
                <span className="mb-1 block text-[11px] text-slate-400">
                  Or shared Player room passcode (min 4 chars)
                </span>
                <input
                  type="password"
                  value={setupRoomPasscode}
                  onChange={(e) => setSetupRoomPasscode(e.target.value)}
                  placeholder="Optional shared table passcode"
                  className="w-full rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                />
              </label>
              <label className="flex items-center gap-2 text-xs text-slate-300">
                <input
                  type="checkbox"
                  checked={allowSelfSignup}
                  onChange={(e) => setAllowSelfSignup(e.target.checked)}
                />
                Allow players to create their own accounts (Sign Up)
              </label>
              <label className="flex items-center gap-2 text-xs text-slate-300">
                <input
                  type="checkbox"
                  checked={allowGuests}
                  onChange={(e) => setAllowGuests(e.target.checked)}
                />
                Allow passwordless guest player sign-in
              </label>
            </div>

            {error && (
              <div className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
                {error}
              </div>
            )}

              <button
                type="submit"
                disabled={busy}
                className="inline-flex w-full items-center justify-center gap-1.5 rounded-md bg-rose-600 px-3 py-2 text-xs font-semibold text-white hover:bg-rose-500 disabled:opacity-50"
              >
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Shield className="h-3.5 w-3.5" />}
                Create Admin &amp; Enable Auth
              </button>
          </form>
        ) : tab === "signup" ? (
          <form onSubmit={handleSignup} className="space-y-3">
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-slate-300">
                Choose Username
              </span>
              <input
                type="text"
                required
                maxLength={40}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="e.g. choom_v"
                className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
              />
            </label>

            <label className="block">
              <span className="mb-1 block text-xs font-medium text-slate-300">
                Password (min 4 characters)
              </span>
              <input
                type="password"
                required
                minLength={4}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Choose a password..."
                className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
              />
            </label>

            <label className="block">
              <span className="mb-1 block text-xs font-medium text-slate-300">
                Confirm Password
              </span>
              <input
                type="password"
                required
                minLength={4}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="Repeat password..."
                className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
              />
            </label>

            {error && (
              <div className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={busy}
              className="inline-flex w-full items-center justify-center gap-1.5 rounded-md bg-cyan-600 px-3 py-2 text-xs font-semibold text-white hover:bg-cyan-500 disabled:opacity-50"
            >
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <UserPlus className="h-3.5 w-3.5" />}
              Create Player Account
            </button>
          </form>
        ) : (
          <form onSubmit={handleLogin} className="space-y-3">
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-slate-300">
                {tab === "admin" ? "Admin Username" : "Username (optional if using room passcode)"}
              </span>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required={tab === "admin"}
                placeholder={tab === "admin" ? "Enter admin username..." : "Username"}
                className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
              />
            </label>

            <label className="block">
              <span className="mb-1 block text-xs font-medium text-slate-300">
                {tab === "admin" ? "Admin Password" : "Password or Shared Player Passcode"}
              </span>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required={tab === "admin" || !authStatus?.allow_guest_users}
                placeholder="Enter password..."
                className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
              />
            </label>

            {error && (
              <div className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={busy}
              className="inline-flex w-full items-center justify-center gap-1.5 rounded-md bg-rose-600 px-3 py-2 text-xs font-semibold text-white hover:bg-rose-500 disabled:opacity-50"
            >
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <KeyRound className="h-3.5 w-3.5" />}
              {tab === "admin" ? "Sign In as Admin" : "Sign In as Player"}
            </button>

            {tab === "user" && authStatus?.allow_guest_users && (
              <button
                type="button"
                disabled={busy}
                onClick={() => void handleQuickGuest()}
                className="inline-flex w-full items-center justify-center gap-1.5 rounded-md border border-cyan-500/40 bg-cyan-500/10 px-3 py-2 text-xs font-semibold text-cyan-200 hover:bg-cyan-500/20 disabled:opacity-50"
              >
                <UserCheck className="h-3.5 w-3.5" />
                Join as Guest Player
              </button>
            )}
          </form>
        )}
        </div>
      </div>
    </div>
  );
}
