import { useEffect, useState } from "react";
import { KeyRound, Loader2, Shield, ShieldCheck, UserCheck, UserPlus, X } from "lucide-react";
import { loginAuth, logoutAuth, registerAuth, setupInitialAuth } from "../api";
import cyberHeroBackdrop from "../assets/cyber-hero-backdrop.jpg";
import type { AuthStatus } from "../types";
import { useModalFocus } from "../utils/useModalFocus";
import { CyberFrame, HazardBadge, HudButton, HudToggle } from "./cyber";

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
  const [bootstrapToken, setBootstrapToken] = useState("");
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
    setBootstrapToken("");
    if (authStatus?.can_bootstrap) {
      setTab("setup");
    } else if (authStatus?.role === "user") {
      setTab("admin");
    } else {
      setTab("user");
    }
  }, [open, authStatus?.can_bootstrap, authStatus?.role]);

  const dialogRef = useModalFocus(open, blocking ? undefined : onClose);

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
      if (setupPlayerPass.trim() && !setupPlayerUser.trim()) {
        setError("Choose a username for the player account.");
        setBusy(false);
        return;
      }
      await setupInitialAuth({
        bootstrap_token: bootstrapToken,
        admin_username: adminUname,
        admin_password: setupAdminPass,
        user_username: setupPlayerPass.trim() ? setupPlayerUser.trim() : "",
        user_password: setupPlayerPass.trim(),
        user_passcode: setupRoomPasscode.trim(),
        allow_guest_users: allowGuests,
        allow_self_signup: allowSelfSignup,
      });
      setBootstrapToken("");
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

  const modalTitle =
    tab === "setup"
      ? "First-Time Setup — Admin Account"
      : tab === "signup"
        ? "Create Player Account"
        : tab === "admin"
          ? "Admin Sign-In"
          : "User Sign-In";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/82 p-4 backdrop-blur-sm outline-none"
      role="dialog"
      aria-modal="true"
      aria-label="Cyberpunk RED GM Access"
      ref={dialogRef}
      tabIndex={-1}
    >
      <CyberFrame
        variant="modal"
        className="max-h-[92dvh] w-full max-w-md overflow-y-auto"
      >
        {/* Slim Crimson Header Band with Cyberpunk Backdrop */}
        <div className="relative overflow-hidden border-b border-[var(--hud-line)] bg-[#5a0b1c]/55 px-4 py-3 sm:px-5">
          <img
            src={cyberHeroBackdrop}
            alt=""
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 h-full w-full object-cover opacity-20"
          />
          <div className="pointer-events-none absolute inset-0 bg-gradient-to-r from-[#3a0712]/80 via-[#5a0b1c]/55 to-[#12070c]/85" />
          <div className="relative z-10 flex items-start justify-between gap-2">
            <div className="flex items-start gap-2.5">
              <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-[var(--hud-accent)]" />
              <div>
                <HazardBadge
                  tone={tab === "setup" || tab === "admin" ? "danger" : "accent"}
                  className="mb-1 text-[9px]"
                >
                  {tab === "setup"
                    ? "FIRST-TIME INSTALL // ADMIN SETUP"
                    : tab === "signup"
                      ? "NEW EDGERUNNER // REGISTER"
                      : tab === "admin"
                        ? "ROOT ACCESS // ADMIN"
                        : "NIGHT CITY NET // SIGN IN"}
                </HazardBadge>
                <h2
                  data-text={modalTitle}
                  className="cp-glitch font-cyber-display text-sm font-semibold uppercase tracking-wider text-[var(--hud-text)]"
                >
                  {modalTitle}
                </h2>
                <p className="mt-0.5 font-cyber-ui text-[11px] text-[var(--hud-muted)]">
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
              <HudButton
                variant="tactical"
                size="xs"
                onClick={onClose}
                aria-label="Close"
                className="px-2 py-1"
              >
                <X className="h-4 w-4" />
              </HudButton>
            )}
          </div>
        </div>

        <div className="p-5">
          <div className="mb-4 flex gap-1 border border-[var(--hud-line-soft)] bg-black/50 p-1">
            {tabs.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => {
                  setTab(t.id);
                  setError(null);
                }}
                className={`flex-1 px-2.5 py-1.5 font-cyber-ui text-xs font-semibold transition ${
                  tab === t.id
                    ? "border border-[var(--hud-accent-line)] bg-[var(--hud-accent-navy)] text-[var(--hud-accent)]"
                    : "border border-transparent text-[var(--hud-muted)] hover:text-[var(--hud-text)]"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          {tab === "setup" ? (
            <form onSubmit={handleSetup} className="space-y-3">
              <label className="block">
                <span className="mb-1 block font-cyber-ui text-[11px] font-medium text-[var(--hud-text)]">
                  One-time Admin bootstrap token (provided by the server operator)
                </span>
                <input
                  type="password"
                  required
                  minLength={32}
                  autoComplete="off"
                  value={bootstrapToken}
                  onChange={(e) => setBootstrapToken(e.target.value)}
                  placeholder="Server bootstrap token"
                  className="w-full border border-[var(--hud-line)] bg-black/60 px-2.5 py-1.5 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
                />
                <span className="mt-1 block font-cyber-ui text-[10px] text-[var(--hud-muted)]">
                  The operator must configure REDGM_BOOTSTRAP_TOKEN before first setup.
                </span>
              </label>
              <div className="grid grid-cols-2 gap-2">
                <label className="block">
                  <span className="mb-1 block font-cyber-ui text-[11px] font-medium text-[var(--hud-text)]">
                    Admin username
                  </span>
                  <input
                    type="text"
                    required
                    value={setupAdminUser}
                    onChange={(e) => setSetupAdminUser(e.target.value)}
                    placeholder="e.g. fixer_boss"
                    className="w-full border border-[var(--hud-line)] bg-black/60 px-2.5 py-1.5 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
                  />
                </label>
                <label className="block">
                  <span className="mb-1 block font-cyber-ui text-[11px] font-medium text-[var(--hud-text)]">
                    Admin password (min 6)
                  </span>
                  <input
                    type="password"
                    required
                    minLength={6}
                    value={setupAdminPass}
                    onChange={(e) => setSetupAdminPass(e.target.value)}
                    placeholder="Strong password"
                    className="w-full border border-[var(--hud-line)] bg-black/60 px-2.5 py-1.5 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
                  />
                </label>
              </div>

              <div className="space-y-2.5 border border-[var(--hud-line-soft)] bg-[var(--hud-row)] p-3">
                <div className="font-cyber-display text-[11px] font-semibold uppercase tracking-wider text-[var(--hud-label)]">
                  Normal User Access (Optional)
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <label className="block">
                    <span className="mb-1 block font-cyber-ui text-[11px] text-[var(--hud-muted)]">
                      Player username
                    </span>
                    <input
                      type="text"
                      value={setupPlayerUser}
                      onChange={(e) => setSetupPlayerUser(e.target.value)}
                      placeholder="e.g. vee"
                      className="w-full border border-[var(--hud-line)] bg-black/60 px-2.5 py-1.5 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
                    />
                  </label>
                  <label className="block">
                    <span className="mb-1 block font-cyber-ui text-[11px] text-[var(--hud-muted)]">
                      Player password
                    </span>
                    <input
                      type="password"
                      value={setupPlayerPass}
                      onChange={(e) => setSetupPlayerPass(e.target.value)}
                      placeholder="Optional (min 4)"
                      className="w-full border border-[var(--hud-line)] bg-black/60 px-2.5 py-1.5 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
                    />
                  </label>
                </div>
                <label className="block">
                  <span className="mb-1 block font-cyber-ui text-[11px] text-[var(--hud-muted)]">
                    Or shared Player room passcode (min 4 chars)
                  </span>
                  <input
                    type="password"
                    value={setupRoomPasscode}
                    onChange={(e) => setSetupRoomPasscode(e.target.value)}
                    placeholder="Optional shared table passcode"
                    className="w-full border border-[var(--hud-line)] bg-black/60 px-2.5 py-1.5 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
                  />
                </label>
                <label className="flex cursor-pointer items-center justify-between gap-2 font-cyber-ui text-xs text-[var(--hud-text)]">
                  <span>Allow players to create their own accounts (Sign Up)</span>
                  <HudToggle
                    as="checkbox"
                    checked={allowSelfSignup}
                    onCheckedChange={setAllowSelfSignup}
                  />
                </label>
                <label className="flex cursor-pointer items-center justify-between gap-2 font-cyber-ui text-xs text-[var(--hud-text)]">
                  <span>Allow passwordless guest player sign-in</span>
                  <HudToggle
                    as="checkbox"
                    checked={allowGuests}
                    onCheckedChange={setAllowGuests}
                  />
                </label>
              </div>

              {error && (
                <div className="cyber-hazard-thin border border-[var(--hud-primary-bright)]/70 bg-[#5a0b1c]/40 px-3 py-2 font-cyber-ui text-xs text-rose-100">
                  {error}
                </div>
              )}

              <HudButton
                type="submit"
                variant="cta"
                size="md"
                disabled={busy}
                className="w-full py-2"
              >
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Shield className="h-3.5 w-3.5" />}
                Create Admin &amp; Enable Auth
              </HudButton>
            </form>
          ) : tab === "signup" ? (
            <form onSubmit={handleSignup} className="space-y-3">
              <label className="block">
                <span className="mb-1 block font-cyber-ui text-xs font-medium text-[var(--hud-text)]">
                  Choose Username
                </span>
                <input
                  type="text"
                  required
                  maxLength={40}
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="e.g. choom_v"
                  className="w-full border border-[var(--hud-line)] bg-black/60 px-3 py-2 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
                />
              </label>

              <label className="block">
                <span className="mb-1 block font-cyber-ui text-xs font-medium text-[var(--hud-text)]">
                  Password (min 4 characters)
                </span>
                <input
                  type="password"
                  required
                  minLength={4}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Choose a password..."
                  className="w-full border border-[var(--hud-line)] bg-black/60 px-3 py-2 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
                />
              </label>

              <label className="block">
                <span className="mb-1 block font-cyber-ui text-xs font-medium text-[var(--hud-text)]">
                  Confirm Password
                </span>
                <input
                  type="password"
                  required
                  minLength={4}
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="Repeat password..."
                  className="w-full border border-[var(--hud-line)] bg-black/60 px-3 py-2 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
                />
              </label>

              {error && (
                <div className="cyber-hazard-thin border border-[var(--hud-primary-bright)]/70 bg-[#5a0b1c]/40 px-3 py-2 font-cyber-ui text-xs text-rose-100">
                  {error}
                </div>
              )}

              <HudButton
                type="submit"
                variant="cta"
                size="md"
                disabled={busy}
                className="w-full py-2"
              >
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <UserPlus className="h-3.5 w-3.5" />}
                Create Player Account
              </HudButton>
            </form>
          ) : (
            <form onSubmit={handleLogin} className="space-y-3">
              <label className="block">
                <span className="mb-1 block font-cyber-ui text-xs font-medium text-[var(--hud-text)]">
                  {tab === "admin" ? "Admin Username" : "Username (optional if using room passcode)"}
                </span>
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required={tab === "admin"}
                  placeholder={tab === "admin" ? "Enter admin username..." : "Username"}
                  className="w-full border border-[var(--hud-line)] bg-black/60 px-3 py-2 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
                />
              </label>

              <label className="block">
                <span className="mb-1 block font-cyber-ui text-xs font-medium text-[var(--hud-text)]">
                  {tab === "admin" ? "Admin Password" : "Password or Shared Player Passcode"}
                </span>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required={tab === "admin" || !authStatus?.allow_guest_users}
                  placeholder="Enter password..."
                  className="w-full border border-[var(--hud-line)] bg-black/60 px-3 py-2 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
                />
              </label>

              {error && (
                <div className="cyber-hazard-thin border border-[var(--hud-primary-bright)]/70 bg-[#5a0b1c]/40 px-3 py-2 font-cyber-ui text-xs text-rose-100">
                  {error}
                </div>
              )}

              <HudButton
                type="submit"
                variant="cta"
                size="md"
                disabled={busy}
                className="w-full py-2"
              >
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <KeyRound className="h-3.5 w-3.5" />}
                {tab === "admin" ? "Sign In as Admin" : "Sign In as Player"}
              </HudButton>

              {tab === "user" && authStatus?.allow_guest_users && (
                <HudButton
                  type="button"
                  variant="tactical"
                  size="md"
                  disabled={busy}
                  onClick={() => void handleQuickGuest()}
                  className="w-full py-2"
                >
                  <UserCheck className="h-3.5 w-3.5 text-[var(--hud-accent)]" />
                  Join as Guest Player
                </HudButton>
              )}
            </form>
          )}
        </div>
      </CyberFrame>
    </div>
  );
}
