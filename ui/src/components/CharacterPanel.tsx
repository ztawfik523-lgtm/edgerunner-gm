import { useEffect, useState } from "react";
import edgerunnerChromeBanner from "../assets/edgerunner-chrome-banner.jpg";
import {
  Activity,
  Backpack,
  BookOpen,
  ChevronDown,
  ChevronUp,
  Coins,
  Cpu,
  Dices,
  Heart,
  HelpCircle,
  History,
  Lock,
  Pencil,
  Plus,
  RotateCcw,
  Save,
  Search,
  ShieldAlert,
  Sparkles,
  Trash2,
  UserPlus,
} from "lucide-react";
import {
  fetchCharacterHistory,
  gameAction,
  runSkillCheck,
  undoCharacterChange,
  updateCharacterProfile,
  updateCharacterState,
} from "../api";
import { STAT_NAMES, type CharacterRecord, type CoopPlayer, type StatName } from "../types";
import { CharacterCreatorModal } from "./CharacterCreatorModal";

interface CharacterPanelProps {
  campaignId: string;
  campaignRevision: number;
  soloRevision?: number;
  characters: CharacterRecord[];
  corebookSkills: Record<string, { stat: string; cost: number; specializable: boolean }>;
  roster?: CoopPlayer[];
  selfClientId?: string;
  protectOthers?: boolean;
  preferredSelectedId?: string;
  onOpenCreateCharacter?: () => void;
  onRefresh: () => Promise<void>;
  onNotify: (msg: string) => void;
}

type SheetTab = "skills" | "gear" | "bio" | "log";

const STAT_QUICK_GUIDE: Record<StatName, { full: string; desc: string }> = {
  INT: {
    full: "Intelligence",
    desc: "Awareness, deduction, street & academic knowledge (Perception, Cryptography, Education).",
  },
  REF: {
    full: "Reflexes",
    desc: "Aim, reaction speed, Initiative, and ranged combat (Handgun, Shoulder Arms, Driving).",
  },
  DEX: {
    full: "Dexterity",
    desc: "Agility, dodging, stealth, and close-quarters control (Evasion, Brawling, Martial Arts).",
  },
  TECH: {
    full: "Technique",
    desc: "Hardware tinkering, medical stabilization, lockpicking, and cybertech.",
  },
  COOL: {
    full: "Cool",
    desc: "Composure, style, intimidation, and street negotiation (Bribery, Persuasion, Streetwise).",
  },
  WILL: {
    full: "Willpower",
    desc: "Mental grit, Pain Resistance, and contributes directly to Max HP.",
  },
  LUCK: {
    full: "Luck",
    desc: "Spend LUCK points before a roll (+1 per point spent) to swing critical checks; refreshes between sessions.",
  },
  MOVE: {
    full: "Movement",
    desc: "Run/sprint speed (MOVE × 2m per Move Action) and athletic chase pacing.",
  },
  BODY: {
    full: "Body",
    desc: "Physical build, Death Saves, Brawling damage, and contributes directly to Max HP.",
  },
  EMP: {
    full: "Empathy",
    desc: "Reading people and cyberware tolerance. Max Humanity = EMP × 10 (each -10 Humanity lowers current EMP by 1).",
  },
};

export function CharacterPanel({
  campaignId,
  campaignRevision,
  soloRevision = 0,
  characters,
  corebookSkills,
  roster = [],
  selfClientId = "",
  protectOthers = false,
  preferredSelectedId = "",
  onOpenCreateCharacter,
  onRefresh,
  onNotify,
}: CharacterPanelProps) {
  const [selectedId, setSelectedId] = useState<string>("");
  const [creating, setCreating] = useState(false);
  const [sheetTab, setSheetTab] = useState<SheetTab>("skills");
  const [inspectedStat, setInspectedStat] = useState<StatName | null>(null);
  const [inspectedSkill, setInspectedSkill] = useState<string | null>(null);

  // Skill check drawer state
  const [skillFilter, setSkillFilter] = useState("");
  const [checkStat, setCheckStat] = useState<StatName>("REF");
  const [checkSkill, setCheckSkill] = useState("Handgun");
  const [checkDv, setCheckDv] = useState(13);
  const [checkMod, setCheckMod] = useState(0);
  const [checkLuck, setCheckLuck] = useState(0);
  const [checkReason, setCheckReason] = useState("Manual check");
  const [showRollExtras, setShowRollExtras] = useState(false);
  const [lastRoll, setLastRoll] = useState<{
    total: number;
    success: boolean;
    die: number;
    explosion: number;
    wound_modifier: number;
  } | null>(null);

  // Inventory & History
  const [itemName, setItemName] = useState("");
  const [itemCount, setItemCount] = useState(1);
  const [confirmRemoveItem, setConfirmRemoveItem] = useState<string | null>(null);
  const [historyRows, setHistoryRows] = useState<
    Array<{ sequence: number; revision: number; reason: string }>
  >([]);

  // Bio / History editor
  const [editingBio, setEditingBio] = useState(false);
  const [bioConcept, setBioConcept] = useState("");
  const [bioSummary, setBioSummary] = useState("");
  const [bioHistory, setBioHistory] = useState("");
  const [bioAppearance, setBioAppearance] = useState("");

  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (preferredSelectedId && characters.some((c) => c.id === preferredSelectedId)) {
      setSelectedId(preferredSelectedId);
      setSheetTab("skills");
    }
  }, [preferredSelectedId, characters]);

  useEffect(() => {
    if (characters.length === 0) {
      setSelectedId("");
      return;
    }
    if (!characters.some((c) => c.id === selectedId)) {
      setSelectedId(characters[0].id);
    }
  }, [characters, selectedId]);

  useEffect(() => {
    setConfirmRemoveItem(null);
    setLastRoll(null);
    setEditingBio(false);
  }, [selectedId, campaignId]);

  const active =
    characters.find((c) => c.id === selectedId) ??
    (preferredSelectedId ? characters.find((c) => c.id === preferredSelectedId) : undefined) ??
    characters[0] ??
    null;

  useEffect(() => {
    if (sheetTab !== "log" || !active) return;
    let cancelled = false;
    fetchCharacterHistory(campaignId, active.id)
      .then((rows) => {
        if (!cancelled) setHistoryRows(rows.slice(-16).reverse());
      })
      .catch(() => {
        if (!cancelled) setHistoryRows([]);
      });
    return () => {
      cancelled = true;
    };
  }, [sheetTab, campaignId, active?.id, active?.revision]);

  const handleHpDelta = async (delta: number) => {
    if (!active || busy) return;
    const nextHp = Math.min(active.max_hp, active.hp + delta);
    setBusy(true);
    try {
      await updateCharacterState(
        campaignId,
        active.id,
        active.revision,
        { hp: nextHp },
        delta < 0 ? `Damage ${delta} HP` : `Heal +${delta} HP`,
      );
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "HP update failed");
    } finally {
      setBusy(false);
    }
  };

  const handleMoneyDelta = async (delta: number) => {
    if (!active || busy) return;
    const nextMoney = Math.max(0, active.money + delta);
    setBusy(true);
    try {
      await updateCharacterState(
        campaignId,
        active.id,
        active.revision,
        { money: nextMoney },
        delta >= 0 ? `Gain ${delta} eb` : `Spend ${Math.abs(delta)} eb`,
      );
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Money update failed");
    } finally {
      setBusy(false);
    }
  };

  const handleAddInventory = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!active || !itemName.trim() || busy) return;
    const nextInv = {
      ...active.inventory,
      [itemName.trim()]: Math.max(1, (active.inventory[itemName.trim()] ?? 0) + itemCount),
    };
    setBusy(true);
    try {
      await updateCharacterState(
        campaignId,
        active.id,
        active.revision,
        { inventory: nextInv },
        `Add ${itemName.trim()}`,
      );
      setItemName("");
      setItemCount(1);
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Inventory update failed");
    } finally {
      setBusy(false);
    }
  };

  const handleRemoveItem = async (name: string) => {
    if (!active || busy) return;
    const nextInv = { ...active.inventory };
    delete nextInv[name];
    setBusy(true);
    try {
      await updateCharacterState(
        campaignId,
        active.id,
        active.revision,
        { inventory: nextInv },
        `Remove ${name}`,
      );
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Inventory remove failed");
    } finally {
      setBusy(false);
    }
  };

  const handleRollCheck = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!active || busy) return;
    setBusy(true);
    try {
      const res = await runSkillCheck(campaignId, {
        character_id: active.id,
        expected_revision: active.revision,
        stat: checkStat,
        skill: checkSkill.trim() ? checkSkill.trim() : null,
        dv: checkDv,
        modifier: checkMod,
        luck: checkLuck,
        reason: checkReason.trim() || "Manual check",
      });
      setLastRoll(res);
      setCheckLuck(0);
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Check failed");
    } finally {
      setBusy(false);
    }
  };

  const handleUndo = async () => {
    if (!active || busy) return;
    setBusy(true);
    try {
      await undoCharacterChange(campaignId, active.id, active.revision);
      await onRefresh();
      onNotify(`Undid latest change for ${active.name}.`);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Nothing to undo");
    } finally {
      setBusy(false);
    }
  };

  const ROLES_DIFFICULT_SKILLS = new Set([
    "Autofire",
    "Demolitions",
    "Electronics/Security Tech",
    "Heavy Weapons",
    "Martial Arts",
    "Paramedic",
    "Pilot Air Vehicle",
  ]);
  const isDifficultSkill = (name: string) =>
    ROLES_DIFFICULT_SKILLS.has(name) ||
    ROLES_DIFFICULT_SKILLS.has(name.split(" (", 1)[0].trim());

  const handleSpendIpSkill = async (skillName: string, currentRank: number) => {
    if (!active || busy) return;
    const kind = isDifficultSkill(skillName) ? "difficult" : "typical";
    setBusy(true);
    try {
      const res = await gameAction<{ skill?: string; rank?: number; cost?: number; ip?: number }>(
        "role_action",
        {
          character_id: active.id,
          action: "spend_ip_skill",
          arguments: { skill: skillName, current_rank: currentRank, kind },
        },
        campaignId,
      );
      await onRefresh();
      onNotify(`Upgraded ${res.skill ?? skillName} to +${res.rank ?? currentRank + 1} (${res.cost ?? ""} IP spent).`);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "IP upgrade failed");
    } finally {
      setBusy(false);
    }
  };

  const handleTherapy = async (tier: "standard" | "extreme") => {
    if (!active || busy) return;
    const cost = tier === "extreme" ? 1000 : 500;
    const diceCount = tier === "extreme" ? 4 : 2;
    if (active.money < cost) {
      onNotify(`Insufficient eddies: ${tier === "extreme" ? "Extreme" : "Standard"} Therapy costs ${cost} eb (p. 230).`);
      return;
    }
    const maxHum = maxHumanity;
    if (active.humanity >= maxHum) {
      onNotify("Humanity is already at maximum.");
      return;
    }
    const rolled = Array.from({ length: diceCount }, () => Math.floor(Math.random() * 6) + 1).reduce((a, b) => a + b, 0);
    const nextHum = Math.min(maxHum, active.humanity + rolled);
    setBusy(true);
    try {
      await updateCharacterState(
        campaignId,
        active.id,
        active.revision,
        { humanity: nextHum, money: active.money - cost },
        `${tier === "extreme" ? "Extreme" : "Standard"} Therapy (-${cost}eb, +${nextHum - active.humanity} Humanity, p. 230)`,
      );
      await onRefresh();
      onNotify(`Completed ${tier} Therapy (+${nextHum - active.humanity} Humanity, -${cost} eb).`);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Therapy failed");
    } finally {
      setBusy(false);
    }
  };

  const handleSaveBio = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!active || busy) return;
    const prevDetail = (active.detail ?? {}) as Record<string, unknown>;
    const prevBackstory =
      prevDetail.backstory && typeof prevDetail.backstory === "object"
        ? (prevDetail.backstory as Record<string, unknown>)
        : {};
    const nextBackstory = {
      ...prevBackstory,
      concept: bioConcept.trim(),
      summary: bioSummary.trim(),
      established_history: bioHistory.trim(),
      appearance: bioAppearance.trim(),
    };
    setBusy(true);
    try {
      await updateCharacterProfile(
        campaignId,
        active.id,
        active.revision,
        {
          backstory: nextBackstory,
          appearance: bioAppearance.trim(),
        },
        "Updated character bio & established history",
      );
      setEditingBio(false);
      await onRefresh();
      onNotify(`Saved bio & history for ${active.name}.`);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Bio update failed");
    } finally {
      setBusy(false);
    }
  };

  const openCreator = () => {
    if (onOpenCreateCharacter) {
      onOpenCreateCharacter();
    } else {
      setCreating(true);
    }
  };

  const creatorModal = !onOpenCreateCharacter ? (
    <CharacterCreatorModal
      open={creating}
      campaignId={campaignId}
      campaignRevision={campaignRevision}
      soloRevision={soloRevision}
      onClose={() => setCreating(false)}
      onCreated={async (id, charName) => {
        setSelectedId(id);
        setCreating(false);
        setSheetTab("skills");
        await onRefresh();
        onNotify(`Created ${charName} and attached to campaign.`);
      }}
      onNotify={onNotify}
    />
  ) : null;

  if (characters.length === 0) {
    return (
      <div className="space-y-4 p-4">
        {creatorModal}
        <div className="cyber-hud-card overflow-hidden rounded-xl bg-[#101624]">
          <div className="relative h-28 w-full overflow-hidden border-b border-rose-500/30">
            <img
              src={edgerunnerChromeBanner}
              alt=""
              aria-hidden="true"
              className="h-full w-full object-cover opacity-75"
            />
            <div className="absolute inset-0 bg-gradient-to-t from-[#101624] via-[#101624]/45 to-transparent" />
            <div className="absolute bottom-2.5 left-4 right-4 flex items-center justify-between">
              <h3 className="font-cyber-display text-sm font-bold uppercase tracking-wider text-slate-100">
                Create Edgerunner Sheet
              </h3>
              <UserPlus className="h-5 w-5 shrink-0 text-cyan-400" />
            </div>
          </div>

          <div className="p-4 space-y-3">
            <p className="text-xs leading-relaxed text-slate-300">
              Build a full Cyberpunk RED character sheet with Corebook Roles, hover/click rulebook
              explanations, official STAT &amp; Skill templates or custom builds, Lifepath history,
              written backstory, and starting gear.
            </p>

            <div className="grid grid-cols-2 gap-2 text-[11px] text-slate-300">
              <div className="rounded border border-slate-800 bg-slate-950/70 p-2">
                <div className="font-semibold text-cyan-300">4 Creation Modes</div>
                <div className="mt-0.5 text-slate-400">
                  Streetrat, Edgerunner, Complete Package (62 STATs / 86 Skills / 2,550 eb), or Freeform.
                </div>
              </div>
              <div className="rounded border border-slate-800 bg-slate-950/70 p-2">
                <div className="font-semibold text-rose-300">Lifepath &amp; Ties</div>
                <div className="mt-0.5 text-slate-400">
                  Roll or write Culture, Origins, Friends, Enemies, Role Lifepath, and Night City history.
                </div>
              </div>
            </div>

            <button
              type="button"
              onClick={openCreator}
              className="cyber-cut-sm inline-flex w-full items-center justify-center gap-2 bg-gradient-to-r from-rose-600 to-rose-500 px-4 py-2.5 font-cyber-hud text-xs font-bold tracking-wider text-white uppercase shadow-[0_0_16px_rgba(244,63,94,0.28)] transition hover:from-rose-500 hover:to-rose-400"
            >
              <UserPlus className="h-4 w-4" />
              Open Character Sheet Creator
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (!active) return null;

  const detail = (active.detail ?? {}) as Record<string, unknown>;
  const cyberwareList = Array.isArray(detail.cyberware) ? detail.cyberware : [];
  const cyberMaxHumPenalty = cyberwareList.reduce((acc, cw) => {
    const item = cw as { hl?: number; name?: string; slot?: string };
    const hl = typeof item.hl === "number" ? item.hl : 0;
    if (hl <= 0) return acc;
    const isBorg = /linear frame|multioptic|shoulder mount|borgware/i.test(String(item.name ?? "") + " " + String(item.slot ?? ""));
    return acc + (isBorg ? 4 : 2);
  }, 0);
  const maxHumanity = Math.max(0, active.stats.EMP * 10 - cyberMaxHumPenalty);

  const threshold = Math.ceil(active.max_hp / 2);
  const woundLabel =
    active.hp < 1
      ? "Mortally Wounded (-4)"
      : active.hp < threshold
        ? "Seriously Wounded (-2)"
        : "Operational";
  const hpPct = Math.max(0, Math.min(100, Math.round((active.hp / Math.max(1, active.max_hp)) * 100)));
  const humPct = Math.max(0, Math.min(100, Math.round((active.humanity / Math.max(1, maxHumanity)) * 100)));
  const claimant = roster.find((p) => p.character_id === active.id);
  const sheetLocked = Boolean(protectOthers && claimant && claimant.client_id !== selfClientId);

  const rolesList = Array.isArray(detail.roles)
    ? (detail.roles as Array<{
        role?: string;
        rank?: number;
        choices?: Record<string, unknown>;
        specialties?: Record<string, unknown>;
      }>)
    : [];
  const roleExtObj =
    detail.role_ext && typeof detail.role_ext === "object"
      ? (detail.role_ext as Record<string, unknown>)
      : {};
  const currentIp = typeof roleExtObj.ip === "number" ? roleExtObj.ip : 0;
  const fashionList = Array.isArray(detail.fashion)
    ? (detail.fashion as Array<string | { name?: string; style?: string }>)
    : [];
  const injuriesList = Array.isArray(detail.critical_injuries) ? detail.critical_injuries : [];
  const equippedWeapon = typeof detail.equipped_weapon === "string" ? detail.equipped_weapon : null;
  const equippedArmor = detail.equipped_armor as { name?: string; sp?: number } | undefined;
  const backstoryObj =
    detail.backstory && typeof detail.backstory === "object"
      ? (detail.backstory as Record<string, unknown>)
      : {};
  const lifepathObj =
    detail.lifepath && typeof detail.lifepath === "object"
      ? (detail.lifepath as Record<string, unknown>)
      : {};
  const creationObj =
    detail.creation && typeof detail.creation === "object"
      ? (detail.creation as Record<string, unknown>)
      : {};

  const skillEntries = Object.entries(active.skills).filter(([name]) =>
    skillFilter.trim() ? name.toLowerCase().includes(skillFilter.trim().toLowerCase()) : true,
  );
  const invEntries = Object.entries(active.inventory);

  return (
    <div className="space-y-3 p-3.5">
      {creatorModal}
      {/* Unified Header + Crew Switcher */}
      {characters.length > 1 && (
        <div className="flex flex-wrap gap-1.5">
          {characters.map((c) => {
            const owner = roster.find((p) => p.character_id === c.id);
            const selected = c.id === active.id;
            return (
              <button
                key={c.id}
                type="button"
                onClick={() => setSelectedId(c.id)}
                className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs transition ${
                  selected
                    ? "border-rose-500/70 bg-rose-500/15 text-slate-100 shadow-[0_0_10px_rgba(244,63,94,0.15)]"
                    : "border-slate-800 bg-[#111726] text-slate-400 hover:text-slate-200"
                }`}
              >
                <span className="font-medium">{c.name}</span>
                <span className="font-mono text-[10px] text-slate-400">
                  {c.hp}/{c.max_hp}
                </span>
                {owner && (
                  <span className="rounded bg-cyan-500/15 px-1 text-[10px] text-cyan-300">
                    {owner.player_name}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      )}

      {sheetLocked && (
        <div className="flex items-center gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-1.5 text-xs text-amber-300">
          <Lock className="h-3.5 w-3.5 shrink-0" />
          <span>Controlled by {claimant?.player_name}. Disable sheet protection in Co-op to edit.</span>
        </div>
      )}

      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate text-base font-bold tracking-tight text-slate-100">
              {active.name}
            </h3>
            {rolesList.map((r, i) => (
              <span
                key={i}
                className="rounded border border-cyan-500/30 bg-cyan-500/10 px-1.5 py-0.5 font-mono text-[10px] text-cyan-300"
              >
                {r.role ?? "Edgerunner"} {r.rank !== undefined ? `R${r.rank}` : ""}
              </span>
            ))}
            <span className="font-mono text-[11px] text-slate-500">rev {active.revision}</span>
          </div>
        </div>

        <div className="flex items-center gap-1.5 shrink-0">
          <button
            type="button"
            onClick={handleUndo}
            disabled={busy || sheetLocked}
            title="Undo latest character change"
            className="inline-flex items-center gap-1 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-300 hover:border-amber-500/60 hover:text-amber-300 disabled:opacity-40"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Undo
          </button>
          <button
            type="button"
            onClick={openCreator}
            className="inline-flex items-center gap-1 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-cyan-300 hover:border-cyan-500/60"
          >
            <Plus className="h-3.5 w-3.5" />
            New
          </button>
        </div>
      </div>

      {/* Combat Vitals Hero Card */}
      <div className="cyber-cut rounded-lg border border-slate-800/90 bg-[#101624] p-3 space-y-3">
        <div>
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
            <span className="inline-flex items-center gap-1.5 font-semibold text-slate-100">
              <Heart className="h-3.5 w-3.5 text-rose-400" />
              HP {active.hp} / {active.max_hp}
            </span>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-[10px] text-slate-400">
                Seriously Wounded: <span className="text-slate-200">{threshold}</span>
              </span>
              <span className="font-mono text-[10px] text-slate-400">
                Death Save: <span className="text-slate-200">{active.stats.BODY}</span>
              </span>
              <span
                className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-mono text-[10px] font-semibold ${
                  active.hp < 1
                    ? "bg-rose-500/20 text-rose-300"
                    : active.hp < threshold
                      ? "bg-amber-500/20 text-amber-300"
                      : "bg-emerald-500/15 text-emerald-300"
                }`}
              >
                {active.hp < threshold && <ShieldAlert className="h-3 w-3" />}
                {woundLabel}
              </span>
            </div>
          </div>

          <div className="relative mt-2 h-2.5 w-full overflow-hidden rounded-full bg-slate-900">
            <div
              className={`h-full transition-all ${
                active.hp < 1
                  ? "bg-rose-600"
                  : active.hp < threshold
                    ? "bg-amber-500"
                    : "bg-emerald-500"
              }`}
              style={{ width: `${hpPct}%` }}
            />
            <div
              title={`Seriously Wounded threshold (${threshold} HP)`}
              className="absolute inset-y-0 left-1/2 w-0.5 bg-slate-950/80"
            />
          </div>

          <div className="mt-2 flex items-center justify-between gap-2">
            <div className="flex gap-1">
              {[-5, -1, +1, +5].map((d) => (
                <button
                  key={d}
                  type="button"
                  disabled={busy || sheetLocked}
                  onClick={() => handleHpDelta(d)}
                  className="rounded border border-slate-700/90 bg-slate-950 px-2 py-0.5 font-mono text-[11px] text-slate-300 hover:border-cyan-500/60 disabled:opacity-40"
                >
                  {d > 0 ? `+${d}` : d}
                </button>
              ))}
            </div>
            {injuriesList.length > 0 && (
              <span className="font-mono text-[10px] text-rose-300">
                {injuriesList.length} critical injur{injuriesList.length === 1 ? "y" : "ies"}
              </span>
            )}
          </div>
        </div>

        {/* Humanity, LUCK, Eurobucks */}
        <div className="grid grid-cols-1 gap-2 border-t border-slate-800/80 pt-2.5 sm:grid-cols-3">
          <div className="rounded border border-slate-800/80 bg-slate-950/60 px-2.5 py-2 text-xs">
            <div className="flex items-center justify-between">
              <span className="inline-flex items-center gap-1 text-slate-400">
                <Cpu className="h-3 w-3 text-cyan-400" />
                Humanity
              </span>
              <span className="font-mono font-bold text-cyan-300">
                {active.humanity}/{maxHumanity}
              </span>
            </div>
            <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
              <div
                className={`h-full transition-all ${
                  active.humanity <= 20 ? "bg-rose-500" : "bg-cyan-400"
                }`}
                style={{ width: `${humPct}%` }}
              />
            </div>
            {active.humanity < maxHumanity && (
              <div className="mt-1.5 flex gap-1">
                <button
                  type="button"
                  disabled={busy || sheetLocked || active.money < 500}
                  onClick={() => void handleTherapy("standard")}
                  title="Standard Therapy: 500 eb, +2d6 Humanity (p. 230)"
                  className="flex-1 rounded border border-slate-800 bg-slate-900 py-0.5 font-mono text-[10px] text-cyan-300 hover:border-cyan-500/60 disabled:opacity-40"
                >
                  Therapy 500eb
                </button>
                <button
                  type="button"
                  disabled={busy || sheetLocked || active.money < 1000}
                  onClick={() => void handleTherapy("extreme")}
                  title="Extreme Therapy: 1,000 eb, +4d6 Humanity (p. 230)"
                  className="flex-1 rounded border border-slate-800 bg-slate-900 py-0.5 font-mono text-[10px] text-cyan-300 hover:border-cyan-500/60 disabled:opacity-40"
                >
                  +4d6 1k eb
                </button>
              </div>
            )}
          </div>

          <div className="rounded border border-slate-800/80 bg-slate-950/60 px-2.5 py-2 text-xs">
            <div className="flex items-center justify-between">
              <span className="inline-flex items-center gap-1 text-slate-400">
                <Sparkles className="h-3 w-3 text-amber-400" />
                LUCK
              </span>
              <span className="font-mono font-bold text-amber-300">
                {active.luck_remaining}/{active.stats.LUCK}
              </span>
            </div>
            <div className="mt-2 flex flex-wrap gap-1" aria-hidden="true">
              {Array.from({ length: Math.min(10, active.stats.LUCK) }).map((_, i) => (
                <span
                  key={i}
                  className={`h-1.5 w-1.5 rounded-full ${
                    i < active.luck_remaining ? "bg-amber-400" : "bg-slate-800"
                  }`}
                />
              ))}
            </div>
          </div>

          <div className="rounded border border-slate-800/80 bg-slate-950/60 px-2.5 py-2 text-xs">
            <div className="flex items-center justify-between">
              <span className="inline-flex items-center gap-1 text-slate-400">
                <Coins className="h-3 w-3 text-emerald-400" />
                Eddies
              </span>
              <span className="font-mono font-bold text-emerald-300">{active.money} eb</span>
            </div>
            <div className="mt-1.5 flex gap-1">
              {[-100, -20, +50, +100].map((d) => (
                <button
                  key={d}
                  type="button"
                  disabled={busy || sheetLocked}
                  onClick={() => handleMoneyDelta(d)}
                  className="flex-1 rounded border border-slate-800 bg-slate-900 py-0.5 font-mono text-[10px] text-slate-300 hover:border-emerald-500/60 disabled:opacity-40"
                >
                  {d > 0 ? `+${d}` : d}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* 5x2 Clickable Attributes Strip */}
      <div className="space-y-1.5">
        <div
          className="grid grid-cols-5 gap-1.5"
          onMouseLeave={() => setInspectedStat(null)}
        >
          {STAT_NAMES.map((stat) => {
            const selectedStat = sheetTab === "skills" && checkStat === stat;
            const guide = STAT_QUICK_GUIDE[stat];
            return (
              <button
                key={stat}
                type="button"
                title={`${guide.full} (${stat} ${active.stats[stat]}): ${guide.desc}`}
                onMouseEnter={() => setInspectedStat(stat)}
                onFocus={() => setInspectedStat(stat)}
                onBlur={() => setInspectedStat((prev) => (prev === stat ? null : prev))}
                onClick={() => {
                  setCheckStat(stat);
                  setSheetTab("skills");
                }}
                className={`rounded border px-2 py-1.5 text-center transition ${
                  selectedStat
                    ? "border-cyan-500/70 bg-cyan-950/35"
                    : "border-slate-800 bg-[#101624] hover:border-slate-700"
                }`}
              >
                <div className="font-mono text-[10px] text-slate-400">{stat}</div>
                <div className="font-mono text-sm font-bold text-slate-100">{active.stats[stat]}</div>
              </button>
            );
          })}
        </div>
        {inspectedStat && (
          <div className="flex items-start gap-2 rounded border border-cyan-500/30 bg-cyan-950/25 px-2.5 py-1.5 text-[11px] text-slate-200">
            <HelpCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-cyan-400" />
            <div>
              <span className="font-semibold text-cyan-300">
                {STAT_QUICK_GUIDE[inspectedStat].full} ({inspectedStat}{" "}
                {active.stats[inspectedStat]})
              </span>{" "}
              — {STAT_QUICK_GUIDE[inspectedStat].desc}
            </div>
          </div>
        )}
      </div>

      {/* Tab Navigation */}
      <div className="flex rounded-lg border border-slate-800 bg-[#0c111c] p-1 text-xs">
        <button
          type="button"
          onClick={() => setSheetTab("skills")}
          className={`flex flex-1 items-center justify-center gap-1.5 rounded-md py-1.5 font-medium transition ${
            sheetTab === "skills"
              ? "bg-slate-800 text-cyan-300 shadow-sm"
              : "text-slate-400 hover:text-slate-200"
          }`}
        >
          <Activity className="h-3.5 w-3.5" />
          Skills &amp; Roll
        </button>
        <button
          type="button"
          onClick={() => setSheetTab("gear")}
          className={`flex flex-1 items-center justify-center gap-1.5 rounded-md py-1.5 font-medium transition ${
            sheetTab === "gear"
              ? "bg-slate-800 text-cyan-300 shadow-sm"
              : "text-slate-400 hover:text-slate-200"
          }`}
        >
          <Backpack className="h-3.5 w-3.5" />
          Gear ({invEntries.length})
        </button>
        <button
          type="button"
          onClick={() => setSheetTab("bio")}
          className={`flex flex-1 items-center justify-center gap-1.5 rounded-md py-1.5 font-medium transition ${
            sheetTab === "bio"
              ? "bg-slate-800 text-cyan-300 shadow-sm"
              : "text-slate-400 hover:text-slate-200"
          }`}
        >
          <BookOpen className="h-3.5 w-3.5" />
          Bio
        </button>
        <button
          type="button"
          onClick={() => setSheetTab("log")}
          className={`flex flex-1 items-center justify-center gap-1.5 rounded-md py-1.5 font-medium transition ${
            sheetTab === "log"
              ? "bg-slate-800 text-cyan-300 shadow-sm"
              : "text-slate-400 hover:text-slate-200"
          }`}
        >
          <History className="h-3.5 w-3.5" />
          Log
        </button>
      </div>

      {/* Tab 1: Skills & Authoritative Skill Check */}
      {sheetTab === "skills" && (
        <div className="space-y-3">
          <form
            onSubmit={handleRollCheck}
            className="space-y-2 rounded-lg border border-slate-800 bg-[#101624] p-3"
          >
            <div className="flex items-center justify-between">
              <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-200">
                <Dices className="h-3.5 w-3.5 text-cyan-400" />
                Authoritative Skill Check
              </span>
              <div className="flex items-center gap-2">
                {lastRoll && (
                  <span
                    className={`font-mono text-xs font-bold ${
                      lastRoll.success ? "text-emerald-400" : "text-rose-400"
                    }`}
                  >
                    Total {lastRoll.total} ({lastRoll.success ? "PASS" : "FAIL"})
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => setShowRollExtras((v) => !v)}
                  className="inline-flex items-center gap-0.5 text-[11px] text-slate-400 hover:text-slate-200"
                >
                  {showRollExtras ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                  Options
                </button>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-5">
              <select
                value={checkStat}
                onChange={(e) => setCheckStat(e.target.value as StatName)}
                className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
              >
                {STAT_NAMES.map((s) => (
                  <option key={s} value={s}>
                    {s} ({active.stats[s]})
                  </option>
                ))}
              </select>
              <input
                type="text"
                value={checkSkill}
                onChange={(e) => setCheckSkill(e.target.value)}
                placeholder="Skill (or blank)"
                className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
              />
              <label className="flex items-center gap-1 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs">
                <span className="text-slate-400">DV</span>
                <input
                  type="number"
                  value={checkDv}
                  onChange={(e) => setCheckDv(parseInt(e.target.value, 10) || 13)}
                  className="w-full bg-transparent font-mono text-slate-100 focus:outline-none"
                />
              </label>
              <label className="flex items-center gap-1 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs">
                <span className="text-slate-400">LUCK</span>
                <input
                  type="number"
                  min={0}
                  max={active.luck_remaining}
                  value={checkLuck}
                  onChange={(e) => setCheckLuck(parseInt(e.target.value, 10) || 0)}
                  className="w-full bg-transparent font-mono text-slate-100 focus:outline-none"
                />
              </label>
              <button
                type="submit"
                disabled={busy || sheetLocked}
                className="rounded bg-cyan-600 px-3 py-1 text-xs font-semibold text-white hover:bg-cyan-500 disabled:opacity-50"
              >
                Roll
              </button>
            </div>

            {showRollExtras && (
              <div className="flex gap-2">
                <input
                  type="text"
                  value={checkReason}
                  onChange={(e) => setCheckReason(e.target.value)}
                  placeholder="Reason..."
                  className="flex-1 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-200"
                />
                <label className="flex items-center gap-1 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs">
                  <span className="text-slate-400">Mod</span>
                  <input
                    type="number"
                    value={checkMod}
                    onChange={(e) => setCheckMod(parseInt(e.target.value, 10) || 0)}
                    className="w-12 bg-transparent font-mono text-slate-100 focus:outline-none"
                  />
                </label>
              </div>
            )}
          </form>

          <div className="rounded-lg border border-slate-800 bg-[#101624] p-3 space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                  Skills ({Object.keys(active.skills).length})
                </span>
                <span
                  title="Improvement Points earned from gigs & missions (Corebook pp. 408-411)"
                  className="rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 font-mono text-[10px] text-amber-300"
                >
                  {currentIp} IP
                </span>
              </div>
              {Object.keys(active.skills).length > 5 && (
                <div className="relative w-40">
                  <Search className="pointer-events-none absolute left-2 top-1.5 h-3 w-3 text-slate-500" />
                  <input
                    type="text"
                    value={skillFilter}
                    onChange={(e) => setSkillFilter(e.target.value)}
                    placeholder="Filter skills..."
                    className="w-full rounded border border-slate-700 bg-slate-950 py-0.5 pl-6 pr-2 text-[11px] text-slate-100 focus:border-cyan-400 focus:outline-none"
                  />
                </div>
              )}
            </div>
            <div
              className="flex flex-wrap gap-1.5"
              onMouseLeave={() => setInspectedSkill(null)}
            >
              {skillEntries.length === 0 && (
                <span className="text-xs text-slate-500">
                  {Object.keys(active.skills).length === 0 ? "No trained skills recorded." : "No matching skills."}
                </span>
              )}
              {skillEntries.map(([name, lvl]) => {
                const skillMeta = corebookSkills[name];
                const mappedStat = skillMeta?.stat as StatName | undefined;
                const statVal =
                  mappedStat && STAT_NAMES.includes(mappedStat) ? active.stats[mappedStat] : null;
                const isSelected = checkSkill === name;
                const tooltipText =
                  mappedStat && statVal !== null
                    ? `${name}: ${mappedStat} (${statVal}) + Rank (${lvl}) = Base ${statVal + lvl}${skillMeta?.cost === 2 ? " · Difficult (x2)" : ""}`
                    : `${name}: Rank +${lvl}`;
                return (
                  <button
                    key={name}
                    type="button"
                    title={tooltipText}
                    onMouseEnter={() => setInspectedSkill(name)}
                    onFocus={() => setInspectedSkill(name)}
                    onBlur={() => setInspectedSkill((prev) => (prev === name ? null : prev))}
                    onClick={() => {
                      setCheckSkill(name);
                      if (mappedStat && STAT_NAMES.includes(mappedStat)) {
                        setCheckStat(mappedStat);
                      }
                    }}
                    className={`rounded border px-2 py-1 text-xs transition ${
                      isSelected
                        ? "border-cyan-500 bg-cyan-500/15 text-cyan-100"
                        : "border-slate-700 bg-slate-900 text-slate-200 hover:border-cyan-500/60"
                    }`}
                  >
                    <span>{name}</span>{" "}
                    <span className="font-mono text-cyan-300">+{lvl}</span>
                    {statVal !== null && (
                      <span className="ml-1 font-mono text-[10px] text-slate-400">
                        ({statVal + lvl})
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
            {inspectedSkill && active.skills[inspectedSkill] !== undefined && (
              <div className="rounded border border-slate-800 bg-slate-950/70 px-2.5 py-1.5 text-[11px] text-slate-300">
                {(() => {
                  const lvl = active.skills[inspectedSkill] ?? 0;
                  const meta = corebookSkills[inspectedSkill];
                  const mStat = meta?.stat as StatName | undefined;
                  const sVal = mStat && STAT_NAMES.includes(mStat) ? active.stats[mStat] : null;
                  const nextRank = lvl + 1;
                  const ipCost = nextRank <= 10 ? (isDifficultSkill(inspectedSkill) ? nextRank * 40 : nextRank * 20) : null;
                  return (
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <span className="font-semibold text-cyan-300">{inspectedSkill}</span>
                        {mStat && sVal !== null ? (
                          <span>
                            {" "}
                            — Roll <span className="font-mono">d10 + {mStat} ({sVal}) + Rank ({lvl})</span>{" "}
                            = <span className="font-mono text-emerald-300">d10 + {sVal + lvl}</span>
                            {meta?.cost === 2 ? " · Difficult (x2 cost)" : ""}
                          </span>
                        ) : (
                          <span> — Rank +{lvl} (click to load into check roller)</span>
                        )}
                      </div>
                      {ipCost !== null && (
                        <button
                          type="button"
                          disabled={busy || sheetLocked || currentIp < ipCost}
                          onClick={() => void handleSpendIpSkill(inspectedSkill, lvl)}
                          className="rounded border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 font-mono text-[10px] text-amber-200 hover:bg-amber-500/20 disabled:opacity-40"
                        >
                          Upgrade +1 ({ipCost} IP)
                        </button>
                      )}
                    </div>
                  );
                })()}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Tab 2: Gear, Loadout & Cyberware */}
      {sheetTab === "gear" && (
        <div className="space-y-3">
          {(equippedWeapon || equippedArmor || cyberwareList.length > 0) && (
            <div className="rounded-lg border border-slate-800 bg-[#101624] p-3 space-y-2 text-xs">
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                Loadout &amp; Cyberware
              </div>
              <div className="flex flex-wrap gap-1.5">
                {equippedWeapon && (
                  <span className="rounded border border-rose-500/40 bg-rose-500/10 px-2 py-0.5 font-mono text-[11px] text-rose-200">
                    Weapon: {equippedWeapon}
                  </span>
                )}
                {equippedArmor?.name && (
                  <span className="rounded border border-cyan-500/40 bg-cyan-500/10 px-2 py-0.5 font-mono text-[11px] text-cyan-200">
                    Armor: {equippedArmor.name} {equippedArmor.sp ? `(SP ${equippedArmor.sp})` : ""}
                  </span>
                )}
                {cyberwareList.map((cw, idx) => (
                  <span
                    key={idx}
                    className="rounded border border-violet-500/40 bg-violet-500/10 px-2 py-0.5 font-mono text-[11px] text-violet-200"
                  >
                    {typeof cw === "string" ? cw : String((cw as { name?: string }).name ?? "Cyberware")}
                  </span>
                ))}
                {fashionList.map((f, idx) => (
                  <span
                    key={`f-${idx}`}
                    className="rounded border border-slate-700 bg-slate-900 px-2 py-0.5 font-mono text-[11px] text-slate-300"
                  >
                    Fashion: {typeof f === "string" ? f : f.name || f.style || "Outfit"}
                  </span>
                ))}
              </div>
              {rolesList[0]?.choices && Object.keys(rolesList[0].choices).length > 0 && (
                <div className="border-t border-slate-800/80 pt-2 text-[11px] text-slate-300 space-y-1">
                  <div className="font-semibold uppercase tracking-wider text-slate-400 text-[10px]">
                    Role Benefits &amp; Equipment ({rolesList[0].role ?? "Role"})
                  </div>
                  {Array.isArray(rolesList[0].choices.moto) && (
                    <div>Nomad Moto Motorpool: {(rolesList[0].choices.moto as string[]).join(", ")}</div>
                  )}
                  {Array.isArray(rolesList[0].choices.recipes) && (
                    <div>Medtech Recipes: {(rolesList[0].choices.recipes as string[]).join(", ")}</div>
                  )}
                  {Array.isArray(rolesList[0].choices.maker) && (
                    <div>Tech Maker Ranks: {(rolesList[0].choices.maker as string[]).join(", ")}</div>
                  )}
                  {typeof rolesList[0].choices.team_member === "object" && rolesList[0].choices.team_member !== null && (
                    <div>
                      Exec Team: {String((rolesList[0].choices.team_member as { name?: string }).name ?? "")}{" "}
                      ({String((rolesList[0].choices.team_member as { role?: string }).role ?? "")})
                    </div>
                  )}
                  {typeof rolesList[0].choices.culture === "string" && (
                    <div>
                      Fixer Reach: {rolesList[0].choices.culture} ({String(rolesList[0].choices.language ?? "")})
                    </div>
                  )}
                </div>
              )}
              <div className="text-[11px] text-slate-400">
                Housing: {typeof detail.housing === "string" ? detail.housing : "Cargo Container (Month 1 Paid)"} ·{" "}
                Lifestyle: {typeof detail.lifestyle === "string" ? detail.lifestyle : "Kibble"}
              </div>
            </div>
          )}

          <div className="rounded-lg border border-slate-800 bg-[#101624] p-3 space-y-2">
            <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">
              Inventory Bag
            </div>
            <form onSubmit={handleAddInventory} className="flex gap-2">
              <input
                type="text"
                value={itemName}
                onChange={(e) => setItemName(e.target.value)}
                placeholder="Add item or weapon..."
                className="flex-1 rounded border border-slate-700 bg-slate-950 px-2.5 py-1 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
              />
              <input
                type="number"
                min={1}
                value={itemCount}
                onChange={(e) => setItemCount(Math.max(1, parseInt(e.target.value, 10) || 1))}
                className="w-14 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-center font-mono text-xs text-slate-100"
              />
              <button
                type="submit"
                disabled={busy || sheetLocked || !itemName.trim()}
                className="rounded bg-slate-800 px-3 py-1 text-xs font-medium text-cyan-300 hover:bg-slate-700 disabled:opacity-40"
              >
                Add
              </button>
            </form>
            <div className="space-y-1">
              {invEntries.length === 0 && (
                <p className="text-xs text-slate-500">Empty gear bag.</p>
              )}
              {invEntries.map(([name, qty]) => {
                const confirming = confirmRemoveItem === name;
                return (
                  <div
                    key={name}
                    className="flex items-center justify-between rounded border border-slate-800/80 bg-slate-950/60 px-2.5 py-1.5 text-xs"
                  >
                    <span className="text-slate-200">
                      {name} <span className="font-mono text-slate-400">×{qty}</span>
                    </span>
                    {confirming ? (
                      <div className="flex items-center gap-1.5 font-mono text-[10px]">
                        <button
                          type="button"
                          disabled={busy || sheetLocked}
                          onClick={() => {
                            setConfirmRemoveItem(null);
                            void handleRemoveItem(name);
                          }}
                          className="text-rose-400 hover:text-rose-300 disabled:opacity-40"
                        >
                          Remove
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmRemoveItem(null)}
                          className="text-slate-400 hover:text-slate-200"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button
                        type="button"
                        disabled={busy || sheetLocked}
                        onClick={() => setConfirmRemoveItem(name)}
                        aria-label={`Remove ${name}`}
                        className="text-slate-500 hover:text-rose-400 disabled:opacity-40"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* Tab 3: Backstory, Lifepath & Established History */}
      {sheetTab === "bio" && (
        <div className="space-y-3 text-xs">
          <div className="rounded-lg border border-slate-800 bg-[#101624] p-3 space-y-2.5">
            <div className="flex items-center justify-between gap-2">
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                Backstory &amp; Established History
              </div>
              {!editingBio && (
                <button
                  type="button"
                  disabled={sheetLocked}
                  onClick={() => {
                    setBioConcept(
                      typeof backstoryObj.concept === "string" ? backstoryObj.concept : "",
                    );
                    setBioSummary(
                      typeof backstoryObj.summary === "string" ? backstoryObj.summary : "",
                    );
                    setBioHistory(
                      typeof backstoryObj.established_history === "string"
                        ? backstoryObj.established_history
                        : "",
                    );
                    setBioAppearance(
                      typeof backstoryObj.appearance === "string"
                        ? backstoryObj.appearance
                        : typeof detail.appearance === "string"
                          ? detail.appearance
                          : "",
                    );
                    setEditingBio(true);
                  }}
                  className="inline-flex items-center gap-1 rounded border border-slate-700 bg-slate-900 px-2 py-0.5 text-[11px] text-cyan-300 hover:border-cyan-500/60 disabled:opacity-40"
                >
                  <Pencil className="h-3 w-3" />
                  Edit Bio
                </button>
              )}
            </div>

            {editingBio ? (
              <form onSubmit={handleSaveBio} className="space-y-2">
                <div>
                  <label className="mb-0.5 block text-[11px] text-slate-400">
                    Concept / Reputation
                  </label>
                  <input
                    type="text"
                    value={bioConcept}
                    onChange={(e) => setBioConcept(e.target.value)}
                    placeholder="e.g. Ex-Trauma Team medic running Watson alley clinics"
                    className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="mb-0.5 block text-[11px] text-slate-400">
                    Appearance &amp; Vibe
                  </label>
                  <input
                    type="text"
                    value={bioAppearance}
                    onChange={(e) => setBioAppearance(e.target.value)}
                    placeholder="Signature coat, chrome optics, scars, mannerisms..."
                    className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="mb-0.5 block text-[11px] text-slate-400">
                    Personal Backstory
                  </label>
                  <textarea
                    rows={3}
                    value={bioSummary}
                    onChange={(e) => setBioSummary(e.target.value)}
                    placeholder="Where you came from, why you took to the Edge..."
                    className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="mb-0.5 block text-[11px] text-slate-400">
                    Established Night City History &amp; Ties
                  </label>
                  <textarea
                    rows={3}
                    value={bioHistory}
                    onChange={(e) => setBioHistory(e.target.value)}
                    placeholder="Prior gigs, owed favors, turf, rivals, safehouses..."
                    className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                  />
                </div>
                <div className="flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setEditingBio(false)}
                    className="rounded border border-slate-700 px-2.5 py-1 text-[11px] text-slate-300 hover:bg-slate-800"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={busy}
                    className="inline-flex items-center gap-1 rounded bg-cyan-600 px-3 py-1 text-[11px] font-semibold text-white hover:bg-cyan-500 disabled:opacity-40"
                  >
                    <Save className="h-3 w-3" />
                    Save Bio
                  </button>
                </div>
              </form>
            ) : (
              <div className="space-y-2 text-slate-300">
                {typeof creationObj.method === "string" && (
                  <div className="text-[11px] text-slate-400">
                    Creation Method:{" "}
                    <span className="font-mono text-cyan-300">{creationObj.method}</span>
                  </div>
                )}
                {typeof backstoryObj.concept === "string" && backstoryObj.concept && (
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-slate-500">Concept</div>
                    <p className="text-slate-100">{backstoryObj.concept}</p>
                  </div>
                )}
                {(typeof backstoryObj.appearance === "string" && backstoryObj.appearance) ||
                (typeof detail.appearance === "string" && detail.appearance) ? (
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-slate-500">
                      Appearance
                    </div>
                    <p className="text-slate-200">
                      {String(backstoryObj.appearance || detail.appearance || "")}
                    </p>
                  </div>
                ) : null}
                {typeof backstoryObj.summary === "string" && backstoryObj.summary && (
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-slate-500">
                      Backstory
                    </div>
                    <p className="whitespace-pre-line leading-relaxed text-slate-200">
                      {backstoryObj.summary}
                    </p>
                  </div>
                )}
                {typeof backstoryObj.established_history === "string" &&
                  backstoryObj.established_history && (
                    <div>
                      <div className="text-[10px] uppercase tracking-wider text-slate-500">
                        Established History &amp; Ties
                      </div>
                      <p className="whitespace-pre-line leading-relaxed text-slate-200">
                        {backstoryObj.established_history}
                      </p>
                    </div>
                  )}
                {!backstoryObj.concept &&
                  !backstoryObj.summary &&
                  !backstoryObj.established_history &&
                  !backstoryObj.appearance &&
                  !detail.appearance && (
                    <p className="text-slate-500">
                      No written backstory or established Night City ties recorded yet. Click Edit
                      Bio to give the AI GM hooks to weave into the story.
                    </p>
                  )}
              </div>
            )}
          </div>

          <div className="rounded-lg border border-slate-800 bg-[#101624] p-3 space-y-2">
            <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">
              Lifepath &amp; Connections
            </div>
            {Object.keys(lifepathObj).length === 0 ? (
              <p className="text-slate-500">No Lifepath traits recorded for this character.</p>
            ) : (
              <div className="space-y-2">
                <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                  {(
                    [
                      ["Cultural Region", lifepathObj.cultural_origin ?? lifepathObj.cultural_region],
                      ["Native Language", lifepathObj.native_language],
                      ["Personality", lifepathObj.personality],
                      ["Clothing Style", lifepathObj.clothing_style],
                      ["Hairstyle", lifepathObj.hairstyle],
                      ["Affectation", lifepathObj.affectation],
                      ["Values Most", lifepathObj.value_most ?? lifepathObj.what_you_value],
                      ["About People", lifepathObj.feelings_about_people],
                      ["Person Valued", lifepathObj.valued_person ?? lifepathObj.person_valued],
                      ["Prized Possession", lifepathObj.valued_possession],
                      ["Family Origin", lifepathObj.family_background],
                      ["Childhood", lifepathObj.childhood_environment],
                      ["Family Crisis", lifepathObj.family_crisis],
                      ["Life Goal", lifepathObj.life_goal ?? lifepathObj.life_goals],
                    ] as Array<[string, unknown]>
                  )
                    .filter(([, val]) => typeof val === "string" && val.trim().length > 0)
                    .map(([label, val]) => (
                      <div
                        key={label}
                        className="rounded border border-slate-800/80 bg-slate-950/60 px-2.5 py-1.5"
                      >
                        <div className="text-[10px] uppercase tracking-wider text-slate-500">
                          {label}
                        </div>
                        <div className="text-slate-200">{String(val)}</div>
                      </div>
                    ))}
                </div>

                {Boolean(lifepathObj.role_lifepath) &&
                  typeof lifepathObj.role_lifepath === "object" &&
                  Object.keys(lifepathObj.role_lifepath as Record<string, unknown>).length > 0 && (
                    <div className="space-y-1">
                      <div className="text-[10px] uppercase tracking-wider text-cyan-400">
                        Role Lifepath
                      </div>
                      <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                        {Object.entries(lifepathObj.role_lifepath as Record<string, unknown>)
                          .filter(([, v]) => Boolean(v))
                          .map(([k, v]) => (
                            <div
                              key={k}
                              className="rounded border border-cyan-500/20 bg-cyan-950/15 px-2.5 py-1.5"
                            >
                              <div className="text-[10px] uppercase tracking-wider text-cyan-400/80">
                                {k}
                              </div>
                              <div className="text-slate-200">{String(v)}</div>
                            </div>
                          ))}
                      </div>
                    </div>
                  )}

                {Array.isArray(lifepathObj.friends) && lifepathObj.friends.length > 0 && (
                  <div>
                    <div className="mb-1 text-[10px] uppercase tracking-wider text-emerald-400">
                      Friends ({lifepathObj.friends.length})
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {(
                        lifepathObj.friends as Array<{
                          name?: string;
                          relationship?: string;
                          note?: string;
                        }>
                      ).map((f, i) => (
                        <span
                          key={i}
                          className="rounded border border-emerald-500/30 bg-emerald-950/20 px-2 py-0.5 text-[11px] text-emerald-200"
                        >
                          {f.name || "Friend"}
                          {f.relationship ? ` — ${f.relationship}` : ""}
                          {f.note ? ` (${f.note})` : ""}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {Array.isArray(lifepathObj.enemies) && lifepathObj.enemies.length > 0 && (
                  <div>
                    <div className="mb-1 text-[10px] uppercase tracking-wider text-rose-400">
                      Enemies ({lifepathObj.enemies.length})
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {(
                        lifepathObj.enemies as Array<{
                          name?: string;
                          who?: string;
                          cause?: string;
                          backup?: string;
                          threat?: string;
                        }>
                      ).map((en, i) => (
                        <span
                          key={i}
                          className="rounded border border-rose-500/30 bg-rose-950/20 px-2 py-0.5 text-[11px] text-rose-200"
                        >
                          {en.name ? `${en.name} (${en.who || "Enemy"})` : en.who || "Enemy"}
                          {en.cause ? `: ${en.cause}` : ""}
                          {en.backup || en.threat ? ` (${en.backup || en.threat})` : ""}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {Array.isArray(lifepathObj.tragic_love_affairs) &&
                  lifepathObj.tragic_love_affairs.length > 0 && (
                    <div>
                      <div className="mb-1 text-[10px] uppercase tracking-wider text-amber-400">
                        Tragic Love Affairs ({lifepathObj.tragic_love_affairs.length})
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {(
                          lifepathObj.tragic_love_affairs as Array<{
                            name?: string;
                            who?: string;
                            outcome?: string;
                            what_happened?: string;
                          }>
                        ).map((la, i) => (
                          <span
                            key={i}
                            className="rounded border border-amber-500/30 bg-amber-950/20 px-2 py-0.5 text-[11px] text-amber-200"
                          >
                            {la.name || la.who || "Past flame"}
                            {la.outcome || la.what_happened
                              ? ` — ${la.outcome || la.what_happened}`
                              : ""}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Tab 4: Audit History */}
      {sheetTab === "log" && (
        <div className="rounded-lg border border-slate-800 bg-[#101624] p-3 space-y-1.5">
          <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Recent Audit History
          </div>
          {historyRows.length === 0 && (
            <p className="text-xs text-slate-500">No recorded events yet.</p>
          )}
          {historyRows.map((h) => (
            <div key={h.sequence} className="flex items-center justify-between gap-2 text-xs text-slate-300">
              <span className="truncate">{h.reason}</span>
              <span className="shrink-0 font-mono text-[11px] text-slate-500">rev {h.revision}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
