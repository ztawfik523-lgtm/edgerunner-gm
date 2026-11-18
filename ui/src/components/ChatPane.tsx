import { type ComponentProps, useEffect, useRef, useState } from "react";
import { Streamdown } from "streamdown";
import cyberHeroBackdrop from "../assets/cyber-hero-backdrop.jpg";
import nightMarketHero from "../assets/night-market-hero.jpg";
import {
  AlertTriangle,
  ArrowDown,
  BookOpen,
  Check,
  ChevronLeft,
  ChevronRight,
  Clock,
  Copy,
  Dices,
  Edit3,
  Lock,
  Minus,
  Palette,
  Pencil,
  Plus,
  RefreshCw,
  Send,
  Sparkles,
  Square,
  Terminal,
  Trash2,
  User,
  Wand2,
  X,
  Zap,
} from "lucide-react";

const COLOR_CLASS_MAP: Record<string, string> = {
  cyan: "font-medium text-cyan-300",
  blue: "font-medium text-cyan-300",
  rose: "font-medium text-rose-400",
  red: "font-medium text-rose-400",
  pink: "font-medium text-rose-400",
  crimson: "font-medium text-rose-400",
  amber: "font-medium text-amber-300",
  yellow: "font-medium text-amber-300",
  gold: "font-medium text-amber-300",
  orange: "font-medium text-amber-300",
  emerald: "font-medium text-emerald-300",
  green: "font-medium text-emerald-300",
  mint: "font-medium text-emerald-300",
  violet: "font-medium text-violet-300",
  purple: "font-medium text-violet-300",
  magenta: "font-medium text-violet-300",
  slate: "text-slate-400",
  muted: "text-slate-400",
  dim: "text-slate-400",
  gray: "text-slate-400",
};

const COLOR_SWATCHES: Array<{ id: string; label: string; dotClass: string }> = [
  { id: "cyan", label: "Cyan", dotClass: "bg-cyan-400" },
  { id: "rose", label: "Rose", dotClass: "bg-rose-400" },
  { id: "amber", label: "Amber", dotClass: "bg-amber-300" },
  { id: "emerald", label: "Emerald", dotClass: "bg-emerald-400" },
  { id: "violet", label: "Violet", dotClass: "bg-violet-400" },
];

export function formatColorMarkdown(raw: string): string {
  const segments = raw.split(/(```[\s\S]*?```|`[^`\n]+`)/g);
  return segments
    .map((seg, idx) => {
      if (idx % 2 === 1) return seg;
      let out = seg.replace(/\[\[([a-zA-Z]+):([^\]\n]+)\]\]/g, (full, rawColor: string, inner: string) => {
        const key = rawColor.toLowerCase();
        return COLOR_CLASS_MAP[key] ? `[${inner}](https://cpr-color.local/${key})` : full;
      });
      out = out.replace(/\[([^\]\n]+)\]\(color:([a-zA-Z]+)\)/g, (full, inner: string, rawColor: string) => {
        const key = rawColor.toLowerCase();
        return COLOR_CLASS_MAP[key] ? `[${inner}](https://cpr-color.local/${key})` : full;
      });
      out = out.replace(/\[\[([a-zA-Z]+):([^\]\n]*)$/g, (full, rawColor: string, inner: string) => {
        const key = rawColor.toLowerCase();
        return COLOR_CLASS_MAP[key] ? `[${inner}](https://cpr-color.local/${key})` : full;
      });
      return out;
    })
    .join("");
}

function ColorAwareLink({ href, children, className, node: _node, ...rest }: ComponentProps<"a"> & { node?: unknown }) {
  const match =
    typeof href === "string"
      ? /^(?:https:\/\/cpr-color\.local\/|#(?:cpr-)?color[:-])([a-zA-Z]+)$/i.exec(href)
      : null;
  if (match) {
    const key = match[1].toLowerCase();
    const cls = COLOR_CLASS_MAP[key];
    if (cls) {
      return (
        <span className={cls} data-cpr-color={key}>
          {children}
        </span>
      );
    }
  }
  return (
    <a
      className={className || "wrap-anywhere font-medium text-cyan-300 underline"}
      href={href}
      rel="noreferrer"
      target="_blank"
      {...rest}
    >
      {children}
    </a>
  );
}

const STREAMDOWN_COMPONENTS = { a: ColorAwareLink };

function FormattedUserText({ content }: { content: string }) {
  const parts = content.split(/(\[\[[a-zA-Z]+:[^\]\n]+\]\])/g);
  return (
    <p className="whitespace-pre-wrap text-sm leading-relaxed">
      {parts.map((part, idx) => {
        const m = /^\[\[([a-zA-Z]+):([^\]\n]+)\]\]$/.exec(part);
        if (m) {
          const key = m[1].toLowerCase();
          const cls = COLOR_CLASS_MAP[key];
          if (cls) {
            return (
              <span key={idx} className={cls} data-cpr-color={key}>
                {m[2]}
              </span>
            );
          }
        }
        return part;
      })}
    </p>
  );
}
import { rollQuickDice } from "../api";
import type {
  ActiveTurnInfo,
  CharacterRecord,
  ChatMessageNode,
  DiceRollResult,
  LibraryEntry,
  StatePatchEvent,
} from "../types";

export interface StreamingTurnState {
  userText: string;
  speakerName?: string;
  text: string;
  citations: LibraryEntry[];
  rolls: DiceRollResult[];
  patches: StatePatchEvent[];
  libraryAdded: LibraryEntry[];
  warnings: string[];
  overclock: boolean;
  truncateFromId?: string;
  startedAt?: number;
}

interface ChatPaneProps {
  campaignId: string | null;
  messages: ChatMessageNode[];
  streaming: StreamingTurnState | null;
  characters: CharacterRecord[];
  selectedSpeakerId: string;
  activeTurn: ActiveTurnInfo | null;
  selfClientId: string;
  onChangeSpeakerId: (charId: string) => void;
  onSend: (text: string, opts: { overclock: boolean; luckSpend: number; speakerCharacterId?: string; speakerName?: string }) => Promise<void>;
  onSendIntro?: () => Promise<void>;
  onEditUserMessage: (msg: ChatMessageNode, newText: string, overclock: boolean, luckSpend?: number) => Promise<void>;
  onUpdateMessageInPlace: (msg: ChatMessageNode, newText: string) => Promise<void>;
  onDeleteMessage: (msg: ChatMessageNode, scope?: "single" | "branch") => Promise<void>;
  onRegenerate: (msg: ChatMessageNode, guidance?: string) => Promise<void>;
  onSwitchBranch: (messageId: string) => Promise<void>;
  onStopStream: () => void;
  onCompressMemory?: () => Promise<void>;
  compressingMemory?: boolean;
  onInspectEntry: (entry: LibraryEntry) => void;
  onNotify: (msg: string) => void;
}

const QUICK_DICE_PRESETS = [
  { label: "d10", count: 1, sides: 10 },
  { label: "d6", count: 1, sides: 6 },
  { label: "2d6", count: 2, sides: 6 },
  { label: "3d6", count: 3, sides: 6 },
  { label: "4d6", count: 4, sides: 6 },
  { label: "d100", count: 1, sides: 100 },
];

function RollCard({ roll }: { roll: DiceRollResult }) {
  const passed = roll.success;
  const primaryDie =
    roll.die ?? (Array.isArray(roll.dice) && roll.dice.length > 0 ? roll.dice[0] : undefined);
  const explosion = roll.explosion ?? roll.critical_adjustment ?? 0;
  const badgeStyle =
    passed === true
      ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
      : passed === false
        ? "border-rose-500/40 bg-rose-500/10 text-rose-300"
        : "border-cyan-500/40 bg-cyan-500/10 text-cyan-300";

  return (
    <div className={`rounded-lg border px-3 py-2 text-xs ${badgeStyle}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 font-semibold">
          <Dices className="h-3.5 w-3.5 shrink-0" />
          <span>{roll.actor ?? "Check"}</span>
          <span className="opacity-75">·</span>
          <span className="font-mono">
            {roll.skill ? `${roll.skill} (${roll.stat})` : roll.stat ?? "Roll"}
          </span>
          {roll.overclock && (
            <span className="rounded bg-rose-500/25 px-1.5 py-0.5 font-mono text-[10px] text-rose-200">
              OVERCLOCK +2
            </span>
          )}
          {(roll.luck_spent ?? 0) > 0 && (
            <span className="rounded bg-amber-500/25 px-1.5 py-0.5 font-mono text-[10px] text-amber-200">
              LUCK +{roll.luck_spent}
            </span>
          )}
        </div>
        <div className="font-mono font-bold">
          {roll.total}
          {roll.dv !== undefined ? ` vs DV ${roll.dv}` : ""}
          {passed === true ? " · SUCCESS" : passed === false ? " · FAIL" : ""}
        </div>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-2 opacity-85">
        {roll.reason && <span>{roll.reason}</span>}
        {primaryDie !== undefined && (
          <span className="font-mono text-[11px]">
            d10={primaryDie}
            {explosion ? ` (${explosion > 0 ? "+" : ""}${explosion})` : ""}
            {roll.wound_modifier ? ` · wound ${roll.wound_modifier}` : ""}
            {roll.luck_spent ? ` · LUCK +${roll.luck_spent}` : ""}
          </span>
        )}
      </div>
    </div>
  );
}

function PatchPill({ patch }: { patch: StatePatchEvent }) {
  const entries = Object.entries(patch.after);
  const label =
    patch.target === "character"
      ? patch.name ?? "Character"
      : patch.target === "solo"
        ? patch.name ?? "Solo Ops"
        : "Campaign";
  return (
    <div className="inline-flex flex-wrap items-center gap-1.5 rounded-md border border-slate-700/80 bg-slate-900/90 px-2.5 py-1 text-[11px] text-slate-300">
      <span className="font-semibold text-cyan-300">{label}:</span>
      {entries.map(([k, val]) => {
        const prev = patch.before[k];
        const displayPrev = typeof prev === "object" ? JSON.stringify(prev) : String(prev ?? "—");
        const displayAfter = typeof val === "object" ? JSON.stringify(val) : String(val);
        return (
          <span key={k} className="font-mono">
            {k}: {displayPrev} → <strong className="text-slate-100">{displayAfter}</strong>
          </span>
        );
      })}
    </div>
  );
}

function BranchPager({
  node,
  disabled,
  onSwitch,
}: {
  node: ChatMessageNode;
  disabled: boolean;
  onSwitch: (id: string) => void;
}) {
  const count = node.sibling_count ?? 1;
  const index = node.sibling_index ?? 0;
  const ids = node.sibling_ids ?? [];
  if (count <= 1 || ids.length <= 1) return null;

  const prevId = ids[(index - 1 + ids.length) % ids.length];
  const nextId = ids[(index + 1) % ids.length];

  return (
    <div className="inline-flex items-center gap-0.5 rounded border border-slate-700/80 bg-slate-900/80 px-1 py-0.5 font-mono text-[11px] text-slate-300">
      <button
        type="button"
        disabled={disabled}
        onClick={() => onSwitch(prevId)}
        title="Previous branch"
        className="rounded p-0.5 hover:bg-slate-800 disabled:opacity-40"
      >
        <ChevronLeft className="h-3 w-3" />
      </button>
      <span className="px-1">
        {index + 1}/{count}
      </span>
      <button
        type="button"
        disabled={disabled}
        onClick={() => onSwitch(nextId)}
        title="Next branch"
        className="rounded p-0.5 hover:bg-slate-800 disabled:opacity-40"
      >
        <ChevronRight className="h-3 w-3" />
      </button>
    </div>
  );
}

export function ChatPane({
  campaignId,
  messages,
  streaming,
  characters,
  selectedSpeakerId,
  activeTurn,
  selfClientId,
  onChangeSpeakerId,
  onSend,
  onSendIntro,
  onEditUserMessage,
  onUpdateMessageInPlace,
  onDeleteMessage,
  onRegenerate,
  onSwitchBranch,
  onStopStream,
  onCompressMemory,
  compressingMemory,
  onInspectEntry,
  onNotify,
}: ChatPaneProps) {
  const [input, setInput] = useState("");
  const [overclock, setOverclock] = useState(false);
  const [luckSpend, setLuckSpend] = useState(0);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editMode, setEditMode] = useState<"branch" | "inplace">("branch");
  const [editText, setEditText] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [guidanceMsgId, setGuidanceMsgId] = useState<string | null>(null);
  const [guidanceText, setGuidanceText] = useState("");
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [diceOpen, setDiceOpen] = useState(false);
  const [colorBarOpen, setColorBarOpen] = useState(false);
  const [lastQuickRoll, setLastQuickRoll] = useState<string | null>(null);
  const [showJumpToLatest, setShowJumpToLatest] = useState(false);
  const [streamElapsedSec, setStreamElapsedSec] = useState<number>(0);
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!streaming?.startedAt) {
      setStreamElapsedSec(0);
      return;
    }
    const update = () => {
      setStreamElapsedSec(Math.max(0, (Date.now() - streaming.startedAt!) / 1000));
    };
    update();
    const timer = setInterval(update, 100);
    return () => clearInterval(timer);
  }, [streaming?.startedAt]);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const stickToBottomRef = useRef(true);
  const bottomRef = useRef<HTMLDivElement>(null);

  const clearInlinePopovers = () => {
    setEditingId(null);
    setConfirmDeleteId(null);
    setGuidanceMsgId(null);
  };

  const openEdit = (msg: ChatMessageNode, mode: "branch" | "inplace") => {
    setConfirmDeleteId(null);
    setGuidanceMsgId(null);
    setEditingId(msg.id);
    setEditMode(mode);
    setEditText(msg.content);
  };

  const openDeleteConfirm = (msgId: string) => {
    setEditingId(null);
    setGuidanceMsgId(null);
    setConfirmDeleteId(msgId);
  };

  const openGuidance = (msgId: string) => {
    setEditingId(null);
    setConfirmDeleteId(null);
    setGuidanceText("");
    setGuidanceMsgId((cur) => (cur === msgId ? null : msgId));
  };

  const handleScroll = () => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    const nearBottom = distanceFromBottom <= 72;
    stickToBottomRef.current = nearBottom;
    setShowJumpToLatest(!nearBottom);
  };

  const scrollToBottom = (smooth = false) => {
    const el = scrollContainerRef.current;
    if (!el) return;
    stickToBottomRef.current = true;
    setShowJumpToLatest(false);
    if (smooth && typeof el.scrollTo === "function") {
      el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    } else {
      el.scrollTop = el.scrollHeight;
    }
  };

  useEffect(() => {
    stickToBottomRef.current = true;
    setShowJumpToLatest(false);
    clearInlinePopovers();
    setEditText("");
    setGuidanceText("");
    const el = scrollContainerRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [campaignId]);

  useEffect(() => {
    const ta = composerRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(160, Math.max(52, ta.scrollHeight))}px`;
  }, [input]);

  useEffect(() => {
    if (!editingId && !confirmDeleteId && !guidanceMsgId) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        clearInlinePopovers();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [editingId, confirmDeleteId, guidanceMsgId]);

  useEffect(() => {
    const ids = new Set(messages.map((m) => m.id));
    if (editingId && !ids.has(editingId)) setEditingId(null);
    if (confirmDeleteId && !ids.has(confirmDeleteId)) setConfirmDeleteId(null);
    if (guidanceMsgId && !ids.has(guidanceMsgId)) setGuidanceMsgId(null);
  }, [messages, editingId, confirmDeleteId, guidanceMsgId]);

  useEffect(() => {
    if (!stickToBottomRef.current) return;
    const el = scrollContainerRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    } else {
      bottomRef.current?.scrollIntoView({ behavior: "auto" });
    }
  }, [messages.length, streaming?.text, streaming?.rolls.length, streaming?.truncateFromId]);

  const visibleMessages = (() => {
    if (!streaming?.truncateFromId) return messages;
    const idx = messages.findIndex((m) => m.id === streaming.truncateFromId);
    return idx >= 0 ? messages.slice(0, idx) : messages;
  })();

  const busy = Boolean(streaming) || Boolean(deletingId);
  const lockedByPeer = Boolean(activeTurn && activeTurn.client_id !== selfClientId);
  const speakerChar = characters.find((c) => c.id === selectedSpeakerId) ?? null;
  const luckChar = speakerChar ?? characters[0] ?? null;
  const maxLuck = Math.max(0, luckChar?.luck_remaining ?? 0);
  const effectiveLuck = Math.min(luckSpend, maxLuck);

  const insertColorTag = (colorId: string) => {
    const ta = composerRef.current;
    if (!ta) {
      setInput((prev) => `${prev}[[${colorId}:text]]`);
      return;
    }
    const start = ta.selectionStart ?? input.length;
    const end = ta.selectionEnd ?? input.length;
    const selected = input.slice(start, end) || "highlighted text";
    const wrapped = `[[${colorId}:${selected}]]`;
    const next = input.slice(0, start) + wrapped + input.slice(end);
    setInput(next);
    const selStart = start + colorId.length + 3;
    const selEnd = selStart + selected.length;
    requestAnimationFrame(() => {
      ta.focus();
      ta.setSelectionRange(selStart, selEnd);
    });
  };

  const handleQuickDice = async (count: number, sides: number, reason: string) => {
    try {
      const res = await rollQuickDice(count, sides, reason);
      const summary = `[Rolled ${count}d${sides}: ${res.dice.join(", ")} = ${res.total}]`;
      setLastQuickRoll(`${count}d${sides} -> ${res.total} (${res.dice.join("+")})`);
      setInput((prev) => (prev.trim() ? `${prev.trim()} ${summary}` : summary));
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Dice roll failed");
    }
  };

  const handleSubmit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || !campaignId || busy || lockedByPeer) return;

    // /roll NdS slash command
    const rollMatch = /^\/roll\s+(\d{1,2})d(\d{1,3})(?:\s+(.*))?$/i.exec(trimmed);
    if (rollMatch) {
      const count = Math.max(1, Math.min(20, parseInt(rollMatch[1], 10)));
      const sides = Math.max(2, Math.min(100, parseInt(rollMatch[2], 10)));
      const reason = rollMatch[3]?.trim() || `Manual ${count}d${sides}`;
      setInput("");
      try {
        const res = await rollQuickDice(count, sides, reason);
        const resultText = `${reason}: rolled ${count}d${sides} [${res.dice.join(", ")}] = ${res.total}`;
        setLastQuickRoll(resultText);
        onNotify(resultText);
      } catch (err) {
        onNotify(err instanceof Error ? err.message : "Roll failed");
      }
      return;
    }

    setInput("");
    const useOverclock = overclock;
    const useLuck = Math.min(luckSpend, maxLuck);
    setOverclock(false);
    setLuckSpend(0);
    stickToBottomRef.current = true;
    setShowJumpToLatest(false);
    await onSend(trimmed, {
      overclock: useOverclock,
      luckSpend: useLuck,
      speakerCharacterId: speakerChar?.id,
      speakerName: speakerChar?.name,
    });
  };

  const handleEditSubmit = async (msg: ChatMessageNode) => {
    const trimmed = editText.trim();
    if (!trimmed || busy) return;
    setEditingId(null);
    if (editMode === "inplace") {
      await onUpdateMessageInPlace(msg, trimmed);
    } else {
      await onEditUserMessage(
        msg,
        trimmed,
        Boolean(msg.metadata?.overclock),
        msg.metadata?.luck_spend,
      );
    }
  };

  const handleCopy = async (msg: ChatMessageNode) => {
    try {
      await navigator.clipboard.writeText(msg.content);
      setCopiedId(msg.id);
      setTimeout(() => setCopiedId((cur) => (cur === msg.id ? null : cur)), 1600);
    } catch {
      onNotify("Could not copy to clipboard.");
    }
  };

  const handleGuidedRetry = async (msg: ChatMessageNode) => {
    const note = guidanceText.trim();
    setGuidanceMsgId(null);
    setGuidanceText("");
    await onRegenerate(msg, note || undefined);
  };

  const triggerDelete = async (msg: ChatMessageNode, scope: "single" | "branch") => {
    if (busy) return;
    setConfirmDeleteId(null);
    setDeletingId(msg.id);
    try {
      await onDeleteMessage(msg, scope);
    } finally {
      setDeletingId(null);
    }
  };

  if (!campaignId) {
    return (
      <div className="flex h-full flex-col items-center justify-center p-6 sm:p-8 text-center bg-[#080b12]/75">
        <div className="cyber-hud-card cyber-holo-sweep relative w-full max-w-lg overflow-hidden rounded-lg bg-[#0b101b] p-7">
          <img
            src={cyberHeroBackdrop}
            alt=""
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 h-full w-full object-cover opacity-35"
          />
          <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-[#070a11] via-[#0a0f1a]/82 to-[#070a11]/65" />
          <div className="relative z-10 flex flex-col items-center gap-3">
            <span className="inline-flex items-center gap-1.5 rounded border border-rose-500/45 bg-rose-500/15 px-2.5 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-[0.2em] text-rose-300">
              <span className="h-1.5 w-1.5 rounded-full bg-rose-400 shadow-[0_0_8px_#fb7185]" />
              NETLINK // STANDBY
            </span>
            <h2
              data-text="Welcome to Night City"
              className="cyber-glitch-title font-cyber-display text-xl font-bold tracking-[0.1em] text-slate-100 uppercase"
            >
              Welcome to Night City
            </h2>
            <p className="max-w-md font-cyber-hud text-sm leading-relaxed text-slate-300">
              Create or select a campaign in the top bar to jack into the Time of the Red with your AI Game Master.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="relative flex h-full flex-col bg-[#0a0e16]/75">
      <div className="relative flex min-h-0 flex-1 flex-col">
        <div
          ref={scrollContainerRef}
          onScroll={handleScroll}
          data-testid="chat-scroll-container"
          className="flex-1 overflow-y-auto px-4 py-5"
        >
        <div className="mx-auto max-w-3xl space-y-5">
          {visibleMessages.length === 0 && !streaming && (
            <div className="cyber-hud-card cyber-holo-sweep relative mt-6 overflow-hidden rounded-lg bg-[#0b101c]">
              <div className="relative h-36 w-full overflow-hidden border-b border-cyan-500/25 sm:h-44">
                <img
                  src={nightMarketHero}
                  alt=""
                  aria-hidden="true"
                  className="h-full w-full object-cover object-center opacity-70"
                />
                <div className="absolute inset-0 bg-gradient-to-t from-[#0b101c] via-[#0b101c]/55 to-transparent" />
                <div className="absolute inset-x-0 bottom-3 flex flex-col items-center px-4 text-center">
                  <span className="mb-1.5 inline-flex items-center gap-1.5 rounded border border-cyan-400/50 bg-slate-950/80 px-2.5 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-[0.22em] text-cyan-300 backdrop-blur-xs">
                    TIME OF THE RED // 2045
                  </span>
                  <h3
                    data-text="Ready to Run the Streets"
                    className="cyber-glitch-title block font-cyber-display text-lg font-bold tracking-[0.1em] text-slate-100 uppercase sm:text-xl"
                  >
                    Ready to Run the Streets
                  </h3>
                </div>
              </div>

              <div className="relative z-10 flex flex-col items-center gap-4 px-6 py-5 text-center">
                <p className="max-w-lg font-cyber-hud text-sm leading-relaxed text-slate-300">
                  Jack in for a full Cyberpunk RED orientation — covering Night City 2045, how d10 checks and STATs work, and what Roles you can play — or type your opening move below.
                </p>

                <button
                  type="button"
                  disabled={busy || lockedByPeer || !onSendIntro}
                  onClick={() => void onSendIntro?.()}
                  className="cyber-cta-pulse cyber-cut-sm inline-flex items-center gap-2.5 border border-rose-500/60 bg-gradient-to-r from-rose-600/90 via-rose-600/80 to-cyan-700/80 px-5 py-2.5 font-cyber-hud text-sm font-bold tracking-wider text-white uppercase transition hover:from-rose-500 hover:to-cyan-600 disabled:opacity-45"
                >
                  <Terminal className="h-4 w-4 text-cyan-200" />
                  <span>Introductory First Message</span>
                </button>
              </div>
            </div>
          )}

          {visibleMessages.map((msg, msgIdx) => {
            const isUser = msg.role === "user";
            const isEditing = editingId === msg.id;
            const isConfirmingDelete = confirmDeleteId === msg.id;
            const isDeletingThis = deletingId === msg.id;
            const hasMessagesBelow = msgIdx < visibleMessages.length - 1;
            const hasUserParent = !isUser && Boolean(msg.parent_id) && visibleMessages.some((m) => m.id === msg.parent_id && m.role === "user");
            const isGuiding = guidanceMsgId === msg.id;
            const rolls = msg.metadata?.rolls ?? [];
            const patches = msg.metadata?.patches ?? [];
            const citations = msg.metadata?.citation_cards ?? [];
            const warnings = msg.metadata?.warnings ?? [];
            const speakerLabel = isUser ? msg.metadata?.speaker_name || "You" : "GM";

            return (
              <div
                key={msg.id}
                className={`group flex flex-col ${isUser ? "items-end" : "items-start"}`}
              >
                <div
                  className={`rounded-xl px-4 py-3 transition ${
                    isUser
                      ? "max-w-[88%] border border-cyan-500/30 bg-cyan-950/35 text-slate-100"
                      : "w-full border border-slate-800/90 bg-[#101624] text-slate-100"
                  }`}
                >
                  {/* Message Header */}
                  <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-400">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="inline-flex items-center gap-1 font-mono font-semibold uppercase tracking-wider text-slate-300">
                        {isUser && <User className="h-3 w-3 text-cyan-400" />}
                        {speakerLabel}
                      </span>
                      {!isUser && msg.model && (
                        <span className="rounded bg-slate-800/80 px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
                          {msg.model}
                        </span>
                      )}
                      {!isUser && msg.metadata?.generation_stats && (
                        <span
                          title={`${msg.metadata.generation_stats.completion_tokens ?? "?"} tokens${msg.metadata.generation_stats.estimated ? " (estimated)" : ""} in ${msg.metadata.generation_stats.elapsed_seconds.toFixed(2)}s`}
                          className="inline-flex items-center gap-1 rounded border border-cyan-500/25 bg-cyan-950/35 px-1.5 py-0.5 font-mono text-[10px] text-cyan-300"
                        >
                          <Clock className="h-2.5 w-2.5" />
                          <span>
                            {msg.metadata.generation_stats.elapsed_seconds.toFixed(1)}s ·{" "}
                            {msg.metadata.generation_stats.tokens_per_second.toFixed(1)} tok/s
                          </span>
                        </span>
                      )}
                      {msg.metadata?.overclock && (
                        <span className="inline-flex items-center gap-1 rounded bg-rose-500/20 px-1.5 py-0.5 font-mono text-[10px] text-rose-300">
                          <Zap className="h-3 w-3" /> OVERCLOCK
                        </span>
                      )}
                      {(msg.metadata?.luck_spend ?? 0) > 0 && (
                        <span className="inline-flex items-center gap-1 rounded bg-amber-500/20 px-1.5 py-0.5 font-mono text-[10px] text-amber-300">
                          LUCK +{msg.metadata?.luck_spend}
                        </span>
                      )}
                      {msg.metadata?.edited && (
                        <span className="font-mono text-[10px] text-slate-500">(edited)</span>
                      )}
                    </div>

                    {/* QoL Action Controls */}
                    <div className="flex flex-wrap items-center gap-1">
                      <BranchPager
                        node={msg}
                        disabled={busy}
                        onSwitch={onSwitchBranch}
                      />

                      <button
                        type="button"
                        onClick={() => void handleCopy(msg)}
                        title="Copy message"
                        aria-label="Copy message"
                        className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-slate-200"
                      >
                        {copiedId === msg.id ? (
                          <Check className="h-3.5 w-3.5 text-emerald-400" />
                        ) : (
                          <Copy className="h-3.5 w-3.5" />
                        )}
                      </button>

                      {isUser && !isEditing && (
                        <button
                          type="button"
                          disabled={busy || lockedByPeer}
                          onClick={() => openEdit(msg, "branch")}
                          title="Edit & branch from this message"
                          aria-label="Edit & branch"
                          className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-cyan-300 disabled:opacity-40"
                        >
                          <Edit3 className="h-3.5 w-3.5" />
                        </button>
                      )}

                      {!isEditing && (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => openEdit(msg, "inplace")}
                          title="Edit message text in-place"
                          aria-label="Edit text in-place"
                          className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-slate-200 disabled:opacity-40"
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                      )}

                      {!isUser && (
                        <>
                          <button
                            type="button"
                            disabled={busy || lockedByPeer || !hasUserParent}
                            onClick={() => void onRegenerate(msg)}
                            title={
                              hasUserParent
                                ? "Regenerate / swipe alternative GM reply"
                                : "Cannot regenerate: no preceding player message"
                            }
                            aria-label="Regenerate reply"
                            className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-cyan-300 disabled:opacity-40"
                          >
                            <RefreshCw className="h-3.5 w-3.5" />
                          </button>
                          <button
                            type="button"
                            disabled={busy || lockedByPeer || !hasUserParent}
                            onClick={() => openGuidance(msg.id)}
                            title={
                              hasUserParent
                                ? "Regenerate with Director note"
                                : "Cannot regenerate: no preceding player message"
                            }
                            aria-label="Guided regenerate"
                            className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-amber-300 disabled:opacity-40"
                          >
                            <Wand2 className="h-3.5 w-3.5" />
                          </button>
                        </>
                      )}

                      {isConfirmingDelete ? (
                        <div className="inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded border border-rose-500/40 bg-rose-500/10 px-1.5 py-0.5">
                          {hasMessagesBelow ? (
                            <>
                              <button
                                type="button"
                                disabled={busy}
                                onClick={() => void triggerDelete(msg, "single")}
                                title="Delete only this message (keep messages below)"
                                className="font-mono text-[10px] font-semibold text-amber-300 hover:text-amber-200 disabled:opacity-40"
                              >
                                This msg
                              </button>
                              <button
                                type="button"
                                disabled={busy}
                                onClick={() => void triggerDelete(msg, "branch")}
                                title="Delete this message and everything below it"
                                className="font-mono text-[10px] font-semibold text-rose-300 hover:text-rose-200 disabled:opacity-40"
                              >
                                + Below
                              </button>
                            </>
                          ) : (
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => void triggerDelete(msg, "branch")}
                              className="font-mono text-[10px] font-semibold text-rose-300 hover:text-rose-200 disabled:opacity-40"
                            >
                              Delete
                            </button>
                          )}
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => setConfirmDeleteId(null)}
                            aria-label="Cancel delete"
                            className="text-slate-400 hover:text-slate-200 disabled:opacity-40"
                          >
                            <X className="h-3 w-3" />
                          </button>
                        </div>
                      ) : (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => openDeleteConfirm(msg.id)}
                          title={isDeletingThis ? "Deleting..." : "Delete message"}
                          aria-label="Delete message"
                          className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-rose-400 disabled:opacity-40"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Body or Edit Box */}
                  {isEditing ? (
                    <div className="space-y-2">
                      <textarea
                        autoFocus
                        value={editText}
                        onChange={(e) => setEditText(e.target.value)}
                        onKeyDown={(e) => {
                          if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
                            e.preventDefault();
                            void handleEditSubmit(msg);
                          }
                        }}
                        rows={3}
                        className="w-full rounded-md border border-cyan-500/60 bg-slate-950 p-2 text-sm text-slate-100 focus:outline-none"
                      />
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-mono text-[10px] text-slate-500">
                          Ctrl+Enter to save · Esc to cancel
                        </span>
                        <div className="flex items-center gap-2">
                          <button
                            type="button"
                            onClick={() => setEditingId(null)}
                            className="rounded px-2.5 py-1 text-xs text-slate-400 hover:text-slate-200"
                          >
                            Cancel
                          </button>
                          <button
                            type="button"
                            onClick={() => void handleEditSubmit(msg)}
                            className="rounded bg-cyan-600 px-3 py-1 text-xs font-semibold text-white hover:bg-cyan-500"
                          >
                            {editMode === "inplace" ? "Save Text" : "Save & Branch"}
                          </button>
                        </div>
                      </div>
                    </div>
                  ) : isUser ? (
                    <FormattedUserText content={msg.content} />
                  ) : (
                    <div className="space-y-3">
                      {citations.length > 0 && (
                        <div className="flex flex-wrap gap-1.5">
                          {citations.map((entry) => (
                            <button
                              key={entry.id}
                              type="button"
                              onClick={() => onInspectEntry(entry)}
                              className="inline-flex items-center gap-1 rounded-md border border-cyan-500/30 bg-cyan-500/10 px-2 py-0.5 text-[11px] text-cyan-200 hover:bg-cyan-500/20"
                            >
                              <BookOpen className="h-3 w-3" />
                              <span>{entry.name}</span>
                              {entry.printed_page && (
                                <span className="font-mono opacity-75">p.{entry.printed_page}</span>
                              )}
                            </button>
                          ))}
                        </div>
                      )}

                      {rolls.length > 0 && (
                        <div className="space-y-1.5">
                          {rolls.map((r, i) => (
                            <RollCard key={i} roll={r} />
                          ))}
                        </div>
                      )}

                      <div className="prose prose-invert prose-sm max-w-none leading-relaxed">
                        <Streamdown
                          key={`${msg.id}:${msg.content}`}
                          mode="static"
                          components={STREAMDOWN_COMPONENTS}
                        >
                          {formatColorMarkdown(msg.content)}
                        </Streamdown>
                      </div>

                      {patches.length > 0 && (
                        <div className="flex flex-wrap gap-1.5 pt-1">
                          {patches.map((p, i) => (
                            <PatchPill key={i} patch={p} />
                          ))}
                        </div>
                      )}

                      {warnings.length > 0 && (
                        <div className="space-y-1">
                          {warnings.map((w, i) => (
                            <div
                              key={i}
                              className="flex flex-wrap items-center justify-between gap-2 rounded border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 text-xs text-amber-300"
                            >
                              <span className="flex items-center gap-1.5">
                                <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                                <span>{w}</span>
                              </span>
                              {onCompressMemory && w.toLowerCase().includes("compress") && (
                                <button
                                  type="button"
                                  disabled={Boolean(compressingMemory) || busy}
                                  onClick={() => void onCompressMemory()}
                                  className="rounded border border-amber-400/50 bg-amber-500/20 px-2 py-0.5 text-[11px] font-semibold text-amber-100 hover:bg-amber-500/30 disabled:opacity-50"
                                >
                                  {compressingMemory ? "Compressing..." : "Compress to Library"}
                                </button>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Guided Regenerate Drawer */}
                  {isGuiding && !isEditing && (
                    <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-slate-800 pt-2.5">
                      <input
                        autoFocus
                        type="text"
                        value={guidanceText}
                        onChange={(e) => setGuidanceText(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.preventDefault();
                            void handleGuidedRetry(msg);
                          }
                        }}
                        placeholder="Director note (e.g. 'make the fixer suspicious', 'roll Streetwise DV 15')..."
                        className="flex-1 min-w-[200px] rounded border border-amber-500/50 bg-slate-950 px-2.5 py-1 text-xs text-slate-100 focus:outline-none"
                      />
                      <button
                        type="button"
                        onClick={() => void handleGuidedRetry(msg)}
                        className="rounded bg-amber-600 px-3 py-1 text-xs font-semibold text-white hover:bg-amber-500"
                      >
                        Retry
                      </button>
                      <button
                        type="button"
                        onClick={() => setGuidanceMsgId(null)}
                        className="rounded px-2 py-1 text-xs text-slate-400 hover:text-slate-200"
                      >
                        Cancel
                      </button>
                    </div>
                  )}
                </div>
              </div>
            );
          })}

          {streaming && (
            <div className="space-y-3">
              {streaming.userText && (
                <div className="flex justify-end">
                  <div className="max-w-[88%] rounded-xl border border-cyan-500/30 bg-cyan-950/35 px-4 py-3 text-slate-100">
                    <div className="mb-1 flex items-center gap-2 text-[11px] text-slate-400">
                      <span className="font-mono font-semibold uppercase tracking-wider text-slate-300">
                        {streaming.speakerName || "You"}
                      </span>
                      {streaming.overclock && (
                        <span className="inline-flex items-center gap-1 rounded bg-rose-500/20 px-1.5 py-0.5 font-mono text-[10px] text-rose-300">
                          <Zap className="h-3 w-3" /> OVERCLOCK
                        </span>
                      )}
                    </div>
                    <p className="whitespace-pre-wrap text-sm leading-relaxed">{streaming.userText}</p>
                  </div>
                </div>
              )}

              <div className="rounded-xl border border-rose-500/35 bg-[#101624] px-4 py-3 text-slate-100 shadow-[0_0_24px_rgba(244,63,94,0.08)]">
                <div className="mb-2 flex items-center justify-between gap-2 text-[11px] text-rose-300">
                  <div className="flex items-center gap-2">
                    <span className="inline-flex items-end gap-0.5" aria-hidden="true">
                      <span className="cyber-eq-bar" style={{ animationDelay: "0ms" }} />
                      <span className="cyber-eq-bar" style={{ animationDelay: "180ms" }} />
                      <span className="cyber-eq-bar" style={{ animationDelay: "360ms" }} />
                    </span>
                    <span className="font-mono font-semibold uppercase tracking-wider">
                      GM Streaming...
                    </span>
                  </div>
                  {streaming.startedAt && (
                    <span className="font-mono text-[10px] text-cyan-300">
                      {streamElapsedSec.toFixed(1)}s
                    </span>
                  )}
                </div>

                <div className="space-y-3">
                  {streaming.citations.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {streaming.citations.map((entry) => (
                        <button
                          key={entry.id}
                          type="button"
                          onClick={() => onInspectEntry(entry)}
                          className="inline-flex items-center gap-1 rounded-md border border-cyan-500/30 bg-cyan-500/10 px-2 py-0.5 text-[11px] text-cyan-200"
                        >
                          <BookOpen className="h-3 w-3" />
                          <span>{entry.name}</span>
                          {entry.printed_page && (
                            <span className="font-mono opacity-75">p.{entry.printed_page}</span>
                          )}
                        </button>
                      ))}
                    </div>
                  )}

                  {streaming.rolls.map((r, i) => (
                    <RollCard key={i} roll={r} />
                  ))}

                  {streaming.libraryAdded.map((entry) => (
                    <div
                      key={entry.id}
                      className="inline-flex items-center gap-1.5 rounded border border-amber-500/40 bg-amber-500/10 px-2.5 py-1 text-xs text-amber-200"
                    >
                      <Sparkles className="h-3.5 w-3.5" />
                      Added Homebrew: {entry.name}
                    </div>
                  ))}

                  <div className="prose prose-invert prose-sm max-w-none leading-relaxed">
                    {streaming.text ? (
                      <Streamdown components={STREAMDOWN_COMPONENTS}>
                        {formatColorMarkdown(streaming.text)}
                      </Streamdown>
                    ) : (
                      <span className="text-xs italic text-slate-400">
                        Checking rules & resolving actions...
                      </span>
                    )}
                  </div>

                  {streaming.patches.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {streaming.patches.map((p, i) => (
                        <PatchPill key={i} patch={p} />
                      ))}
                    </div>
                  )}

                  {streaming.warnings.map((w, i) => (
                    <div
                      key={i}
                      className="flex items-center gap-1.5 rounded border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 text-xs text-amber-300"
                    >
                      <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                      <span>{w}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          <div ref={bottomRef} />
        </div>
      </div>

        {showJumpToLatest && (
          <div className="pointer-events-none absolute inset-x-0 bottom-3 z-20 flex justify-center px-4">
            <button
              type="button"
              onClick={() => scrollToBottom(true)}
              className="pointer-events-auto inline-flex items-center gap-1.5 rounded-full border border-cyan-500/50 bg-[#0d111a]/95 px-3 py-1.5 text-xs font-medium text-cyan-200 shadow-lg backdrop-blur hover:border-cyan-400 hover:bg-slate-900"
            >
              <ArrowDown className="h-3.5 w-3.5" />
              Jump to latest
            </button>
          </div>
        )}
      </div>

      {/* Composer Dock */}
      <form
        onSubmit={handleSubmit}
        className="border-t border-slate-800/90 bg-[#0c101a]/92 px-4 py-3 backdrop-blur-md"
      >
        <div className="mx-auto max-w-3xl space-y-2">
          {lockedByPeer && (
            <div className="flex items-center gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-1.5 text-xs text-amber-300">
              <Lock className="h-3.5 w-3.5 shrink-0" />
              <span>GM is resolving {activeTurn?.player_name}&apos;s turn...</span>
            </div>
          )}

          {diceOpen && (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-800 bg-[#101624] px-3 py-2 text-xs">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="font-mono text-[11px] text-slate-400">Quick Dice:</span>
                {QUICK_DICE_PRESETS.map((p) => (
                  <button
                    key={p.label}
                    type="button"
                    onClick={() => void handleQuickDice(p.count, p.sides, `Quick ${p.label}`)}
                    className="rounded border border-slate-700 bg-slate-900 px-2 py-0.5 font-mono text-[11px] text-cyan-300 hover:border-cyan-400"
                  >
                    {p.label}
                  </button>
                ))}
              </div>
              {lastQuickRoll && (
                <span className="font-mono text-[11px] text-emerald-300">{lastQuickRoll}</span>
              )}
            </div>
          )}

          {colorBarOpen && (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-800 bg-[#101624] px-3 py-2 text-xs">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="font-mono text-[11px] text-slate-400">Highlight Color:</span>
                {COLOR_SWATCHES.map((swatch) => (
                  <button
                    key={swatch.id}
                    type="button"
                    onClick={() => insertColorTag(swatch.id)}
                    className="inline-flex items-center gap-1.5 rounded border border-slate-700 bg-slate-900 px-2 py-0.5 text-[11px] text-slate-200 hover:border-cyan-400"
                  >
                    <span className={`h-2 w-2 rounded-full ${swatch.dotClass}`} />
                    {swatch.label}
                  </button>
                ))}
              </div>
              <span className="font-mono text-[10px] text-slate-500">
                Syntax: [[cyan:word]]
              </span>
            </div>
          )}

          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2">
              {characters.length > 0 && (
                <select
                  aria-label="Speaking character"
                  value={selectedSpeakerId}
                  onChange={(e) => onChangeSpeakerId(e.target.value)}
                  className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200 focus:border-cyan-400 focus:outline-none"
                >
                  <option value="">Party / General</option>
                  {characters.map((c) => (
                    <option key={c.id} value={c.id}>
                      As: {c.name}
                    </option>
                  ))}
                </select>
              )}

              <button
                type="button"
                onClick={() => setOverclock((v) => !v)}
                title="Spend 2 Humanity to gain +2 on your primary check this turn"
                className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium transition ${
                  overclock
                    ? "border-rose-500 bg-rose-600/25 text-rose-200 shadow-[0_0_12px_rgba(244,63,94,0.25)]"
                    : "border-slate-700 bg-slate-900 text-slate-400 hover:text-slate-200"
                }`}
              >
                <Zap className="h-3.5 w-3.5" />
                Overclock (-2 Humanity / +2 Check)
              </button>

              {luckChar && (
                <div
                  title={`Commit LUCK before the roll (only spent if a check runs this turn; ${maxLuck} available)`}
                  className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs ${
                    effectiveLuck > 0
                      ? "border-amber-500/70 bg-amber-500/15 text-amber-200"
                      : "border-slate-700 bg-slate-900 text-slate-400"
                  }`}
                >
                  <span className="font-mono text-[11px] font-semibold">LUCK</span>
                  <button
                    type="button"
                    aria-label="Decrease Luck spend"
                    disabled={effectiveLuck <= 0}
                    onClick={() => setLuckSpend((v) => Math.max(0, v - 1))}
                    className="rounded p-0.5 hover:bg-slate-800 disabled:opacity-35"
                  >
                    <Minus className="h-3 w-3" />
                  </button>
                  <span className="min-w-[2.2rem] text-center font-mono text-[11px] font-semibold">
                    +{effectiveLuck}/{maxLuck}
                  </span>
                  <button
                    type="button"
                    aria-label="Increase Luck spend"
                    disabled={effectiveLuck >= maxLuck}
                    onClick={() => setLuckSpend((v) => Math.min(maxLuck, v + 1))}
                    className="rounded p-0.5 hover:bg-slate-800 disabled:opacity-35"
                  >
                    <Plus className="h-3 w-3" />
                  </button>
                </div>
              )}

              <button
                type="button"
                onClick={() => setDiceOpen((v) => !v)}
                className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs transition ${
                  diceOpen
                    ? "border-cyan-500/60 bg-cyan-500/15 text-cyan-200"
                    : "border-slate-700 bg-slate-900 text-slate-400 hover:text-slate-200"
                }`}
              >
                <Dices className="h-3.5 w-3.5" />
                Dice
              </button>

              <button
                type="button"
                onClick={() => setColorBarOpen((v) => !v)}
                title="Highlight selected text in color ([[cyan:text]])"
                className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs transition ${
                  colorBarOpen
                    ? "border-cyan-500/60 bg-cyan-500/15 text-cyan-200"
                    : "border-slate-700 bg-slate-900 text-slate-400 hover:text-slate-200"
                }`}
              >
                <Palette className="h-3.5 w-3.5" />
                Color
              </button>
            </div>

            <span className="text-[11px] text-slate-500">
              Enter to send · Shift+Enter for new line · <code className="text-slate-400">/roll 3d6</code>
            </span>
          </div>

          <div className="flex items-end gap-2">
            <textarea
              ref={composerRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void handleSubmit();
                }
              }}
              placeholder="Describe your action..."
              rows={2}
              disabled={busy || lockedByPeer}
              className="flex-1 resize-none rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-cyan-400 focus:outline-none disabled:opacity-60"
            />

            {busy ? (
              <button
                type="button"
                onClick={onStopStream}
                className="inline-flex h-10 items-center gap-1.5 rounded-lg bg-rose-600 px-4 text-xs font-semibold text-white hover:bg-rose-500"
              >
                <Square className="h-3.5 w-3.5 fill-current" />
                Stop
              </button>
            ) : (
              <button
                type="submit"
                disabled={!input.trim() || lockedByPeer}
                className="inline-flex h-10 items-center gap-1.5 rounded-lg bg-cyan-600 px-4 text-xs font-semibold text-white hover:bg-cyan-500 disabled:opacity-40"
              >
                <Send className="h-3.5 w-3.5" />
                Send
              </button>
            )}
          </div>
        </div>
      </form>
    </div>
  );
}
