import { useEffect, useState } from "react";
import {
  Check,
  Copy,
  Globe,
  KeyRound,
  Lock,
  Radio,
  Shield,
  Users,
  X,
} from "lucide-react";
import {
  fetchNetworkInfo,
  getClientId,
  getStoredRoomPin,
  setStoredRoomPin,
} from "../api";
import type { ActiveTurnInfo, CharacterRecord, CoopPlayer, NetworkInfo } from "../types";
import { CyberFrame, HazardBadge, HudButton, HudToggle } from "./cyber";

interface CoopModalProps {
  open: boolean;
  campaignId: string | null;
  campaignName: string | null;
  characters: CharacterRecord[];
  isAdmin?: boolean;
  currentUsername?: string | null;
  playerName: string;
  claimedCharId: string;
  protectOthers: boolean;
  roster: CoopPlayer[];
  activeTurn: ActiveTurnInfo | null;
  onChangePlayerName: (name: string) => void;
  onChangeClaimedChar: (charId: string) => void;
  onChangeProtectOthers: (val: boolean) => void;
  onClose: () => void;
  onNotify: (msg: string) => void;
}

export function CoopModal({
  open,
  campaignId,
  campaignName,
  characters,
  isAdmin = true,
  currentUsername = null,
  playerName,
  claimedCharId,
  protectOthers,
  roster,
  activeTurn,
  onChangePlayerName,
  onChangeClaimedChar,
  onChangeProtectOthers,
  onClose,
  onNotify,
}: CoopModalProps) {
  const [netInfo, setNetInfo] = useState<NetworkInfo | null>(null);
  const [nameDraft, setNameDraft] = useState(playerName);
  const [pinDraft, setPinDraft] = useState(getStoredRoomPin());
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const selfClientId = getClientId();

  useEffect(() => {
    setNameDraft(playerName);
  }, [playerName, open]);

  useEffect(() => {
    if (!open) return;
    fetchNetworkInfo(campaignId ?? undefined)
      .then(setNetInfo)
      .catch(() => setNetInfo(null));
  }, [open, campaignId]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const copyText = async (key: string, text: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedKey(key);
      onNotify(`Copied ${label}.`);
      setTimeout(() => setCopiedKey(null), 1800);
    } catch {
      onNotify("Could not access clipboard.");
    }
  };

  const handleSaveIdentity = (e: React.FormEvent) => {
    e.preventDefault();
    onChangePlayerName(nameDraft.trim() || "Player");
    setStoredRoomPin(pinDraft);
    onNotify("Updated player profile & room passcode.");
  };

  const lanCmd = `.venv/bin/python redkb.py serve --lan`;
  const charById = new Map(characters.map((c) => [c.id, c.name]));
  const selectableCharacters = isAdmin
    ? characters
    : characters.filter((c) => {
        const owner = String(c.detail?.owner_username ?? "").trim().toLowerCase();
        const me = String(currentUsername ?? "").trim().toLowerCase();
        return !owner || (me && owner === me);
      });

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="Party & LAN Multiplayer"
      onClick={onClose}
    >
      <CyberFrame
        variant="modal"
        className="flex max-h-[90dvh] w-full max-w-lg flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[var(--hud-line)] bg-[#5a0b1c]/55 px-4 py-3 sm:px-5">
          <div className="flex items-center gap-2.5">
            <Users className="h-4 w-4 shrink-0 text-[var(--hud-accent)]" />
            <div>
              <h2
                data-text="Party & LAN Table"
                className="cp-glitch font-cyber-display text-sm font-semibold uppercase tracking-wider text-[var(--hud-text)]"
              >
                Party &amp; LAN Table
              </h2>
              <p className="font-cyber-ui text-[11px] text-[var(--hud-muted)]">
                {campaignName ? `Campaign: ${campaignName}` : "No campaign selected"}
              </p>
            </div>
          </div>
          <HudButton
            variant="tactical"
            size="xs"
            onClick={onClose}
            aria-label="Close party settings"
            className="px-2 py-1"
          >
            <X className="h-4 w-4" />
          </HudButton>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto p-5 font-cyber-ui text-xs">
          {/* Your Seat / Identity */}
          <form
            onSubmit={handleSaveIdentity}
            className="space-y-3 border border-[var(--hud-line-soft)] bg-[var(--hud-row)] p-3.5"
          >
            <div className="flex items-center justify-between">
              <span className="font-cyber-display text-xs font-semibold uppercase tracking-wider text-[var(--hud-text)]">
                Your Seat &amp; Character
              </span>
              <span className="font-cyber-data text-[10px] text-[var(--hud-muted)]">
                ID {selfClientId.slice(0, 8)}
              </span>
            </div>

            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
              <div>
                <label className="mb-1 block font-cyber-ui text-[11px] text-[var(--hud-muted)]">
                  Player Name
                </label>
                <input
                  type="text"
                  value={nameDraft}
                  onChange={(e) => setNameDraft(e.target.value)}
                  placeholder="Your handle..."
                  className="w-full border border-[var(--hud-line)] bg-black/60 px-2.5 py-1.5 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
                />
              </div>

              <div>
                <label className="mb-1 block font-cyber-ui text-[11px] text-[var(--hud-muted)]">
                  Claimed Character
                </label>
                <select
                  value={claimedCharId}
                  onChange={(e) => onChangeClaimedChar(e.target.value)}
                  className="w-full border border-[var(--hud-line)] bg-black/60 px-2.5 py-1.5 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                >
                  {isAdmin && <option value="">Any / Narrator (GM)</option>}
                  {!isAdmin && <option value="">Unassigned / Select Your Character</option>}
                  {selectableCharacters.map((c) => {
                    const owner = String(c.detail?.owner_username ?? "").trim();
                    return (
                      <option key={c.id} value={c.id}>
                        {c.name}{owner ? ` (@${owner})` : ""}
                      </option>
                    );
                  })}
                </select>
              </div>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
              <label className="inline-flex cursor-pointer items-center gap-2 font-cyber-ui text-xs text-[var(--hud-text)]">
                <HudToggle
                  as="checkbox"
                  checked={protectOthers}
                  onCheckedChange={onChangeProtectOthers}
                  className="min-w-12 py-0.5 text-[10px]"
                />
                <Shield className="h-3.5 w-3.5 text-[var(--hud-accent)]" />
                <span>Protect other players&apos; sheets in HUD</span>
              </label>

              <HudButton type="submit" variant="cta" size="sm">
                Save Seat
              </HudButton>
            </div>

            {(netInfo?.pin_required || pinDraft) && (
              <div className="pt-1">
                <label className="mb-1 flex items-center gap-1.5 font-cyber-ui text-[11px] text-[var(--hud-warn)]">
                  <KeyRound className="h-3 w-3" />
                  Room Passcode (PIN)
                </label>
                <input
                  type="password"
                  value={pinDraft}
                  onChange={(e) => setPinDraft(e.target.value)}
                  placeholder="Enter host PIN if required..."
                  className="w-full border border-[var(--hud-warn)]/60 bg-black/60 px-2.5 py-1.5 font-cyber-data text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-warn)] focus:outline-none"
                />
              </div>
            )}
          </form>

          {/* Online Crew */}
          <div className="space-y-2 border border-[var(--hud-line-soft)] bg-[var(--hud-row)] p-3.5">
            <div className="flex items-center justify-between gap-2">
              <span className="inline-flex items-center gap-1.5 font-cyber-display text-xs font-semibold uppercase tracking-wider text-[var(--hud-text)]">
                <Radio className="h-3.5 w-3.5 text-[var(--hud-ok)]" />
                Live Crew (<span className="font-cyber-data">{roster.length}</span>)
              </span>
              {activeTurn && (
                <HazardBadge tone="warn" className="text-[10px]">
                  Turn: {activeTurn.player_name}
                </HazardBadge>
              )}
            </div>

            {roster.length === 0 ? (
              <p className="font-cyber-ui text-[var(--hud-muted)]">
                Only you are tuned in right now. Friends who open this campaign appear here automatically with live updates.
              </p>
            ) : (
              <div className="space-y-1.5">
                {roster.map((p) => {
                  const isYou = p.client_id === selfClientId;
                  const charName = p.character_id ? charById.get(p.character_id) : null;
                  return (
                    <div
                      key={p.client_id}
                      className="flex items-center justify-between border border-[var(--hud-line-soft)] bg-black/50 px-2.5 py-1.5"
                    >
                      <div className="flex items-center gap-2">
                        <span className="h-2 w-2 bg-[var(--hud-ok)]" />
                        <span className="font-cyber-ui font-medium text-[var(--hud-text)]">
                          {p.player_name}
                          {isYou ? " (You)" : ""}
                        </span>
                      </div>
                      <span className="font-cyber-ui text-[11px] font-medium text-[var(--hud-accent)]">
                        {charName ?? "Observer / Party"}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* LAN Hosting Info */}
          <div className="space-y-2.5 border border-[var(--hud-line-soft)] bg-[var(--hud-row)] p-3.5">
            <div className="flex items-center justify-between">
              <span className="inline-flex items-center gap-1.5 font-cyber-display text-xs font-semibold uppercase tracking-wider text-[var(--hud-text)]">
                {netInfo?.lan_enabled ? (
                  <Globe className="h-3.5 w-3.5 text-[var(--hud-ok)]" />
                ) : (
                  <Lock className="h-3.5 w-3.5 text-[var(--hud-muted)]" />
                )}
                Network Hosting
              </span>
              {netInfo?.lan_enabled ? (
                <HazardBadge tone="accent" className="text-[10px]">
                  LAN OPEN
                </HazardBadge>
              ) : (
                <span className="border border-[var(--hud-line-soft)] bg-black/50 px-2 py-0.5 font-cyber-data text-[10px] uppercase tracking-wider text-[var(--hud-muted)]">
                  LOCAL ONLY
                </span>
              )}
            </div>

            {netInfo?.lan_enabled ? (
              <div className="space-y-1.5">
                <p className="font-cyber-ui text-[var(--hud-muted)]">
                  Friends on the same Wi-Fi / LAN can join straight in their browser:
                </p>
                {netInfo.join_urls.map((url) => (
                  <div
                    key={url}
                    className="flex items-center justify-between gap-2 border border-[var(--hud-accent-line)] bg-[var(--hud-accent-navy)] px-2.5 py-1.5 font-cyber-data text-[11px] text-[var(--hud-accent)]"
                  >
                    <span className="truncate">{url}</span>
                    <HudButton
                      variant="tactical"
                      size="xs"
                      onClick={() => void copyText(url, url, "join link")}
                      className="shrink-0"
                    >
                      {copiedKey === url ? <Check className="h-3 w-3 text-[var(--hud-ok)]" /> : <Copy className="h-3 w-3" />}
                      Copy
                    </HudButton>
                  </div>
                ))}
              </div>
            ) : (
              <div className="space-y-2 font-cyber-ui text-[var(--hud-muted)]">
                <p>
                  Right now the server only accepts connections from this computer (
                  <code className="font-cyber-data text-[var(--hud-text)]">127.0.0.1</code>). Start the server with{" "}
                  <code className="font-cyber-data text-[var(--hud-accent)]">--lan</code> (plus optional{" "}
                  <code className="font-cyber-data text-[var(--hud-accent)]">--pin 4242</code>) so friends on your Wi-Fi can join:
                </p>
                <div className="flex items-center justify-between gap-2 border border-[var(--hud-line-soft)] bg-black/60 px-2.5 py-1.5 font-cyber-data text-[11px] text-[var(--hud-text)]">
                  <span className="truncate">{lanCmd}</span>
                  <HudButton
                    variant="tactical"
                    size="xs"
                    onClick={() => void copyText("lan-cmd", lanCmd, "LAN launch command")}
                    className="shrink-0"
                  >
                    {copiedKey === "lan-cmd" ? <Check className="h-3 w-3 text-[var(--hud-ok)]" /> : <Copy className="h-3 w-3" />}
                    Copy
                  </HudButton>
                </div>
              </div>
            )}
          </div>
        </div>
      </CyberFrame>
    </div>
  );
}
