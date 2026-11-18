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

interface CoopModalProps {
  open: boolean;
  campaignId: string | null;
  campaignName: string | null;
  characters: CharacterRecord[];
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

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="Co-op & LAN Multiplayer"
      onClick={onClose}
    >
      <div
        className="cyber-cut flex max-h-[90vh] w-full max-w-lg flex-col overflow-hidden border border-slate-700 bg-[#0d111a] shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-800 px-5 py-3.5">
          <div className="flex items-center gap-2.5">
            <Users className="h-4 w-4 text-cyan-400" />
            <div>
              <h2 className="text-sm font-bold text-slate-100">Co-op & LAN Table</h2>
              <p className="text-[11px] text-slate-400">
                {campaignName ? `Campaign: ${campaignName}` : "No campaign selected"}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close co-op settings"
            className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-slate-100"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex-1 space-y-5 overflow-y-auto p-5 text-xs">
          {/* Your Seat / Identity */}
          <form onSubmit={handleSaveIdentity} className="space-y-3 rounded-lg border border-slate-800 bg-[#101624] p-3.5">
            <div className="flex items-center justify-between">
              <span className="font-semibold text-slate-200">Your Seat & Character</span>
              <span className="font-mono text-[10px] text-slate-500">
                ID {selfClientId.slice(0, 8)}
              </span>
            </div>

            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
              <div>
                <label className="mb-1 block text-[11px] text-slate-400">Player Name</label>
                <input
                  type="text"
                  value={nameDraft}
                  onChange={(e) => setNameDraft(e.target.value)}
                  placeholder="Your handle..."
                  className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                />
              </div>

              <div>
                <label className="mb-1 block text-[11px] text-slate-400">Claimed Character</label>
                <select
                  value={claimedCharId}
                  onChange={(e) => onChangeClaimedChar(e.target.value)}
                  className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                >
                  <option value="">Any / Narrator</option>
                  {characters.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
              <label className="inline-flex cursor-pointer items-center gap-2 text-slate-300">
                <input
                  type="checkbox"
                  checked={protectOthers}
                  onChange={(e) => onChangeProtectOthers(e.target.checked)}
                  className="rounded border-slate-600 bg-slate-900 accent-cyan-500"
                />
                <Shield className="h-3.5 w-3.5 text-cyan-400" />
                Protect other players&apos; sheets in HUD
              </label>

              <button
                type="submit"
                className="rounded bg-cyan-600 px-3 py-1 font-semibold text-white hover:bg-cyan-500"
              >
                Save Seat
              </button>
            </div>

            {(netInfo?.pin_required || pinDraft) && (
              <div className="pt-1">
                <label className="mb-1 flex items-center gap-1.5 text-[11px] text-amber-300">
                  <KeyRound className="h-3 w-3" />
                  Room Passcode (PIN)
                </label>
                <input
                  type="password"
                  value={pinDraft}
                  onChange={(e) => setPinDraft(e.target.value)}
                  placeholder="Enter host PIN if required..."
                  className="w-full rounded border border-amber-500/40 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100 focus:border-amber-400 focus:outline-none"
                />
              </div>
            )}
          </form>

          {/* Online Crew */}
          <div className="space-y-2 rounded-lg border border-slate-800 bg-[#101624] p-3.5">
            <div className="flex items-center justify-between">
              <span className="inline-flex items-center gap-1.5 font-semibold text-slate-200">
                <Radio className="h-3.5 w-3.5 text-emerald-400" />
                Live Crew ({roster.length})
              </span>
              {activeTurn && (
                <span className="rounded bg-amber-500/15 px-2 py-0.5 font-mono text-[10px] text-amber-300">
                  Turn: {activeTurn.player_name}
                </span>
              )}
            </div>

            {roster.length === 0 ? (
              <p className="text-slate-400">
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
                      className="flex items-center justify-between rounded border border-slate-800 bg-slate-950/70 px-2.5 py-1.5"
                    >
                      <div className="flex items-center gap-2">
                        <span className="h-2 w-2 rounded-full bg-emerald-400" />
                        <span className="font-medium text-slate-100">
                          {p.player_name}
                          {isYou ? " (You)" : ""}
                        </span>
                      </div>
                      <span className="font-mono text-[11px] text-cyan-300">
                        {charName ?? "Observer / Party"}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* LAN Hosting Info */}
          <div className="space-y-2.5 rounded-lg border border-slate-800 bg-[#101624] p-3.5">
            <div className="flex items-center justify-between">
              <span className="inline-flex items-center gap-1.5 font-semibold text-slate-200">
                {netInfo?.lan_enabled ? (
                  <Globe className="h-3.5 w-3.5 text-emerald-400" />
                ) : (
                  <Lock className="h-3.5 w-3.5 text-slate-400" />
                )}
                Network Hosting
              </span>
              <span
                className={`rounded px-2 py-0.5 font-mono text-[10px] ${
                  netInfo?.lan_enabled
                    ? "border border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
                    : "border border-slate-700 bg-slate-900 text-slate-400"
                }`}
              >
                {netInfo?.lan_enabled ? "LAN OPEN" : "LOCAL ONLY"}
              </span>
            </div>

            {netInfo?.lan_enabled ? (
              <div className="space-y-1.5">
                <p className="text-slate-400">
                  Friends on the same Wi-Fi / LAN can join straight in their browser:
                </p>
                {netInfo.join_urls.map((url) => (
                  <div
                    key={url}
                    className="flex items-center justify-between gap-2 rounded border border-cyan-500/30 bg-slate-950 px-2.5 py-1.5 font-mono text-[11px] text-cyan-300"
                  >
                    <span className="truncate">{url}</span>
                    <button
                      type="button"
                      onClick={() => void copyText(url, url, "join link")}
                      className="inline-flex shrink-0 items-center gap-1 rounded bg-slate-800 px-2 py-0.5 text-slate-200 hover:bg-slate-700"
                    >
                      {copiedKey === url ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
                      Copy
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <div className="space-y-2 text-slate-400">
                <p>
                  Right now the server only accepts connections from this computer (<code className="text-slate-300">127.0.0.1</code>). Start the server with <code className="text-cyan-300">--lan</code> (plus optional <code className="text-cyan-300">--pin 4242</code>) so friends on your Wi-Fi can join:
                </p>
                <div className="flex items-center justify-between gap-2 rounded border border-slate-800 bg-slate-950 px-2.5 py-1.5 font-mono text-[11px] text-slate-200">
                  <span className="truncate">{lanCmd}</span>
                  <button
                    type="button"
                    onClick={() => void copyText("lan-cmd", lanCmd, "LAN launch command")}
                    className="inline-flex shrink-0 items-center gap-1 rounded bg-slate-800 px-2 py-0.5 text-slate-200 hover:bg-slate-700"
                  >
                    {copiedKey === "lan-cmd" ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
                    Copy
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
