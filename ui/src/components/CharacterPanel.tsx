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
  EyeOff,
  Heart,
  HelpCircle,
  History,
  Image as ImageIcon,
  Lock,
  Pencil,
  Plus,
  RotateCcw,
  Save,
  Search,
  ShieldAlert,
  Sparkles,
  Trash2,
  Upload,
  UserCheck,
  UserPlus,
  X,
  Zap,
} from "lucide-react";
import {
  deleteCharacter,
  fetchCharacterHistory,
  gameAction,
  postManualChatRoll,
  runSkillCheck,
  undoCharacterChange,
  updateCharacterProfile,
  updateCharacterState,
} from "../api";
import { STAT_NAMES, type CharacterRecord, type CoopPlayer, type StatName } from "../types";
import {
  CHARACTER_COLOR_THEMES,
  isHexColor,
  normalizeColorHex,
  resolveCharacterColor,
} from "../utils/characterColors";
import { getWeaponTierTheme, inferWeaponTierFromName } from "../utils/weaponQuality";
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
  isAdmin?: boolean;
  currentUsername?: string | null;
  activeChannelId?: string;
  overclock?: boolean;
  onToggleOverclock?: () => void;
  selectedSpeakerId?: string;
  onSelectSpeakerId?: (id: string) => void;
  requireCharacterToSpeak?: boolean;
  onOpenCreateCharacter?: () => void;
  onRefresh: () => Promise<void>;
  onNotify: (msg: string) => void;
}

type SheetTab = "skills" | "gear" | "bio" | "log";

type EquipSlot = "weapon" | "armor" | "head_armor";

function inferItemEquipKind(name: string): EquipSlot | null {
  const lower = name.toLowerCase();
  const looksArmor =
    /\b(armor|armorjack|kevlar|leathers|flak|metalgear|bodyweight|subdermal|skinweave|shield)\b|\bsp\s*\d+/i.test(
      lower,
    );
  if (looksArmor) {
    if (/\b(head|helmet|cowl|visor|cap)\b/i.test(lower)) return "head_armor";
    return "armor";
  }
  const looksWeapon =
    /\b(pistol|revolver|smg|rifle|shotgun|sniper|launcher|bow|crossbow|katana|sword|blade|knife|machete|bat|axe|club|hammer|chainsaw|dartgun|microwaver|flamethrower|railgun|melee|handgun|weapon)\b/i.test(
      lower,
    ) || Boolean(inferWeaponTierFromName(name));
  if (looksWeapon) return "weapon";
  return null;
}

function parseArmorSp(name: string): number | undefined {
  const m = name.match(/\bSP\s*[:=]?\s*(\d+)\b/i);
  if (!m) return undefined;
  const parsed = parseInt(m[1], 10);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : undefined;
}

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
  isAdmin = true,
  currentUsername = null,
  activeChannelId = "main",
  overclock = false,
  onToggleOverclock,
  selectedSpeakerId,
  onSelectSpeakerId,
  requireCharacterToSpeak = true,
  onOpenCreateCharacter,
  onRefresh,
  onNotify,
}: CharacterPanelProps) {
  // Filter visible characters: Admin sees all; normal players only see their own character(s)
  // (plus unowned characters if they haven't claimed/created one yet).
  const visibleCharacters = (() => {
    if (isAdmin) return characters;
    const uname = (currentUsername || "").trim().toLowerCase();
    const ownedByMe = characters.filter((c) => {
      const owner = String((c.detail as Record<string, unknown> | undefined)?.owner_username ?? "")
        .trim()
        .toLowerCase();
      return Boolean(uname && owner === uname);
    });
    if (ownedByMe.length > 0) return ownedByMe;
    return characters.filter((c) => {
      const owner = String((c.detail as Record<string, unknown> | undefined)?.owner_username ?? "")
        .trim()
        .toLowerCase();
      return !owner || (uname && owner === uname);
    });
  })();

  const [selectedId, setSelectedId] = useState<string>(() =>
    selectedSpeakerId && visibleCharacters.some((c) => c.id === selectedSpeakerId)
      ? selectedSpeakerId
      : "",
  );
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
  const [equipMenuForItem, setEquipMenuForItem] = useState<string | null>(null);
  const [confirmDeleteChar, setConfirmDeleteChar] = useState(false);
  const [historyRows, setHistoryRows] = useState<
    Array<{ sequence: number; revision: number; reason: string }>
  >([]);

  // Bio / Identity / History editor
  const [editingBio, setEditingBio] = useState(false);
  const [bioHandle, setBioHandle] = useState("");
  const [bioRealName, setBioRealName] = useState("");
  const [bioRealNameHidden, setBioRealNameHidden] = useState(true);
  const [bioGender, setBioGender] = useState("");
  const [bioPronouns, setBioPronouns] = useState("");
  const [bioPortraitUrl, setBioPortraitUrl] = useState("");
  const [bioColor, setBioColor] = useState("cyan");
  const [bioOwner, setBioOwner] = useState("");
  const [bioConcept, setBioConcept] = useState("");
  const [bioSummary, setBioSummary] = useState("");
  const [bioHistory, setBioHistory] = useState("");
  const [bioAppearance, setBioAppearance] = useState("");

  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (preferredSelectedId && visibleCharacters.some((c) => c.id === preferredSelectedId)) {
      setSelectedId(preferredSelectedId);
      setSheetTab("skills");
    }
  }, [preferredSelectedId, visibleCharacters]);

  useEffect(() => {
    if (visibleCharacters.length === 0) {
      setSelectedId("");
      return;
    }
    if (selectedSpeakerId && visibleCharacters.some((c) => c.id === selectedSpeakerId)) {
      setSelectedId((prev) => (prev === selectedSpeakerId ? prev : selectedSpeakerId));
      return;
    }
    if (!visibleCharacters.some((c) => c.id === selectedId)) {
      setSelectedId(visibleCharacters[0].id);
    }
  }, [visibleCharacters, selectedId, selectedSpeakerId]);

  useEffect(() => {
    setConfirmRemoveItem(null);
    setEquipMenuForItem(null);
    setConfirmDeleteChar(false);
    setLastRoll(null);
    setEditingBio(false);
  }, [selectedId, campaignId]);

  const active =
    visibleCharacters.find((c) => c.id === selectedId) ??
    (preferredSelectedId ? visibleCharacters.find((c) => c.id === preferredSelectedId) : undefined) ??
    visibleCharacters[0] ??
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
      const updated = await updateCharacterState(
        campaignId,
        active.id,
        active.revision,
        { inventory: nextInv },
        `Remove ${name}`,
      );
      const clearProfile: {
        equipped_weapon?: null;
        equipped_armor?: null;
        equipped_head_armor?: null;
      } = {};
      if (equippedWeapon === name) clearProfile.equipped_weapon = null;
      if (equippedArmor?.name === name) clearProfile.equipped_armor = null;
      if (equippedHeadArmor?.name === name) clearProfile.equipped_head_armor = null;
      if (Object.keys(clearProfile).length > 0) {
        await updateCharacterProfile(
          campaignId,
          active.id,
          updated.revision,
          clearProfile,
          `Unequip removed ${name}`,
        );
      }
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Inventory remove failed");
    } finally {
      setBusy(false);
    }
  };

  const handleEquipItem = async (slot: EquipSlot, name: string | null) => {
    if (!active || busy) return;
    setBusy(true);
    setEquipMenuForItem(null);
    try {
      const profilePatch: {
        equipped_weapon?: string | null;
        equipped_armor?: { name: string; sp?: number } | null;
        equipped_head_armor?: { name: string; sp?: number } | null;
      } = {};
      if (slot === "weapon") {
        profilePatch.equipped_weapon = name;
      } else if (slot === "armor") {
        if (name) {
          const sp = parseArmorSp(name);
          profilePatch.equipped_armor = sp !== undefined ? { name, sp } : { name };
        } else {
          profilePatch.equipped_armor = null;
        }
      } else {
        if (name) {
          const sp = parseArmorSp(name);
          profilePatch.equipped_head_armor = sp !== undefined ? { name, sp } : { name };
        } else {
          profilePatch.equipped_head_armor = null;
        }
      }
      await updateCharacterProfile(
        campaignId,
        active.id,
        active.revision,
        profilePatch,
        name ? `Equip ${name}` : `Unequip ${slot}`,
      );
      await onRefresh();
      onNotify(name ? `Equipped ${name}.` : `Unequipped ${slot.replace("_", " ")}.`);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Failed to update equipped gear");
    } finally {
      setBusy(false);
    }
  };

  const handleDeleteCharacter = async () => {
    if (!active || busy) return;
    setBusy(true);
    try {
      const res = await deleteCharacter(campaignId, active.id);
      setConfirmDeleteChar(false);
      if (selectedSpeakerId === active.id) {
        onSelectSpeakerId?.("");
      }
      await onRefresh();
      onNotify(`Deleted character ${res.name || active.name}.`);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Failed to delete character");
    } finally {
      setBusy(false);
    }
  };

  const handleRollCheck = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!active || busy) return;
    setBusy(true);
    try {
      let rollRes: {
        total: number;
        success: boolean;
        die: number;
        explosion: number;
        wound_modifier: number;
      };
      try {
        const chatRoll = await postManualChatRoll({
          campaign_id: campaignId,
          character_id: active.id,
          stat: checkStat,
          skill: checkSkill.trim() ? checkSkill.trim() : null,
          dv: checkDv,
          modifier: checkMod,
          luck: checkLuck,
          reason: checkReason.trim() || "Manual check",
          channel_id: activeChannelId,
        });
        rollRes = chatRoll.result;
      } catch {
        rollRes = await runSkillCheck(campaignId, {
          character_id: active.id,
          expected_revision: active.revision,
          stat: checkStat,
          skill: checkSkill.trim() ? checkSkill.trim() : null,
          dv: checkDv,
          modifier: checkMod,
          luck: checkLuck,
          reason: checkReason.trim() || "Manual check",
        });
      }
      setLastRoll(rollRes);
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
      gender: bioGender.trim() || undefined,
      pronouns: bioPronouns.trim() || undefined,
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
          handle: bioHandle.trim() || active.name,
          real_name: bioRealName.trim() || null,
          real_name_hidden: bioRealNameHidden,
          gender: (bioGender === "__custom__" ? "" : bioGender.trim()) || null,
          pronouns: bioPronouns.trim() || null,
          portrait_url: bioPortraitUrl.trim() || null,
          color: bioColor,
          ...(isAdmin ? { owner_username: bioOwner.trim() || null } : {}),
        },
        "Updated character identity, portrait & bio",
      );
      setEditingBio(false);
      await onRefresh();
      onNotify(`Saved identity & bio for ${bioHandle.trim() || active.name}.`);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Bio update failed");
    } finally {
      setBusy(false);
    }
  };

  const handleClaimCharacter = async () => {
    if (!active || !currentUsername || busy) return;
    setBusy(true);
    try {
      await updateCharacterProfile(
        campaignId,
        active.id,
        active.revision,
        { owner_username: currentUsername },
        `Claimed by ${currentUsername}`,
      );
      await onRefresh();
      onNotify(`Claimed ${active.name} for your account (${currentUsername}).`);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Failed to claim character");
    } finally {
      setBusy(false);
    }
  };

  const handlePortraitFileSelect = (file: File | undefined) => {
    if (!file) return;
    if (file.size > 2.5 * 1024 * 1024) {
      onNotify("Portrait image must be under 2.5 MB.");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") {
        setBioPortraitUrl(reader.result);
      }
    };
    reader.readAsDataURL(file);
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

  if (visibleCharacters.length === 0) {
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
              Build your own independent Cyberpunk RED character sheet with Corebook Roles, hover/click rulebook
              explanations, official STAT &amp; Skill templates or custom builds, Lifepath history,
              written backstory, custom portrait, and starting gear.
            </p>

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
  const ownerUsername = typeof detail.owner_username === "string" && detail.owner_username.trim() ? detail.owner_username.trim() : null;
  const ownedByOtherAccount = Boolean(
    !isAdmin &&
      ownerUsername &&
      currentUsername &&
      ownerUsername.toLowerCase() !== currentUsername.toLowerCase(),
  );
  const sheetLocked = Boolean(
    ownedByOtherAccount || (protectOthers && claimant && claimant.client_id !== selfClientId),
  );
  const activeHandle = typeof detail.handle === "string" && detail.handle.trim() ? detail.handle.trim() : active.name;
  const activeRealName = typeof detail.real_name === "string" && detail.real_name.trim() ? detail.real_name.trim() : null;
  const activeRealNameHidden = Boolean(
    detail.real_name_hidden ?? (activeRealName && activeHandle !== activeRealName),
  );
  const activePortraitUrl = typeof detail.portrait_url === "string" ? detail.portrait_url.trim() : "";
  const rawActiveColor = typeof detail.color === "string" ? detail.color.trim() : "";
  const activeColorKey =
    rawActiveColor && (CHARACTER_COLOR_THEMES[rawActiveColor] || isHexColor(rawActiveColor))
      ? rawActiveColor
      : "cyan";
  const activeColorTheme = resolveCharacterColor(activeColorKey);

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
  const equippedWeapon = typeof detail.equipped_weapon === "string" && detail.equipped_weapon.trim() ? detail.equipped_weapon.trim() : null;
  const equippedArmor = detail.equipped_armor as { name?: string; sp?: number } | undefined;
  const equippedHeadArmor = detail.equipped_head_armor as { name?: string; sp?: number } | undefined;
  const canDelete = Boolean(
    isAdmin ||
      (ownerUsername &&
        currentUsername &&
        ownerUsername.toLowerCase() === currentUsername.toLowerCase()),
  );
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
      {(visibleCharacters.length > 1 || (onSelectSpeakerId && (isAdmin || !requireCharacterToSpeak))) && (
        <div className="flex flex-wrap items-center gap-1.5">
          {visibleCharacters.map((c) => {
            const owner = roster.find((p) => p.character_id === c.id);
            const cDet = (c.detail ?? {}) as Record<string, unknown>;
            const cHandle = typeof cDet.handle === "string" && cDet.handle.trim() ? cDet.handle.trim() : c.name;
            const cOwnerUser = typeof cDet.owner_username === "string" ? cDet.owner_username.trim() : "";
            const selected = c.id === active.id;
            const isSpeaking = selectedSpeakerId === c.id;
            return (
              <button
                key={c.id}
                type="button"
                onClick={() => {
                  setSelectedId(c.id);
                  onSelectSpeakerId?.(c.id);
                }}
                className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs transition ${
                  selected
                    ? "border-rose-500/70 bg-rose-500/15 text-slate-100 shadow-[0_0_10px_rgba(244,63,94,0.15)]"
                    : "border-slate-800 bg-[#111726] text-slate-400 hover:text-slate-200"
                }`}
              >
                {isSpeaking && (
                  <span
                    title="Active speaker in chat"
                    className="h-1.5 w-1.5 rounded-full bg-cyan-400 shadow-[0_0_6px_#22d3ee]"
                  />
                )}
                <span className="font-medium">{cHandle}</span>
                <span className="font-mono text-[10px] text-slate-400">
                  {c.hp}/{c.max_hp}
                </span>
                {(owner || cOwnerUser) && (
                  <span className="rounded bg-cyan-500/15 px-1 text-[10px] text-cyan-300">
                    {owner?.player_name || cOwnerUser}
                  </span>
                )}
              </button>
            );
          })}
          {onSelectSpeakerId && (isAdmin || !requireCharacterToSpeak) && (
            <button
              type="button"
              onClick={() => onSelectSpeakerId("")}
              title="Speak in chat as Party / General instead of a specific character"
              className={`rounded-md border px-2 py-1 text-[11px] font-medium transition ${
                selectedSpeakerId === ""
                  ? "border-cyan-500/60 bg-cyan-500/15 text-cyan-200"
                  : "border-slate-800 bg-[#111726] text-slate-400 hover:text-slate-200"
              }`}
            >
              Party / General
            </button>
          )}
        </div>
      )}

      {sheetLocked && (
        <div className="flex items-center gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-1.5 text-xs text-amber-300">
          <Lock className="h-3.5 w-3.5 shrink-0" />
          <span>
            {ownedByOtherAccount
              ? `Owned by ${ownerUsername}. Only ${ownerUsername} or Admin can modify this sheet.`
              : `Controlled by ${claimant?.player_name}. Disable sheet protection in Party to edit.`}
          </span>
        </div>
      )}

      {!ownerUsername && currentUsername && !isAdmin && (
        <div className="flex items-center justify-between gap-2 rounded-md border border-cyan-500/40 bg-cyan-950/25 px-3 py-1.5 text-xs text-cyan-200">
          <span>This character is currently unclaimed. Claim it as your independent Edgerunner?</span>
          <button
            type="button"
            disabled={busy}
            onClick={() => void handleClaimCharacter()}
            className="inline-flex items-center gap-1 rounded bg-cyan-600 px-2.5 py-1 font-semibold text-white hover:bg-cyan-500"
          >
            <UserCheck className="h-3.5 w-3.5" />
            <span>Claim Sheet</span>
          </button>
        </div>
      )}

      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-3">
          {activePortraitUrl ? (
            <img
              src={activePortraitUrl}
              alt={activeHandle}
              className={`h-11 w-11 shrink-0 rounded-lg object-cover ring-2 ${activeColorTheme.avatarRingClass}`}
              style={activeColorTheme.avatarRingStyle}
            />
          ) : (
            <div
              className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border font-cyber-display text-sm font-bold uppercase ${activeColorTheme.nameBadgeClass}`}
              style={activeColorTheme.nameBadgeStyle}
            >
              {activeHandle.slice(0, 2)}
            </div>
          )}
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="truncate text-base font-bold tracking-tight text-slate-100">
                {activeHandle}
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
            <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
              {activeRealName && (
                <span className="inline-flex items-center gap-1">
                  <span>Real Name: <strong className="text-slate-300">{activeRealName}</strong></span>
                  {activeRealNameHidden ? (
                    <span
                      title="NPCs and other players only know your Street Handle unless revealed in play"
                      className="inline-flex items-center gap-0.5 rounded border border-amber-500/35 bg-amber-500/10 px-1.5 py-0.2 font-mono text-[9px] text-amber-300"
                    >
                      <EyeOff className="h-2.5 w-2.5" /> Hidden
                    </span>
                  ) : (
                    <span className="rounded border border-slate-700 bg-slate-900 px-1.5 py-0.2 font-mono text-[9px] text-slate-400">
                      Known
                    </span>
                  )}
                </span>
              )}
              {ownerUsername && (
                <span className="font-mono text-[10px] text-cyan-300/80">
                  Player: {ownerUsername}
                </span>
              )}
            </div>
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
          {confirmDeleteChar ? (
            <div className="inline-flex items-center gap-1 rounded border border-rose-500/50 bg-rose-950/40 px-2 py-1 text-xs">
              <button
                type="button"
                disabled={busy}
                onClick={() => void handleDeleteCharacter()}
                className="font-semibold text-rose-300 hover:text-rose-200 disabled:opacity-40"
              >
                Confirm Delete
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => setConfirmDeleteChar(false)}
                className="text-slate-400 hover:text-slate-200"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              type="button"
              disabled={busy || !canDelete}
              onClick={() => setConfirmDeleteChar(true)}
              title={
                canDelete
                  ? `Delete ${activeHandle}`
                  : !ownerUsername
                    ? "Claim this character first to delete it"
                    : `Owned by ${ownerUsername}. Only its owner or Admin can delete it.`
              }
              aria-label={`Delete ${activeHandle}`}
              className="inline-flex items-center gap-1 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-400 hover:border-rose-500/60 hover:text-rose-300 disabled:opacity-40"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          )}
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

        {onToggleOverclock && (
          <button
            type="button"
            onClick={onToggleOverclock}
            aria-pressed={overclock}
            title="Spend 2 Humanity to gain +2 on your primary check next turn"
            className={`cyber-overclock-btn flex w-full items-center justify-between gap-2 rounded-md border px-3 py-1.5 text-xs font-semibold ${
              overclock
                ? "cyber-overclock-active border-rose-500 bg-rose-600/25 text-rose-100"
                : "border-slate-800 bg-slate-950/80 text-slate-300 hover:border-rose-500/50 hover:text-rose-200"
            }`}
          >
            <span className="inline-flex items-center gap-1.5 font-cyber-display text-[11px] tracking-wider uppercase">
              <Zap className={`h-3.5 w-3.5 ${overclock ? "text-cyan-300" : "text-rose-400"}`} />
              Overclock
            </span>
            <span className="font-mono text-[10px]">
              {overclock ? "ARMED // -2 HUM +2 CHK" : "-2 Humanity / +2 Check"}
            </span>
          </button>
        )}
      </div>

      {/* 5x2 Clickable Attributes Strip */}
      <div className="space-y-1.5">
        <div
          className="grid grid-cols-5 gap-1.5"
          onMouseLeave={() => setInspectedStat(null)}
        >
          {STAT_NAMES.map((stat) => {
            const selectedStat = sheetTab === "skills" && checkStat === stat;
            return (
              <button
                key={stat}
                type="button"
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
        {(() => {
          const displayedStat = inspectedStat ?? checkStat;
          return (
            <div className="flex min-h-[52px] items-start gap-2 rounded border border-cyan-500/30 bg-cyan-950/25 px-2.5 py-1.5 text-[11px] leading-snug text-slate-200">
              <HelpCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-cyan-400" />
              <div>
                <span className="font-semibold text-cyan-300">
                  {STAT_QUICK_GUIDE[displayedStat].full} ({displayedStat}{" "}
                  {active.stats[displayedStat]})
                </span>{" "}
                — {STAT_QUICK_GUIDE[displayedStat].desc}
              </div>
            </div>
          );
        })()}
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
              <div className="flex items-center gap-2">
                <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-200">
                  <Dices className="h-3.5 w-3.5 text-cyan-400" />
                  Manual Skill Roll
                </span>
                <span className="font-mono text-[10px] text-slate-500">
                  (Authoritative Skill Check · Posts to Chat)
                </span>
              </div>
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
            {(() => {
              const displayedSkill =
                inspectedSkill && active.skills[inspectedSkill] !== undefined
                  ? inspectedSkill
                  : active.skills[checkSkill] !== undefined
                    ? checkSkill
                    : null;
              if (!displayedSkill) {
                return (
                  <div className="flex min-h-[42px] items-center rounded border border-slate-800 bg-slate-950/70 px-2.5 py-1.5 text-[11px] text-slate-500">
                    Hover or select a trained skill to inspect roll math and IP upgrade cost.
                  </div>
                );
              }
              const lvl = active.skills[displayedSkill] ?? 0;
              const meta = corebookSkills[displayedSkill];
              const mStat = meta?.stat as StatName | undefined;
              const sVal = mStat && STAT_NAMES.includes(mStat) ? active.stats[mStat] : null;
              const nextRank = lvl + 1;
              const ipCost = nextRank <= 10 ? (isDifficultSkill(displayedSkill) ? nextRank * 40 : nextRank * 20) : null;
              return (
                <div className="flex min-h-[42px] flex-wrap items-center justify-between gap-2 rounded border border-slate-800 bg-slate-950/70 px-2.5 py-1.5 text-[11px] text-slate-300">
                  <div>
                    <span className="font-semibold text-cyan-300">{displayedSkill}</span>
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
                      onClick={() => void handleSpendIpSkill(displayedSkill, lvl)}
                      className="rounded border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 font-mono text-[10px] text-amber-200 hover:bg-amber-500/20 disabled:opacity-40"
                    >
                      Upgrade +1 ({ipCost} IP)
                    </button>
                  )}
                </div>
              );
            })()}
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
          </div>
        </div>
      )}

      {/* Tab 2: Gear, Loadout & Cyberware */}
      {sheetTab === "gear" && (
        <div className="space-y-3">
          {(equippedWeapon || equippedArmor?.name || equippedHeadArmor?.name || cyberwareList.length > 0) && (
            <div className="rounded-lg border border-slate-800 bg-[#101624] p-3 space-y-2 text-xs">
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                Loadout &amp; Cyberware
              </div>
              <div className="flex flex-wrap gap-1.5">
                {equippedWeapon && (() => {
                  const wTier = inferWeaponTierFromName(equippedWeapon);
                  const wTheme = wTier ? getWeaponTierTheme(wTier) : null;
                  return (
                    <span
                      className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 font-mono text-[11px] ${
                        wTheme ? wTheme.badgeClass : "border-rose-500/40 bg-rose-500/10 text-rose-200"
                      }`}
                    >
                      <span>Weapon: {equippedWeapon}</span>
                      {!sheetLocked && (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => void handleEquipItem("weapon", null)}
                          aria-label={`Unequip ${equippedWeapon}`}
                          title="Unequip weapon"
                          className="ml-0.5 opacity-70 hover:opacity-100 disabled:opacity-40"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      )}
                    </span>
                  );
                })()}
                {equippedArmor?.name && (
                  <span className="inline-flex items-center gap-1 rounded border border-cyan-500/40 bg-cyan-500/10 px-2 py-0.5 font-mono text-[11px] text-cyan-200">
                    <span>
                      Body Armor: {equippedArmor.name} {equippedArmor.sp !== undefined ? `(SP ${equippedArmor.sp})` : ""}
                    </span>
                    {!sheetLocked && (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void handleEquipItem("armor", null)}
                        aria-label={`Unequip ${equippedArmor.name}`}
                        title="Unequip body armor"
                        className="ml-0.5 opacity-70 hover:opacity-100 disabled:opacity-40"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    )}
                  </span>
                )}
                {equippedHeadArmor?.name && (
                  <span className="inline-flex items-center gap-1 rounded border border-cyan-500/40 bg-cyan-500/10 px-2 py-0.5 font-mono text-[11px] text-cyan-200">
                    <span>
                      Head Armor: {equippedHeadArmor.name} {equippedHeadArmor.sp !== undefined ? `(SP ${equippedHeadArmor.sp})` : ""}
                    </span>
                    {!sheetLocked && (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void handleEquipItem("head_armor", null)}
                        aria-label={`Unequip ${equippedHeadArmor.name}`}
                        title="Unequip head armor"
                        className="ml-0.5 opacity-70 hover:opacity-100 disabled:opacity-40"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    )}
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
                const wTier = inferWeaponTierFromName(name);
                const wTheme = wTier ? getWeaponTierTheme(wTier) : null;
                const isEquippedWeapon = equippedWeapon === name;
                const isEquippedBody = equippedArmor?.name === name;
                const isEquippedHead = equippedHeadArmor?.name === name;
                const isEquipped = isEquippedWeapon || isEquippedBody || isEquippedHead;
                const inferredSlot = inferItemEquipKind(name);
                const menuOpen = equipMenuForItem === name;
                return (
                  <div
                    key={name}
                    className={`flex flex-wrap items-center justify-between gap-2 rounded border px-2.5 py-1.5 text-xs ${
                      wTheme ? wTheme.cardClass : "border-slate-800/80 bg-slate-950/60"
                    }`}
                  >
                    <span className="flex flex-wrap items-center gap-1.5 text-slate-200">
                      <span>{name}</span>
                      {wTheme && wTier && (
                        <span className={`rounded px-1 py-0.5 font-mono text-[9px] font-bold ${wTheme.badgeClass}`}>
                          {wTheme.label}
                        </span>
                      )}
                      {isEquipped && (
                        <span className="rounded border border-emerald-500/40 bg-emerald-500/15 px-1.5 py-0.5 font-mono text-[9px] font-semibold text-emerald-300">
                          {isEquippedWeapon ? "Equipped Weapon" : isEquippedHead ? "Worn Head" : "Worn Body"}
                        </span>
                      )}
                      <span className="font-mono text-slate-400">×{qty}</span>
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
                      <div className="flex items-center gap-1.5">
                        {!sheetLocked && (
                          isEquipped ? (
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() =>
                                void handleEquipItem(
                                  isEquippedWeapon ? "weapon" : isEquippedHead ? "head_armor" : "armor",
                                  null,
                                )
                              }
                              className="rounded border border-emerald-500/40 bg-emerald-950/30 px-1.5 py-0.5 font-mono text-[10px] text-emerald-300 hover:border-amber-500/50 hover:text-amber-200 disabled:opacity-40"
                            >
                              Unequip
                            </button>
                          ) : inferredSlot ? (
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => void handleEquipItem(inferredSlot, name)}
                              className="rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 font-mono text-[10px] text-cyan-300 hover:border-cyan-500/60 disabled:opacity-40"
                            >
                              Equip
                            </button>
                          ) : menuOpen ? (
                            <div className="inline-flex items-center gap-1 font-mono text-[10px]">
                              <button
                                type="button"
                                disabled={busy}
                                onClick={() => void handleEquipItem("weapon", name)}
                                className="rounded border border-rose-500/40 bg-rose-950/30 px-1.5 py-0.5 text-rose-200 hover:border-rose-400"
                              >
                                Weapon
                              </button>
                              <button
                                type="button"
                                disabled={busy}
                                onClick={() => void handleEquipItem("armor", name)}
                                className="rounded border border-cyan-500/40 bg-cyan-950/30 px-1.5 py-0.5 text-cyan-200 hover:border-cyan-400"
                              >
                                Body
                              </button>
                              <button
                                type="button"
                                disabled={busy}
                                onClick={() => void handleEquipItem("head_armor", name)}
                                className="rounded border border-cyan-500/40 bg-cyan-950/30 px-1.5 py-0.5 text-cyan-200 hover:border-cyan-400"
                              >
                                Head
                              </button>
                              <button
                                type="button"
                                onClick={() => setEquipMenuForItem(null)}
                                className="text-slate-400 hover:text-slate-200"
                              >
                                ×
                              </button>
                            </div>
                          ) : (
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => setEquipMenuForItem(name)}
                              className="rounded border border-slate-800 bg-slate-900/70 px-1.5 py-0.5 font-mono text-[10px] text-slate-400 hover:border-cyan-500/50 hover:text-cyan-300 disabled:opacity-40"
                            >
                              Equip...
                            </button>
                          )
                        )}
                        <button
                          type="button"
                          disabled={busy || sheetLocked}
                          onClick={() => setConfirmRemoveItem(name)}
                          aria-label={`Remove ${name}`}
                          className="text-slate-500 hover:text-rose-400 disabled:opacity-40"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
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
                Identity, Portrait &amp; Backstory
              </div>
              {!editingBio && (
                <button
                  type="button"
                  disabled={sheetLocked}
                  onClick={() => {
                    setBioHandle(activeHandle);
                    setBioRealName(activeRealName ?? "");
                    setBioRealNameHidden(activeRealNameHidden);
                    setBioGender(
                      typeof detail.gender === "string"
                        ? detail.gender
                        : typeof backstoryObj.gender === "string"
                          ? backstoryObj.gender
                          : "",
                    );
                    setBioPronouns(
                      typeof detail.pronouns === "string"
                        ? detail.pronouns
                        : typeof backstoryObj.pronouns === "string"
                          ? backstoryObj.pronouns
                          : "",
                    );
                    setBioPortraitUrl(activePortraitUrl);
                    setBioColor(activeColorKey);
                    setBioOwner(ownerUsername ?? "");
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
                  Edit Bio &amp; Portrait
                </button>
              )}
            </div>

            {editingBio ? (
              <form onSubmit={handleSaveBio} className="space-y-2.5">
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <div>
                    <label className="mb-0.5 block text-[11px] text-slate-400">
                      Street Handle / Alias (Primary)
                    </label>
                    <input
                      type="text"
                      value={bioHandle}
                      onChange={(e) => setBioHandle(e.target.value)}
                      placeholder="e.g. V, Kiwi, Blackhand..."
                      className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                    />
                  </div>
                  <div>
                    <div className="mb-0.5 flex items-center justify-between gap-1">
                      <label className="text-[11px] text-slate-400">
                        Real / Legal Name (Optional)
                      </label>
                      <label className="inline-flex cursor-pointer items-center gap-1 text-[10px] text-amber-300">
                        <input
                          type="checkbox"
                          checked={bioRealNameHidden}
                          onChange={(e) => setBioRealNameHidden(e.target.checked)}
                          className="rounded border-slate-700 bg-slate-950 accent-amber-500"
                        />
                        <span>Hidden (Known by Handle only)</span>
                      </label>
                    </div>
                    <input
                      type="text"
                      value={bioRealName}
                      onChange={(e) => setBioRealName(e.target.value)}
                      placeholder="Leave blank if known strictly by Handle..."
                      className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="mb-0.5 block text-[11px] text-slate-400">Gender</label>
                    <input
                      type="text"
                      aria-label="Edit character gender"
                      list="cpr-panel-gender-list"
                      value={bioGender === "__custom__" ? "" : bioGender}
                      onChange={(e) => setBioGender(e.target.value)}
                      placeholder="Woman, Man, Non-Binary..."
                      className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                    />
                    <datalist id="cpr-panel-gender-list">
                      <option value="Woman" />
                      <option value="Man" />
                      <option value="Non-Binary" />
                      <option value="Genderfluid" />
                      <option value="Agender" />
                    </datalist>
                  </div>
                  <div>
                    <label className="mb-0.5 block text-[11px] text-slate-400">Pronouns</label>
                    <input
                      type="text"
                      value={bioPronouns}
                      onChange={(e) => setBioPronouns(e.target.value)}
                      placeholder="she/her, he/him, they/them..."
                      className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                    />
                  </div>
                </div>

                <div className="space-y-1.5 rounded border border-slate-800 bg-slate-950/60 p-2.5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <label className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-slate-300">
                      <ImageIcon className="h-3.5 w-3.5 text-cyan-400" />
                      Character Portrait (URL or Upload)
                    </label>
                    <label className="inline-flex cursor-pointer items-center gap-1 rounded border border-cyan-500/40 bg-cyan-500/10 px-2 py-0.5 text-[10px] text-cyan-200 hover:bg-cyan-500/20">
                      <Upload className="h-3 w-3" />
                      <span>Upload Image</span>
                      <input
                        type="file"
                        accept="image/*"
                        onChange={(e) => handlePortraitFileSelect(e.target.files?.[0])}
                        className="hidden"
                      />
                    </label>
                  </div>
                  <div className="flex items-center gap-2">
                    {bioPortraitUrl && (
                      <img
                        src={bioPortraitUrl}
                        alt="Preview"
                        className="h-9 w-9 shrink-0 rounded object-cover ring-1 ring-cyan-500/50"
                      />
                    )}
                    <input
                      type="text"
                      value={bioPortraitUrl}
                      onChange={(e) => setBioPortraitUrl(e.target.value)}
                      placeholder="Paste image URL (https://...) or upload a portrait file..."
                      className="flex-1 rounded border border-slate-700 bg-slate-950 px-2.5 py-1 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                    />
                    {bioPortraitUrl && (
                      <button
                        type="button"
                        onClick={() => setBioPortraitUrl("")}
                        className="rounded border border-slate-700 px-2 py-1 text-[10px] text-slate-400 hover:text-rose-300"
                      >
                        Clear
                      </button>
                    )}
                  </div>
                </div>

                <div className="flex flex-wrap items-center justify-between gap-2 rounded border border-slate-800 bg-slate-950/60 p-2.5">
                  <span className="text-[11px] text-slate-300">Chat Name Tag Color:</span>
                  <div className="flex flex-wrap items-center gap-1.5">
                    {Object.entries(CHARACTER_COLOR_THEMES).map(([cid, theme]) => (
                      <button
                        key={cid}
                        type="button"
                        onClick={() => setBioColor(cid)}
                        className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[10px] transition ${
                          bioColor === cid
                            ? `${theme.nameBadgeClass} font-bold`
                            : "border-slate-800 bg-slate-900 text-slate-400 hover:text-slate-200"
                        }`}
                      >
                        <span className={`h-2 w-2 rounded-full ${theme.dotClass}`} />
                        {theme.label.split(" ")[1] || theme.label}
                      </button>
                    ))}
                    <label
                      className="inline-flex cursor-pointer items-center gap-1 rounded border border-slate-700 bg-slate-900 px-2 py-0.5 font-mono text-[10px] text-slate-200 hover:border-cyan-400"
                      style={isHexColor(bioColor) ? resolveCharacterColor(bioColor).nameBadgeStyle : undefined}
                    >
                      <input
                        type="color"
                        aria-label="Edit character color wheel"
                        value={normalizeColorHex(bioColor)}
                        onChange={(e) => setBioColor(e.target.value)}
                        className="h-3 w-3.5 cursor-pointer border-0 bg-transparent p-0"
                      />
                      <span>{isHexColor(bioColor) ? bioColor.toUpperCase() : "Wheel"}</span>
                    </label>
                  </div>
                </div>

                {isAdmin && (
                  <div>
                    <label className="mb-0.5 block text-[11px] text-slate-400">
                      Assigned Player Account (Admin Only — leave blank for shared/unclaimed)
                    </label>
                    <input
                      type="text"
                      value={bioOwner}
                      onChange={(e) => setBioOwner(e.target.value)}
                      placeholder="Account username..."
                      className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                    />
                  </div>
                )}
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
                {Boolean(detail.gender || backstoryObj.gender || detail.pronouns || backstoryObj.pronouns) && (
                  <div className="flex flex-wrap gap-3 text-[11px] text-slate-300">
                    {Boolean(detail.gender || backstoryObj.gender) && (
                      <span>
                        <span className="text-slate-500">Gender:</span>{" "}
                        {String(detail.gender || backstoryObj.gender)}
                      </span>
                    )}
                    {Boolean(detail.pronouns || backstoryObj.pronouns) && (
                      <span>
                        <span className="text-slate-500">Pronouns:</span>{" "}
                        {String(detail.pronouns || backstoryObj.pronouns)}
                      </span>
                    )}
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
