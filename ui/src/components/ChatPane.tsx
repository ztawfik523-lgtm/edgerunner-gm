import { type ComponentProps, useEffect, useRef, useState } from "react";
import { Streamdown } from "streamdown";
import cyberHeroBackdrop from "../assets/cyber-hero-backdrop.jpg";
import {
  AlertTriangle,
  ArrowDown,
  BookOpen,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Clock,
  Copy,
  Dices,
  Edit3,
  EyeOff,
  Layers,
  Lock,
  Minus,
  Palette,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Send,
  Shield,
  Sparkles,
  Square,
  Trash2,
  User,
  UserPlus,
  Users,
  Wand2,
  X,
  Zap,
} from "lucide-react";
import { rollQuickDice } from "../api";
import {
  CHARACTER_COLOR_THEMES,
  isHexColor,
  normalizeColorHex,
  resolveCharacterColor,
} from "../utils/characterColors";
import type {
  ActiveTurnInfo,
  CampaignRecord,
  CharacterRecord,
  ChatMessageNode,
  DiceRollResult,
  LibraryEntry,
  PartyGroupingState,
  StatePatchEvent,
} from "../types";

export { CHARACTER_COLOR_THEMES };

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
  magenta: "font-medium text-fuchsia-300",
  sky: "font-medium text-sky-300",
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
  { id: "magenta", label: "Magenta", dotClass: "bg-fuchsia-400" },
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
    <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-100">
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

export interface StreamingTurnState {
  userText: string;
  speakerName?: string;
  speakerColor?: string;
  speakerPortraitUrl?: string;
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
  campaign?: CampaignRecord | null;
  partyGrouping?: PartyGroupingState | null;
  activeChannelId?: string;
  onChangeChannelId?: (channelId: string) => void;
  messages: ChatMessageNode[];
  streaming: StreamingTurnState | null;
  isPeerStreaming?: boolean;
  characters: CharacterRecord[];
  selectedSpeakerId: string;
  overclock?: boolean;
  onClearOverclock?: () => void;
  activeTurn: ActiveTurnInfo | null;
  selfClientId: string;
  isAdmin?: boolean;
  currentUsername?: string | null;
  requireCharacterToSpeak?: boolean;
  onUpdateCharacterColor?: (charId: string, color: string) => Promise<void>;
  onOpenCreateCharacter?: () => void;
  onSend: (
    text: string,
    opts: {
      overclock: boolean;
      luckSpend: number;
      speakerCharacterId?: string;
      speakerName?: string;
      gmMode?: "auto" | "force_gm" | "hold_gm";
    },
  ) => Promise<void>;
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

const GM_MODES = [
  {
    id: "auto" as const,
    label: "Smart GM",
    tip: "Smart GM: lets players chat together/OOC and triggers the GM on world/NPC actions. Click to cycle mode.",
    cls: "border-cyan-500/45 bg-cyan-500/15 text-cyan-200 hover:bg-cyan-500/25",
  },
  {
    id: "hold_gm" as const,
    label: "Party Chat",
    tip: "Party Chat (Hold GM): post dialogue or queue actions without triggering the GM yet. Click to cycle mode.",
    cls: "border-amber-500/45 bg-amber-500/15 text-amber-200 hover:bg-amber-500/25",
  },
  {
    id: "force_gm" as const,
    label: "Force GM",
    tip: "Force GM: always trigger an AI GM response immediately on send. Click to cycle mode.",
    cls: "border-rose-500/45 bg-rose-500/15 text-rose-200 hover:bg-rose-500/25",
  },
];

function RollCard({ roll, compact = false }: { roll: DiceRollResult; compact?: boolean }) {
  const passed = roll.success;
  const primaryDie =
    roll.die ?? (Array.isArray(roll.dice) && roll.dice.length > 0 ? roll.dice[0] : undefined);
  const explosion = roll.explosion ?? roll.critical_adjustment ?? 0;
  const badgeStyle =
    passed === true
      ? "border-emerald-500/45 bg-emerald-950/35 text-emerald-200"
      : passed === false
        ? "border-rose-500/45 bg-rose-950/35 text-rose-200"
        : "border-cyan-500/45 bg-cyan-950/35 text-cyan-200";

  return (
    <div className={`rounded-md border px-2.5 py-1.5 text-xs ${badgeStyle}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5 font-semibold">
          <Dices className="h-3.5 w-3.5 shrink-0 text-amber-300" />
          <span>{roll.actor ?? "Check"}</span>
          <span className="opacity-70">·</span>
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
          {passed === true ? " · PASS" : passed === false ? " · FAIL" : ""}
        </div>
      </div>
      {(!compact || primaryDie !== undefined || roll.reason) && (
        <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[11px] opacity-85">
          {roll.reason && <span>{roll.reason}</span>}
          {primaryDie !== undefined && (
            <span className="font-mono text-[10px]">
              [d10={primaryDie}
              {explosion ? ` ${explosion > 0 ? `+${explosion} crit` : `${explosion} fumble`}` : ""}
              {roll.wound_modifier ? ` · wound ${roll.wound_modifier}` : ""}]
            </span>
          )}
        </div>
      )}
    </div>
  );
}

function PatchPill({ patch }: { patch: StatePatchEvent }) {
  const entries = Object.entries(patch.after ?? {});
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
        const prev = patch.before?.[k];
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
  partyGrouping = null,
  activeChannelId = "main",
  onChangeChannelId,
  messages,
  streaming,
  isPeerStreaming = false,
  characters,
  selectedSpeakerId,
  overclock = false,
  onClearOverclock,
  activeTurn,
  selfClientId,
  isAdmin = true,
  currentUsername = null,
  requireCharacterToSpeak = true,
  onUpdateCharacterColor,
  onOpenCreateCharacter,
  onSend,
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
  const [luckSpend, setLuckSpend] = useState(0);
  const [gmMode, setGmMode] = useState<"auto" | "force_gm" | "hold_gm">("auto");
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
  const [gmOpsOpenIds, setGmOpsOpenIds] = useState<Record<string, boolean>>({});

  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const stickToBottomRef = useRef(true);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [colorPreview, setColorPreview] = useState<string | null>(null);
  const colorDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setColorPreview(null);
    return () => {
      if (colorDebounceRef.current) clearTimeout(colorDebounceRef.current);
    };
  }, [selectedSpeakerId]);

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

  // Filter characters this user is allowed to control/speak as
  const selectableCharacters = characters.filter((c) => {
    if (isAdmin) return true;
    const owner = String((c.detail as Record<string, unknown> | undefined)?.owner_username ?? "").trim();
    if (!owner) return true; // unowned characters can be claimed
    return Boolean(currentUsername && owner.toLowerCase() === currentUsername.toLowerCase());
  });

  const busy = (Boolean(streaming) && !isPeerStreaming) || Boolean(deletingId);
  const lockedByPeer = Boolean(activeTurn && activeTurn.client_id !== selfClientId);
  const speakerChar = selectableCharacters.find((c) => c.id === selectedSpeakerId) ?? null;
  const luckChar = speakerChar ?? selectableCharacters[0] ?? null;
  const maxLuck = Math.max(0, luckChar?.luck_remaining ?? 0);
  const effectiveLuck = Math.min(luckSpend, maxLuck);

  const blockedByNoCharacter =
    !isAdmin && requireCharacterToSpeak && !speakerChar;

  const lastMessage = visibleMessages.length > 0 ? visibleMessages[visibleMessages.length - 1] : null;
  const partyFloorOpen = Boolean(lastMessage && lastMessage.role === "user" && !streaming);

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

  const handleSubmit = async (e?: React.FormEvent, overrideGmMode?: "auto" | "force_gm" | "hold_gm") => {
    e?.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || !campaignId || busy || lockedByPeer || blockedByNoCharacter) return;

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
    onClearOverclock?.();
    setLuckSpend(0);
    stickToBottomRef.current = true;
    setShowJumpToLatest(false);
    const charDetail = (speakerChar?.detail ?? {}) as Record<string, unknown>;
    const speakerDisplay =
      typeof charDetail.handle === "string" && charDetail.handle.trim()
        ? charDetail.handle.trim()
        : speakerChar?.name;

    await onSend(trimmed, {
      overclock: useOverclock,
      luckSpend: useLuck,
      speakerCharacterId: speakerChar?.id,
      speakerName: speakerDisplay,
      gmMode: overrideGmMode ?? gmMode,
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
            className="pointer-events-none absolute inset-0 h-full w-full object-cover opacity-40"
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
              Create or select a campaign to jack into the Time of the Red.
            </p>
          </div>
        </div>
      </div>
    );
  }

  const speakerCharDetail = (speakerChar?.detail ?? {}) as Record<string, unknown>;
  const rawSpeakerColor = typeof speakerCharDetail.color === "string" ? speakerCharDetail.color.trim() : "";
  const activeSpeakerColor =
    rawSpeakerColor && (CHARACTER_COLOR_THEMES[rawSpeakerColor] || isHexColor(rawSpeakerColor))
      ? rawSpeakerColor
      : "cyan";

  const visibleSplitChannels = (() => {
    if (!partyGrouping || partyGrouping.mode !== "split") return [];
    const myCharId = speakerChar?.id || selectedSpeakerId || "";
    const myChan = myCharId ? partyGrouping.char_channel_map?.[myCharId] : undefined;
    if (isAdmin) return partyGrouping.channels;
    return partyGrouping.channels.filter((ch) => ch.id === myChan || ch.id === activeChannelId);
  })();

  const currentGmMode = GM_MODES.find((m) => m.id === gmMode) ?? GM_MODES[0];
  const cycleGmMode = () => {
    const idx = GM_MODES.findIndex((m) => m.id === gmMode);
    const next = GM_MODES[(idx + 1) % GM_MODES.length];
    setGmMode(next.id);
  };

  return (
    <div className="relative flex h-full min-h-0 min-w-0 w-full flex-col bg-[#080b12]/80">
      {/* Split-Scene Channel Bar (only shown when party is split into separate scene channels) */}
      {partyGrouping?.mode === "split" && visibleSplitChannels.length > 0 && onChangeChannelId && (
        <div className="flex flex-wrap items-center gap-1.5 border-b border-amber-500/25 bg-[#0e1422]/95 px-4 py-1.5 text-[11px]">
          <span className="font-mono text-[10px] uppercase tracking-wider text-amber-300">
            Scene Channels:
          </span>
          <button
            type="button"
            onClick={() => onChangeChannelId("main")}
            className={`rounded border px-2 py-0.5 font-mono text-[10px] transition ${
              activeChannelId === "main"
                ? "border-cyan-400 bg-cyan-500/20 font-bold text-cyan-100"
                : "border-slate-700 bg-slate-900 text-slate-400 hover:text-slate-200"
            }`}
          >
            Main Table
          </button>
          {visibleSplitChannels.map((ch) => (
            <button
              key={ch.id}
              type="button"
              onClick={() => onChangeChannelId(ch.id)}
              className={`rounded border px-2 py-0.5 font-mono text-[10px] transition ${
                activeChannelId === ch.id
                  ? "border-amber-400 bg-amber-500/20 font-bold text-amber-100"
                  : "border-slate-700 bg-slate-900 text-slate-300 hover:border-amber-500/50"
              }`}
            >
              {ch.location} ({ch.handles.join(", ")})
            </button>
          ))}
        </div>
      )}

      <div className="relative flex min-h-0 flex-1 flex-col">
        <div
          ref={scrollContainerRef}
          onScroll={handleScroll}
          data-testid="chat-scroll-container"
          className="flex-1 overflow-y-auto px-2.5 py-3 sm:px-4 sm:py-5"
        >
          <div className="mx-auto max-w-3xl space-y-3 sm:space-y-5">
            {visibleMessages.length === 0 && !streaming && (
              <div className="rounded-lg border border-slate-800/80 bg-[#0b101b]/75 px-4 py-6 text-center text-xs text-slate-400">
                No messages yet. Check the <strong className="text-slate-200">Campaign</strong> tab for story &amp; rules, or describe your opening move below.
              </div>
            )}

            {visibleMessages.map((msg, msgIdx) => {
              if (msg.role === "system") {
                const isSession = Boolean(msg.metadata?.session_started);
                return (
                  <div key={msg.id} className="my-2 flex items-center gap-3 px-2">
                    <div className="h-px flex-1 bg-slate-800/80" />
                    <span
                      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 font-mono text-[10px] font-semibold uppercase tracking-wider ${
                        isSession
                          ? "border-amber-500/40 bg-amber-500/10 text-amber-200"
                          : "border-cyan-500/35 bg-cyan-950/30 text-cyan-200"
                      }`}
                    >
                      <Sparkles className="h-3 w-3" />
                      {msg.content}
                    </span>
                    <div className="h-px flex-1 bg-slate-800/80" />
                  </div>
                );
              }
              const isUser = msg.role === "user";
              const isEditing = editingId === msg.id;
              const isConfirmingDelete = confirmDeleteId === msg.id;
              const isDeletingThis = deletingId === msg.id;
              const hasMessagesBelow = msgIdx < visibleMessages.length - 1;
              const hasUserParent =
                !isUser &&
                Boolean(msg.parent_id) &&
                visibleMessages.some((m) => m.id === msg.parent_id && m.role === "user");
              const isGuiding = guidanceMsgId === msg.id;

              // Resolve character object for speaker styling, Handle vs Real Name, portrait, and color
              const matchedChar = isUser
                ? characters.find(
                    (c) =>
                      c.id === msg.metadata?.speaker_character_id ||
                      (msg.metadata?.speaker_name &&
                        c.name.toLowerCase() === msg.metadata.speaker_name.toLowerCase()),
                  ) ?? null
                : null;
              const charDetail = (matchedChar?.detail ?? {}) as Record<string, unknown>;
              const speakerHandle = isUser
                ? (typeof charDetail.handle === "string" && charDetail.handle.trim()) ||
                  msg.metadata?.speaker_name ||
                  matchedChar?.name ||
                  "You"
                : "GM";
              const realName =
                typeof charDetail.real_name === "string" && charDetail.real_name.trim()
                  ? charDetail.real_name.trim()
                  : null;
              const realNameHidden = Boolean(
                charDetail.real_name_hidden ?? (realName && speakerHandle !== realName),
              );
              const charRoles = Array.isArray(charDetail.roles)
                ? (charDetail.roles as Array<{ role?: string; rank?: number }>)
                : [];
              const primaryRole = charRoles[0]?.role;

              const colorId = isUser
                ? msg.metadata?.speaker_color ||
                  (typeof charDetail.color === "string" ? charDetail.color : "") ||
                  "cyan"
                : "rose";
              const speakerTheme = resolveCharacterColor(colorId);
              const portraitUrl = isUser
                ? msg.metadata?.speaker_portrait_url ||
                  (typeof charDetail.portrait_url === "string" ? charDetail.portrait_url : "")
                : "";

              // Gather inline action rolls for this user message:
              // Either stored directly on msg.metadata.rolls, or on the immediate child assistant message
              const nextMsg = msgIdx + 1 < visibleMessages.length ? visibleMessages[msgIdx + 1] : null;
              const actionRolls: DiceRollResult[] = isUser
                ? (msg.metadata?.rolls && msg.metadata.rolls.length > 0
                    ? msg.metadata.rolls
                    : nextMsg && nextMsg.role === "assistant" && nextMsg.parent_id === msg.id
                      ? nextMsg.metadata?.rolls ?? []
                      : [])
                : [];

              // On assistant messages, only show rolls that weren't already displayed on the parent user message
              const parentInView =
                !isUser && msg.parent_id
                  ? visibleMessages.find((m) => m.id === msg.parent_id && m.role === "user")
                  : null;
              const assistantRolls = !isUser && !parentInView ? msg.metadata?.rolls ?? [] : [];

              const patches = msg.metadata?.patches ?? [];
              const citations = msg.metadata?.citation_cards ?? [];
              const warnings = msg.metadata?.warnings ?? [];
              const gmOpsCount = citations.length + patches.length + warnings.length;
              const gmOpsOpen = Boolean(gmOpsOpenIds[msg.id]);

              return (
                <div
                  key={msg.id}
                  className={`group flex flex-col ${isUser ? "items-end" : "items-start"}`}
                >
                  <div
                    className={`rounded-xl px-3 py-2.5 transition sm:px-4 sm:py-3 ${
                      isUser
                        ? `max-w-[92%] sm:max-w-[90%] border ${speakerTheme.cardBorderClass} text-slate-100`
                        : "w-full border border-slate-800/90 bg-[#0e1422] text-slate-100"
                    }`}
                    style={isUser ? speakerTheme.cardBorderStyle : undefined}
                  >
                    {/* Message Header */}
                    <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-400">
                      <div className="flex flex-wrap items-center gap-2">
                        {isUser ? (
                          <div className="inline-flex items-center gap-2">
                            {portraitUrl ? (
                              <img
                                src={portraitUrl}
                                alt={speakerHandle}
                                className={`h-6 w-6 rounded-full object-cover ring-2 ${speakerTheme.avatarRingClass}`}
                                style={speakerTheme.avatarRingStyle}
                              />
                            ) : (
                              <span
                                className={`inline-flex h-5 w-5 items-center justify-center rounded-full border ${speakerTheme.nameBadgeClass}`}
                                style={speakerTheme.nameBadgeStyle}
                              >
                                <User className="h-3 w-3" />
                              </span>
                            )}
                            <span
                              className={`inline-flex items-center gap-1.5 rounded border px-2 py-0.5 font-cyber-hud text-xs font-bold tracking-wider uppercase ${speakerTheme.nameBadgeClass}`}
                              style={speakerTheme.nameBadgeStyle}
                            >
                              <span className={`h-1.5 w-1.5 rounded-full ${speakerTheme.dotClass}`} style={speakerTheme.dotStyle} />
                              {speakerHandle}
                            </span>
                            {primaryRole && (
                              <span className="rounded border border-slate-700 bg-slate-900/90 px-1.5 py-0.5 font-mono text-[10px] text-slate-300">
                                {primaryRole}
                              </span>
                            )}
                            {realName && !realNameHidden && realName !== speakerHandle && (
                              <span className="text-[10px] text-slate-400">({realName})</span>
                            )}
                            {realName && realNameHidden && isAdmin && (
                              <span
                                title={`Real name '${realName}' is hidden from public/NPCs`}
                                className="inline-flex items-center gap-0.5 rounded border border-slate-700/80 bg-slate-900/80 px-1.5 py-0.5 font-mono text-[9px] text-slate-400"
                              >
                                <EyeOff className="h-2.5 w-2.5" /> Alias Only
                              </span>
                            )}
                          </div>
                        ) : (
                          <span className="inline-flex items-center gap-1.5 rounded border border-rose-500/45 bg-rose-500/15 px-2 py-0.5 font-cyber-display text-[10px] font-bold uppercase tracking-widest text-rose-200">
                            <span className="h-1.5 w-1.5 rounded-full bg-rose-400" />
                            GAME MASTER
                          </span>
                        )}

                        {!isUser && isAdmin && msg.model && (
                          <span className="rounded bg-slate-800/80 px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
                            {msg.model}
                          </span>
                        )}
                        {!isUser && isAdmin && msg.metadata?.generation_stats && (
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

                      {/* QoL Action Controls + Admin-Only GM Ops Submenu Toggle */}
                      <div className="flex flex-wrap items-center gap-1">
                        {!isUser && isAdmin && gmOpsCount > 0 && (
                          <button
                            type="button"
                            onClick={() =>
                              setGmOpsOpenIds((prev) => ({ ...prev, [msg.id]: !prev[msg.id] }))
                            }
                            title="Admin-only submenu: rulebook entries read, campaign state updates & engine logs"
                            className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 font-mono text-[10px] transition ${
                              gmOpsOpen
                                ? "border-cyan-400/60 bg-cyan-500/20 text-cyan-200"
                                : "border-slate-700/80 bg-slate-900/90 text-slate-400 hover:border-slate-600 hover:text-slate-200"
                            }`}
                          >
                            <Layers className="h-3 w-3 text-cyan-400" />
                            <span>GM Ops ({gmOpsCount})</span>
                            {gmOpsOpen ? (
                              <ChevronUp className="h-3 w-3" />
                            ) : (
                              <ChevronDown className="h-3 w-3" />
                            )}
                          </button>
                        )}

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

                        {!isEditing && (isAdmin || isUser) && (
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
                            {isAdmin && (
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
                            )}
                          </>
                        )}

                        {(isAdmin || isUser) && (
                          <>
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
                          </>
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
                      <div className="space-y-2.5">
                        <FormattedUserText content={msg.content} />
                        {/* Inline Dice Rolls right next to the player action that rolled them */}
                        {actionRolls.length > 0 && (
                          <div className="space-y-1.5 border-t border-slate-800/70 pt-2">
                            {actionRolls.map((r, i) => (
                              <RollCard key={i} roll={r} compact />
                            ))}
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="space-y-3">
                        {/* Collapsible Admin-Only GM Ops Submenu (Citations, Campaign Patches, System Warnings) */}
                        {isAdmin && gmOpsOpen && gmOpsCount > 0 && (
                          <div className="space-y-2.5 rounded-lg border border-slate-700/80 bg-slate-950/90 p-3 text-xs">
                            <div className="flex items-center justify-between border-b border-slate-800 pb-1.5 font-mono text-[10px] uppercase tracking-wider text-cyan-300">
                              <span className="inline-flex items-center gap-1.5">
                                <Shield className="h-3 w-3 text-rose-400" />
                                Admin Engine Log (Hidden from Players)
                              </span>
                              <span>{gmOpsCount} item(s)</span>
                            </div>

                            {citations.length > 0 && (
                              <div className="space-y-1">
                                <div className="font-mono text-[10px] text-slate-400">
                                  Rulebook &amp; Library Entries Read:
                                </div>
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
                              </div>
                            )}

                            {patches.length > 0 && (
                              <div className="space-y-1">
                                <div className="font-mono text-[10px] text-slate-400">
                                  Campaign &amp; Sheet State Updates:
                                </div>
                                <div className="flex flex-wrap gap-1.5">
                                  {patches.map((p, i) => (
                                    <PatchPill key={i} patch={p} />
                                  ))}
                                </div>
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

                        {assistantRolls.length > 0 && (
                          <div className="space-y-1.5">
                            {assistantRolls.map((r, i) => (
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

            {streaming && (() => {
              const streamTheme = resolveCharacterColor(streaming.speakerColor || activeSpeakerColor);
              return (
              <div className="space-y-3">
                {streaming.userText && !isPeerStreaming && (
                  <div className="flex justify-end">
                    <div
                      className={`max-w-[90%] rounded-xl border px-4 py-3 text-slate-100 ${streamTheme.cardBorderClass}`}
                      style={streamTheme.cardBorderStyle}
                    >
                      <div className="mb-1.5 flex items-center gap-2 text-[11px] text-slate-400">
                        <span
                          className={`inline-flex items-center gap-1.5 rounded border px-2 py-0.5 font-cyber-hud text-xs font-bold uppercase ${streamTheme.nameBadgeClass}`}
                          style={streamTheme.nameBadgeStyle}
                        >
                          {streaming.speakerName || "You"}
                        </span>
                        {streaming.overclock && (
                          <span className="inline-flex items-center gap-1 rounded bg-rose-500/20 px-1.5 py-0.5 font-mono text-[10px] text-rose-300">
                            <Zap className="h-3 w-3" /> OVERCLOCK
                          </span>
                        )}
                      </div>
                      <p className="whitespace-pre-wrap text-sm leading-relaxed">{streaming.userText}</p>
                      {streaming.rolls.length > 0 && (
                        <div className="mt-2 space-y-1.5 border-t border-slate-800/70 pt-2">
                          {streaming.rolls.map((r, i) => (
                            <RollCard key={i} roll={r} compact />
                          ))}
                        </div>
                      )}
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
                    {isAdmin && streaming.startedAt && (
                      <span className="font-mono text-[10px] text-cyan-300">
                        {streamElapsedSec.toFixed(1)}s
                      </span>
                    )}
                  </div>

                  <div className="space-y-3">
                    {!streaming.userText &&
                      streaming.rolls.map((r, i) => <RollCard key={i} roll={r} />)}

                    {isAdmin &&
                      streaming.libraryAdded.map((entry) => (
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
                          Checking rules &amp; resolving actions...
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </div>
              );
            })()}

            <div ref={bottomRef} />
          </div>
        </div>

        {showJumpToLatest && (
          <div className="pointer-events-none absolute right-2.5 bottom-2.5 z-20 flex justify-end sm:inset-x-0 sm:bottom-3 sm:justify-center sm:px-4">
            <button
              type="button"
              onClick={() => scrollToBottom(true)}
              className="pointer-events-auto inline-flex items-center gap-1.5 rounded-full border border-cyan-500/50 bg-[#0d111a]/95 px-2.5 py-1 text-[11px] font-medium text-cyan-200 shadow-lg backdrop-blur hover:border-cyan-400 hover:bg-slate-900 sm:px-3 sm:py-1.5 sm:text-xs"
            >
              <ArrowDown className="h-3.5 w-3.5" />
              Jump to latest
            </button>
          </div>
        )}
      </div>

      {/* Composer Dock */}
      <form
        onSubmit={(e) => void handleSubmit(e)}
        className="shrink-0 border-t border-slate-800/90 bg-[#0b0f19]/95 px-2.5 py-2 backdrop-blur-md sm:px-4 sm:py-3"
      >
        <div className="mx-auto max-w-3xl space-y-1.5 sm:space-y-2">
          {lockedByPeer && (
            <div className="flex items-center gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-1.5 text-xs text-amber-300">
              <Lock className="h-3.5 w-3.5 shrink-0" />
              <span>GM is resolving {activeTurn?.player_name}&apos;s turn...</span>
            </div>
          )}

          {/* Party Floor Open / Deferred GM Resolution Bar */}
          {partyFloorOpen && lastMessage && !lockedByPeer && (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-cyan-500/40 bg-cyan-950/25 px-3 py-1.5 text-xs text-cyan-200">
              <div className="flex items-center gap-2">
                <Users className="h-3.5 w-3.5 shrink-0 text-cyan-400" />
                <span>
                  {lastMessage.metadata?.defer_reason ||
                    "Party floor open — teammates can reply or chain actions before the GM steps in."}
                </span>
              </div>
              <button
                type="button"
                disabled={busy}
                onClick={() => void onRegenerate(lastMessage)}
                className="inline-flex items-center gap-1.5 rounded bg-rose-600 px-3 py-1 font-cyber-hud text-xs font-bold tracking-wider text-white uppercase shadow hover:bg-rose-500 disabled:opacity-45"
              >
                <Play className="h-3 w-3 fill-current" />
                <span>Resolve GM Turn</span>
              </button>
            </div>
          )}

          {/* Characterless Speaking Lock Banner */}
          {blockedByNoCharacter && (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-rose-500/45 bg-rose-950/25 px-2.5 py-1.5 text-[11px] text-rose-200 sm:px-3 sm:py-2 sm:text-xs">
              <div className="flex min-w-0 flex-1 items-center gap-1.5 sm:gap-2">
                <Lock className="h-3.5 w-3.5 shrink-0 text-rose-400" />
                <span>
                  Admin requires an active Edgerunner sheet to speak in chat. Create or claim your character first.
                </span>
              </div>
              {onOpenCreateCharacter && (
                <button
                  type="button"
                  onClick={onOpenCreateCharacter}
                  className="inline-flex shrink-0 items-center gap-1 rounded bg-cyan-600 px-2.5 py-1 font-semibold text-white hover:bg-cyan-500"
                >
                  <UserPlus className="h-3.5 w-3.5" />
                  <span>Create Character</span>
                </button>
              )}
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
                <span className="font-mono text-[11px] text-slate-400">Text Highlight:</span>
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
              {speakerChar && onUpdateCharacterColor && (
                <div className="flex flex-wrap items-center gap-1.5 border-l border-slate-800 pl-2">
                  <span className="font-mono text-[10px] text-slate-400">Name Tag Color:</span>
                  {Object.entries(CHARACTER_COLOR_THEMES).map(([cid, theme]) => (
                    <button
                      key={cid}
                      type="button"
                      title={`Set ${speakerChar.name}'s name tag color to ${theme.label}`}
                      onClick={() => void onUpdateCharacterColor(speakerChar.id, cid)}
                      className={`h-4 w-4 rounded-full border transition ${theme.dotClass} ${
                        activeSpeakerColor === cid ? "scale-110 ring-2 ring-white" : "opacity-65 hover:opacity-100"
                      }`}
                    />
                  ))}
                  <label
                    className="ml-1 inline-flex cursor-pointer items-center gap-1 rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 font-mono text-[10px] text-slate-200 hover:border-cyan-400"
                    title="Pick any custom Name Tag Color from the color wheel"
                  >
                    <input
                      type="color"
                      aria-label="Custom name tag color wheel"
                      value={normalizeColorHex(colorPreview || activeSpeakerColor)}
                      onChange={(e) => {
                        const nextHex = e.target.value;
                        const targetCharId = speakerChar.id;
                        setColorPreview(nextHex);
                        if (colorDebounceRef.current) clearTimeout(colorDebounceRef.current);
                        colorDebounceRef.current = setTimeout(() => {
                          colorDebounceRef.current = null;
                          void onUpdateCharacterColor(targetCharId, nextHex);
                        }, 140);
                      }}
                      className="h-3.5 w-4 cursor-pointer border-0 bg-transparent p-0"
                    />
                    <span>
                      {isHexColor(colorPreview || activeSpeakerColor)
                        ? (colorPreview || activeSpeakerColor).toUpperCase()
                        : "Wheel"}
                    </span>
                  </label>
                </div>
              )}
            </div>
          )}

          <div className="grid grid-cols-[1fr_auto] items-center gap-x-2 gap-y-1.5 sm:grid-cols-[1fr_auto_auto] sm:gap-y-2">
            <div className="col-start-1 row-start-1 flex min-w-0 flex-wrap items-center gap-1 sm:gap-1.5">
              {luckChar && (
                <div
                  title={`Commit LUCK before the roll (only spent if a check runs this turn; ${maxLuck} available)`}
                  className={`inline-flex items-center gap-0.5 rounded-md border px-1.5 py-0.5 text-[11px] ${
                    effectiveLuck > 0
                      ? "border-amber-500/70 bg-amber-500/15 text-amber-200"
                      : "border-slate-700 bg-slate-900 text-slate-400"
                  }`}
                >
                  <Sparkles className="h-3 w-3 text-amber-400" />
                  <button
                    type="button"
                    aria-label="Decrease Luck spend"
                    disabled={effectiveLuck <= 0}
                    onClick={() => setLuckSpend((v) => Math.max(0, v - 1))}
                    className="rounded p-0.5 hover:bg-slate-800 disabled:opacity-35"
                  >
                    <Minus className="h-2.5 w-2.5" />
                  </button>
                  <span className="min-w-[1.8rem] text-center font-mono text-[11px] font-semibold">
                    +{effectiveLuck}/{maxLuck}
                  </span>
                  <button
                    type="button"
                    aria-label="Increase Luck spend"
                    disabled={effectiveLuck >= maxLuck}
                    onClick={() => setLuckSpend((v) => Math.min(maxLuck, v + 1))}
                    className="rounded p-0.5 hover:bg-slate-800 disabled:opacity-35"
                  >
                    <Plus className="h-2.5 w-2.5" />
                  </button>
                </div>
              )}

              <button
                type="button"
                onClick={() => setDiceOpen((v) => !v)}
                className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-1 text-[11px] transition sm:px-2 sm:text-xs ${
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
                title="Highlight text or pick your character's Name Tag Color"
                className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-1 text-[11px] transition sm:px-2 sm:text-xs ${
                  colorBarOpen
                    ? "border-cyan-500/60 bg-cyan-500/15 text-cyan-200"
                    : "border-slate-700 bg-slate-900 text-slate-400 hover:text-slate-200"
                }`}
              >
                <Palette className="h-3.5 w-3.5" />
                Color
              </button>

              {overclock && (
                <span
                  title="Overclock armed in Character tab (-2 Humanity / +2 Check on next roll)"
                  className="inline-flex items-center gap-1 rounded-md border border-rose-500/60 bg-rose-500/15 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-rose-200"
                >
                  <Zap className="h-3 w-3 text-cyan-300" />
                  OVERCLOCK
                </span>
              )}
            </div>

            <span className="hidden text-[11px] text-slate-500 sm:col-span-2 sm:col-start-2 sm:row-start-1 sm:inline sm:justify-self-end">
              Enter to send · Shift+Enter for new line · <code className="text-slate-400">/roll 3d6</code>
            </span>

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
              placeholder={
                blockedByNoCharacter
                  ? "Create or claim your character to speak in chat..."
                  : gmMode === "hold_gm"
                    ? "Talk to the party or queue your action (GM will wait)..."
                    : "Describe your action..."
              }
              rows={2}
              disabled={busy || lockedByPeer || blockedByNoCharacter}
              className="col-start-1 row-start-2 min-h-[40px] w-full min-w-0 resize-none rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-sm text-slate-100 placeholder:text-slate-500 focus:border-cyan-400 focus:outline-none disabled:opacity-60 max-sm:h-10 sm:px-3 sm:py-2"
            />

            <button
              type="button"
              onClick={cycleGmMode}
              aria-label={`GM turn mode: ${currentGmMode.label}`}
              title={currentGmMode.tip}
              className={`col-start-2 row-start-1 inline-flex h-7 shrink-0 items-center justify-self-end rounded-md border px-2 text-[11px] font-semibold transition sm:col-start-2 sm:row-start-2 sm:h-10 sm:self-end sm:rounded-lg sm:px-2.5 ${currentGmMode.cls}`}
            >
              {currentGmMode.label}
            </button>

            {busy ? (
              <button
                type="button"
                onClick={onStopStream}
                className="col-start-2 row-start-2 inline-flex h-10 shrink-0 items-center gap-1.5 self-end rounded-lg bg-rose-600 px-3 text-xs font-semibold text-white hover:bg-rose-500 sm:col-start-3 sm:px-4"
              >
                <Square className="h-3.5 w-3.5 fill-current" />
                Stop
              </button>
            ) : (
              <button
                type="submit"
                disabled={!input.trim() || lockedByPeer || blockedByNoCharacter}
                className={`col-start-2 row-start-2 inline-flex h-10 shrink-0 items-center gap-1.5 self-end rounded-lg px-3 text-xs font-semibold text-white disabled:opacity-40 sm:col-start-3 sm:px-4 ${
                  gmMode === "hold_gm"
                    ? "bg-amber-600 hover:bg-amber-500"
                    : "bg-cyan-600 hover:bg-cyan-500"
                }`}
              >
                <Send className="h-3.5 w-3.5" />
                {gmMode === "hold_gm" ? "Post" : "Send"}
              </button>
            )}
          </div>
        </div>
      </form>
    </div>
  );
}
