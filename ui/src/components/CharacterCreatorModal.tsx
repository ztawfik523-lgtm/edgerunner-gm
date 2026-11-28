import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import edgerunnerChromeBanner from "../assets/edgerunner-chrome-banner.jpg";
import {
  AlertTriangle,
  ArrowUpDown,
  Backpack,
  BookOpen,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Cpu,
  Dices,
  Eye,
  EyeOff,
  Heart,
  ImagePlus,
  Minus,
  Palette,
  Plus,
  RotateCcw,
  Search,
  Shield,
  Sparkles,
  Trash2,
  UserPlus,
  Users,
  Wand2,
  X,
} from "lucide-react";
import {
  assistCharacterCreation,
  createRulesPlayerCharacter,
  fetchCreationReference,
} from "../api";
import { clearDraft, loadDraft, saveDraft } from "../draftStorage";
import {
  CHARACTER_COLOR_THEMES,
  isHexColor,
  normalizeColorHex,
  resolveCharacterColor,
} from "../utils/characterColors";
import {
  classifyWeaponGenre,
  classifyWeaponTiers,
  getWeaponTierTheme,
  type WeaponGenre,
  type WeaponTierFilter,
} from "../utils/weaponQuality";
import {
  STAT_NAMES,
  type CreationKitCyberware,
  type CreationKitEntry,
  type CreationKitItem,
  type CreationMethodInfo,
  type CreationReference,
  type CreationRoleInfo,
  type CreationShopItem,
  type CreationSkillInfo,
  type StatName,
} from "../types";
import { CyberFrame, HazardBadge, HudButton, RoleTag, SegmentedBar } from "./cyber";
import { FieldAiActions } from "./FieldAiActions";

interface CharacterCreatorModalProps {
  open: boolean;
  campaignId: string;
  soloRevision: number;
  onClose: () => void;
  onCreated: (characterId: string, name: string) => Promise<void>;
  onNotify: (msg: string) => void;
}

type CreatorStep = "identity" | "stats" | "skills" | "lifepath" | "gear" | "review";

interface InspectorCard {
  title: string;
  subtitle?: string;
  body: string;
  mechanics?: string;
  tip?: string;
}

interface FriendEntry {
  name: string;
  relationship: string;
  note: string;
}

interface EnemyEntry {
  who: string;
  name: string;
  wronged: "I wronged them" | "They wronged me";
  cause: string;
  backup: string;
  revenge: string;
}

interface LoveEntry {
  name: string;
  outcome: string;
}

function parseHlVal(stats: Record<string, unknown>): number {
  if (typeof stats.hl === "number" && Number.isFinite(stats.hl)) return stats.hl;
  const raw = stats.humanity_loss;
  if (typeof raw === "number" && Number.isFinite(raw)) return raw;
  if (typeof raw === "string") {
    const m = raw.match(/\d+/);
    if (m) return Number.parseInt(m[0], 10) || 0;
  }
  return 0;
}

function parseSpVal(stats: Record<string, unknown>): number {
  if (typeof stats.sp === "number" && Number.isFinite(stats.sp)) return stats.sp;
  const raw = stats.damage_stopping_power_sp;
  if (typeof raw === "number" && Number.isFinite(raw)) return raw;
  if (typeof raw === "string") {
    const m = raw.match(/\d+/);
    if (m) return Number.parseInt(m[0], 10) || 0;
  }
  return 0;
}

const STEPS: Array<{ id: CreatorStep; label: string; short: string }> = [
  { id: "identity", label: "1. Identity & Role", short: "Role" },
  { id: "stats", label: "2. STATs & Vitals", short: "STATs" },
  { id: "skills", label: "3. Skills", short: "Skills" },
  { id: "lifepath", label: "4. Backstory & Lifepath", short: "Lifepath" },
  { id: "gear", label: "5. Gear & Cyberware", short: "Gear" },
  { id: "review", label: "6. Sheet Preview", short: "Review" },
];

const HANDLE_SUGGESTIONS = [
  "Vee Mercer",
  "Rook Sato",
  "Nyx Vasquez",
  "Kestrel Cho",
  "Dante Kurosawa",
  "Sable Orlov",
  "Juno Reyes",
  "Cipher Vance",
  "Tora Lindqvist",
  "Marrow Novak",
  "Hex Callahan",
  "Kira Sterling",
];

const MAKER_SPECIALTIES = [
  "Field Expertise",
  "Upgrade Expertise",
  "Fabrication Expertise",
  "Invention Expertise",
] as const;

const SPECIALIZATION_BASES = ["Language", "Local Expert", "Science", "Play Instrument", "Martial Arts"] as const;

const FALLBACK_STATS: Record<StatName, number> = {
  INT: 6,
  REF: 6,
  DEX: 6,
  TECH: 6,
  COOL: 6,
  WILL: 6,
  LUCK: 6,
  MOVE: 6,
  BODY: 7,
  EMP: 7,
};

const DEFAULT_INSPECTOR: InspectorCard = {
  title: "Cyberpunk RED Sheet Studio",
  subtitle: "Beginner-Friendly Guide",
  body: "Hover over or click any Role, STAT, Skill, Lifepath trait, or Piece of Gear to see what it does in Night City without digging through the book.",
  mechanics: "Your finished character starts with a Role Ability (Rank 4), starting Hit Points, Humanity, Lifepath history, gear, and starting Eurobucks saved directly into your campaign.",
  tip: "New to Cyberpunk RED? Pick Streetrat (Templates) to jump in quickly, or roll your Lifepath for instant Night City drama!",
};

function d(sides: number): number {
  return Math.floor(Math.random() * sides) + 1;
}

function pickRandom<T>(list: readonly T[]): T {
  return list[Math.floor(Math.random() * list.length)];
}

function basicSkillRanks(skills: CreationSkillInfo[]): Record<string, number> {
  return Object.fromEntries(skills.filter((s) => s.basic).map((s) => [s.basic_skill_name || s.name, 2]));
}

/** The starter-kit pick for each entry: the fixed item, or the chosen (default first) option. */
function pickKit<T extends CreationKitItem>(
  section: string,
  entries: CreationKitEntry<T>[],
  choices: Record<string, string>,
): T[] {
  return entries.map((entry, idx) => {
    if (entry.type === "fixed") return entry;
    return entry.options.find((o) => o.item === choices[`${section}-${idx}`]) ?? entry.options[0];
  });
}

const itemKey = (name: string) => name.replace(/[^a-z0-9]/gi, "").toLowerCase();

function skillBaseCost(skillName: string, skillIndex: Map<string, CreationSkillInfo>): number {
  const clean = skillName.trim();
  const direct = skillIndex.get(clean.toLowerCase());
  if (direct) return direct.cost;
  const base = clean.split("(", 1)[0].trim().toLowerCase();
  return skillIndex.get(base)?.cost ?? 1;
}

function skillStat(skillName: string, skillIndex: Map<string, CreationSkillInfo>): StatName {
  const clean = skillName.trim();
  const direct = skillIndex.get(clean.toLowerCase());
  if (direct) return direct.stat;
  const base = clean.split("(", 1)[0].trim().toLowerCase();
  return skillIndex.get(base)?.stat ?? "INT";
}

function defaultCompleteSkills(
  roleInfo: CreationRoleInfo | undefined,
  skills: CreationSkillInfo[],
): Record<string, number> {
  const out = basicSkillRanks(skills);
  // Spend what the Basic Skills leave of 86 on the role's single-cost skills.
  const cheap = new Set(skills.filter((s) => s.cost === 1 && !s.basic).map((s) => s.name));
  const focus = Object.keys(roleInfo?.skills ?? {}).filter((k) => cheap.has(k));
  let budget = 86 - Object.values(out).reduce((a, b) => a + b, 0);
  for (const name of focus) {
    if (budget <= 0) break;
    const add = Math.min(6, budget);
    out[name] = add;
    budget -= add;
  }
  while (budget > 0) {
    let progressed = false;
    for (const k of Object.keys(out)) {
      if (out[k] < 6 && budget > 0) {
        out[k] += 1;
        budget -= 1;
        progressed = true;
      }
    }
    if (!progressed) break;
  }
  return out;
}

export function CharacterCreatorModal({
  open,
  campaignId,
  soloRevision,
  onClose,
  onCreated,
  onNotify,
}: CharacterCreatorModalProps) {
  const [refData, setRefData] = useState<CreationReference | null>(null);
  const [loadingRef, setLoadingRef] = useState(false);
  const roleExtrasRef = useRef<HTMLDivElement | null>(null);
  const [step, setStep] = useState<CreatorStep>("identity");
  const [inspector, setInspector] = useState<InspectorCard>(DEFAULT_INSPECTOR);
  const [busy, setBusy] = useState(false);

  // Core Identity & Mode
  const [name, setName] = useState("");
  const [realName, setRealName] = useState("");
  const [realNameHidden, setRealNameHidden] = useState(true);
  const [portraitUrl, setPortraitUrl] = useState("");
  const [characterColor, setCharacterColor] = useState("cyan");
  const [gender, setGender] = useState("");
  const [pronouns, setPronouns] = useState("");
  const [age, setAge] = useState("");
  const [conceptTagline, setConceptTagline] = useState("");
  const [method, setMethod] = useState<CreationMethodInfo["id"]>("streetrat");
  const [selectedRole, setSelectedRole] = useState("Solo");

  // Role-specific mechanical choices
  const [techMakerRanks, setTechMakerRanks] = useState<Record<string, number>>({
    "Field Expertise": 2,
    "Upgrade Expertise": 2,
    "Fabrication Expertise": 2,
    "Invention Expertise": 2,
  });
  const [medtechAlloc, setMedtechAlloc] = useState<Record<string, number>>({
    Surgery: 2,
    Pharmaceuticals: 1,
    "Cryosystem Operation": 1,
  });
  const [medtechRecipes, setMedtechRecipes] = useState<string[]>(["Speedheal"]);
  const [fixerCulture, setFixerCulture] = useState("Night City Street");
  const [fixerLanguage, setFixerLanguage] = useState("");
  const [nomadVehicles, setNomadVehicles] = useState<string[]>([]);
  const [execTeamName, setExecTeamName] = useState("Kaito Reyes");
  const [execTeamRole, setExecTeamRole] = useState("Bodyguard");
  const [execTeamLoyalty, setExecTeamLoyalty] = useState(4);
  const [housing, setHousing] = useState("Cargo Container");
  const [lifestyle, setLifestyle] = useState("Kibble");
  const [traumaTeam, setTraumaTeam] = useState<"None" | "Silver" | "Executive">("None");

  // STATs & template dice
  const [streetratRoll, setStreetratRoll] = useState<number>(1);
  const [edgerunnerRolls, setEdgerunnerRolls] = useState<number[]>([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
  const [customStats, setCustomStats] = useState<Record<StatName, number>>({ ...FALLBACK_STATS });

  // Skills
  const [edgerunnerSkills, setEdgerunnerSkills] = useState<Record<string, number>>({});
  const [customSkills, setCustomSkills] = useState<Record<string, number>>({});
  const [specializations, setSpecializations] = useState<Record<string, string>>({});
  const [skillFilter, setSkillFilter] = useState("");
  const [skillGroupFilter, setSkillGroupFilter] = useState<string>("All");
  const [specBasePick, setSpecBasePick] = useState<(typeof SPECIALIZATION_BASES)[number]>("Language");
  const [specFocusInput, setSpecFocusInput] = useState("");

  // Lifepath, Backstory & Established History
  const [culturalRegion, setCulturalRegion] = useState("");
  const [culturalLanguage, setCulturalLanguage] = useState("");
  const [personality, setPersonality] = useState("");
  const [clothingStyle, setClothingStyle] = useState("");
  const [hairstyle, setHairstyle] = useState("");
  const [affectation, setAffectation] = useState("");
  const [valueMost, setValueMost] = useState("");
  const [feelingsAboutPeople, setFeelingsAboutPeople] = useState("");
  const [valuedPerson, setValuedPerson] = useState("");
  const [valuedPossession, setValuedPossession] = useState("");
  const [familyBackground, setFamilyBackground] = useState("");
  const [childhoodEnv, setChildhoodEnv] = useState("");
  const [familyCrisis, setFamilyCrisis] = useState("");
  const [lifeGoal, setLifeGoal] = useState("");
  const [roleLifepath, setRoleLifepath] = useState<Record<string, string>>({});
  const [friends, setFriends] = useState<FriendEntry[]>([]);
  const [enemies, setEnemies] = useState<EnemyEntry[]>([]);
  const [loveAffairs, setLoveAffairs] = useState<LoveEntry[]>([]);
  const [backstorySummary, setBackstorySummary] = useState("");
  const [establishedHistory, setEstablishedHistory] = useState("");
  const [appearanceNotes, setAppearanceNotes] = useState("");
  const [reputation, setReputation] = useState(0);
  const [reputationNote, setReputationNote] = useState("");
  const [traumaHook, setTraumaHook] = useState("");
  const [addictionHook, setAddictionHook] = useState("");
  const [debtHook, setDebtHook] = useState("");
  const [showRepHooks, setShowRepHooks] = useState(true);
  const [customLifepathFields, setCustomLifepathFields] = useState<Record<string, boolean>>({});
  const [ammoCaliber, setAmmoCaliber] = useState("");
  const [aiBioGuidance, setAiBioGuidance] = useState("");
  const [aiContactsGuidance, setAiContactsGuidance] = useState("");
  const [aiBusyKey, setAiBusyKey] = useState<string | null>(null);
  const [aiError, setAiError] = useState("");

  // Gear, Cyberware, Fashion
  const [kitChoices, setKitChoices] = useState<Record<string, string>>({});
  const [shopCategory, setShopCategory] = useState<
    "weapon" | "armor" | "cyberware" | "gear" | "program" | "hardware" | "vehicle" | "drug" | "fashion"
  >("weapon");
  const [weaponGenres, setWeaponGenres] = useState<WeaponGenre[]>([]);
  const [weaponTiers, setWeaponTiers] = useState<WeaponTierFilter[]>([]);
  const [armorSubFilter, setArmorSubFilter] = useState<"all" | "body" | "head" | "shield">("all");
  const [cyberwareSubFilter, setCyberwareSubFilter] = useState<
    "all" | "foundation" | "neural" | "cyberoptic" | "cyberaudio" | "cyberlimb" | "body" | "fashionware"
  >("all");
  const [programSubFilter, setProgramSubFilter] = useState<"all" | "booster" | "defender" | "attacker" | "black_ice">("all");
  const [fashionStyleFilter, setFashionStyleFilter] = useState<string>("All");
  const [shopSort, setShopSort] = useState<"cost_asc" | "cost_desc" | "name_asc" | "sp_desc" | "hl_asc" | "tier_asc" | "tier_desc">("cost_asc");
  const [affordableOnly, setAffordableOnly] = useState(false);
  const [selectedOnly, setSelectedOnly] = useState(false);
  const [loadoutOpen, setLoadoutOpen] = useState(false);
  const [inspectedItemId, setInspectedItemId] = useState<string | null>(null);
  const [shopSearch, setShopSearch] = useState("");
  const [cartItems, setCartItems] = useState<Array<{ name: string; category: string; cost_eb: number; hl?: number; sp?: number; location?: string; install?: string; notes?: string; qty: number }>>([]);
  const [selectedFashion, setSelectedFashion] = useState<Array<{ name: string; cost_eb: number; style: string }>>([]);
  const [resetCount, setResetCount] = useState(0);
  const [draftRestored, setDraftRestored] = useState(false);

  const draftKey = `character:${campaignId}`;
  const hydratedRef = useRef(false);
  const hadSavedDraftRef = useRef(false);
  const prevRoleRef = useRef<string | null>(null);
  const skipNextRoleResetRef = useRef(false);

  const handlePortraitUpload = (file: File | undefined) => {
    if (!file) return;
    if (file.size > 2.5 * 1024 * 1024) {
      onNotify("Portrait image must be under 2.5 MB.");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") {
        setPortraitUrl(reader.result);
      }
    };
    reader.readAsDataURL(file);
  };

  const resetCharacterDefaults = () => {
    setGender("");
    setPronouns("");
    setStep("identity");
    setName("");
    setRealName("");
    setRealNameHidden(true);
    setPortraitUrl("");
    setCharacterColor("cyan");
    setPronouns("");
    setAge("");
    setConceptTagline("");
    setMethod("streetrat");
    setSelectedRole("Solo");
    setTechMakerRanks({
      "Field Expertise": 2,
      "Upgrade Expertise": 2,
      "Fabrication Expertise": 2,
      "Invention Expertise": 2,
    });
    setMedtechAlloc({ Surgery: 2, Pharmaceuticals: 1, "Cryosystem Operation": 1 });
    setMedtechRecipes(["Speedheal"]);
    setFixerCulture("Night City Street");
    setFixerLanguage("");
    setNomadVehicles([]);
    setExecTeamName("Kaito Reyes");
    setExecTeamRole("Bodyguard");
    setExecTeamLoyalty(4);
    setHousing("Cargo Container");
    setLifestyle("Kibble");
    setTraumaTeam("None");
    setFashionStyleFilter("All");
    setStreetratRoll(1);
    setEdgerunnerRolls([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
    setCustomStats({ ...FALLBACK_STATS });
    setEdgerunnerSkills(roleInfo && Object.keys(roleInfo.skills).length === 20 ? { ...roleInfo.skills } : {});
    setCustomSkills({});
    setSpecializations({});
    setCulturalRegion("");
    setCulturalLanguage("");
    setPersonality("");
    setClothingStyle("");
    setHairstyle("");
    setAffectation("");
    setValueMost("");
    setFeelingsAboutPeople("");
    setValuedPerson("");
    setValuedPossession("");
    setFamilyBackground("");
    setChildhoodEnv("");
    setFamilyCrisis("");
    setLifeGoal("");
    setRoleLifepath({});
    setFriends([]);
    setEnemies([]);
    setLoveAffairs([]);
    setBackstorySummary("");
    setEstablishedHistory("");
    setAppearanceNotes("");
    setReputation(0);
    setReputationNote("");
    setTraumaHook("");
    setAddictionHook("");
    setDebtHook("");
    setCustomLifepathFields({});
    setAmmoCaliber("");
    setAiBioGuidance("");
    setAiContactsGuidance("");
    setKitChoices({});
    setCartItems([]);
    setSelectedFashion([]);
    setDraftRestored(false);
    setResetCount((n) => n + 1);
    prevRoleRef.current = null;
  };

  useEffect(() => {
    if (!open) {
      hydratedRef.current = false;
      hadSavedDraftRef.current = false;
      setShowRepHooks(true);
      setCustomLifepathFields({});
      setLoadoutOpen(false);
      setInspectedItemId(null);
      setAiError("");
      setInspector(DEFAULT_INSPECTOR);
      return;
    }
    const saved = loadDraft<Record<string, unknown>>(draftKey);
    hadSavedDraftRef.current = Boolean(saved);
    if (saved) {
      skipNextRoleResetRef.current = true;
      if (typeof saved.step === "string") setStep(saved.step as CreatorStep);
      if (typeof saved.name === "string") setName(saved.name);
      if (typeof saved.realName === "string") setRealName(saved.realName);
      if (typeof saved.realNameHidden === "boolean") setRealNameHidden(saved.realNameHidden);
      if (typeof saved.portraitUrl === "string") setPortraitUrl(saved.portraitUrl);
      if (typeof saved.characterColor === "string") setCharacterColor(saved.characterColor);
      if (typeof saved.gender === "string") setGender(saved.gender);
      if (typeof saved.pronouns === "string") setPronouns(saved.pronouns);
      if (typeof saved.age === "string") setAge(saved.age);
      if (typeof saved.conceptTagline === "string") setConceptTagline(saved.conceptTagline);
      if (typeof saved.method === "string") setMethod(saved.method as typeof method);
      if (typeof saved.selectedRole === "string") {
        setSelectedRole(saved.selectedRole);
        prevRoleRef.current = saved.selectedRole;
      }
      if (saved.techMakerRanks && typeof saved.techMakerRanks === "object") setTechMakerRanks(saved.techMakerRanks as Record<string, number>);
      if (saved.medtechAlloc && typeof saved.medtechAlloc === "object") setMedtechAlloc(saved.medtechAlloc as Record<string, number>);
      if (Array.isArray(saved.medtechRecipes)) setMedtechRecipes(saved.medtechRecipes as string[]);
      if (typeof saved.fixerCulture === "string") setFixerCulture(saved.fixerCulture);
      if (typeof saved.fixerLanguage === "string") setFixerLanguage(saved.fixerLanguage);
      if (Array.isArray(saved.nomadVehicles)) setNomadVehicles(saved.nomadVehicles as string[]);
      if (typeof saved.execTeamName === "string") setExecTeamName(saved.execTeamName);
      if (typeof saved.execTeamRole === "string") setExecTeamRole(saved.execTeamRole);
      if (typeof saved.execTeamLoyalty === "number") setExecTeamLoyalty(saved.execTeamLoyalty);
      if (typeof saved.housing === "string") setHousing(saved.housing);
      if (typeof saved.lifestyle === "string") setLifestyle(saved.lifestyle);
      if (saved.traumaTeam === "None" || saved.traumaTeam === "Silver" || saved.traumaTeam === "Executive") setTraumaTeam(saved.traumaTeam);
      if (typeof saved.streetratRoll === "number") setStreetratRoll(saved.streetratRoll);
      if (Array.isArray(saved.edgerunnerRolls)) setEdgerunnerRolls(saved.edgerunnerRolls as number[]);
      if (saved.customStats && typeof saved.customStats === "object") setCustomStats(saved.customStats as Record<StatName, number>);
      if (saved.edgerunnerSkills && typeof saved.edgerunnerSkills === "object") setEdgerunnerSkills(saved.edgerunnerSkills as Record<string, number>);
      if (saved.customSkills && typeof saved.customSkills === "object") setCustomSkills(saved.customSkills as Record<string, number>);
      if (saved.specializations && typeof saved.specializations === "object") setSpecializations(saved.specializations as Record<string, string>);
      if (typeof saved.culturalRegion === "string") setCulturalRegion(saved.culturalRegion);
      if (typeof saved.culturalLanguage === "string") setCulturalLanguage(saved.culturalLanguage);
      if (typeof saved.personality === "string") setPersonality(saved.personality);
      if (typeof saved.clothingStyle === "string") setClothingStyle(saved.clothingStyle);
      if (typeof saved.hairstyle === "string") setHairstyle(saved.hairstyle);
      if (typeof saved.affectation === "string") setAffectation(saved.affectation);
      if (typeof saved.valueMost === "string") setValueMost(saved.valueMost);
      if (typeof saved.feelingsAboutPeople === "string") setFeelingsAboutPeople(saved.feelingsAboutPeople);
      if (typeof saved.valuedPerson === "string") setValuedPerson(saved.valuedPerson);
      if (typeof saved.valuedPossession === "string") setValuedPossession(saved.valuedPossession);
      if (typeof saved.familyBackground === "string") setFamilyBackground(saved.familyBackground);
      if (typeof saved.childhoodEnv === "string") setChildhoodEnv(saved.childhoodEnv);
      if (typeof saved.familyCrisis === "string") setFamilyCrisis(saved.familyCrisis);
      if (typeof saved.lifeGoal === "string") setLifeGoal(saved.lifeGoal);
      if (saved.roleLifepath && typeof saved.roleLifepath === "object") setRoleLifepath(saved.roleLifepath as Record<string, string>);
      if (Array.isArray(saved.friends)) setFriends(saved.friends as FriendEntry[]);
      if (Array.isArray(saved.enemies)) setEnemies(saved.enemies as EnemyEntry[]);
      if (Array.isArray(saved.loveAffairs)) setLoveAffairs(saved.loveAffairs as LoveEntry[]);
      if (typeof saved.backstorySummary === "string") setBackstorySummary(saved.backstorySummary);
      if (typeof saved.establishedHistory === "string") setEstablishedHistory(saved.establishedHistory);
      if (typeof saved.appearanceNotes === "string") setAppearanceNotes(saved.appearanceNotes);
      if (typeof saved.reputation === "number") setReputation(saved.reputation);
      if (typeof saved.reputationNote === "string") setReputationNote(saved.reputationNote);
      if (typeof saved.traumaHook === "string") setTraumaHook(saved.traumaHook);
      if (typeof saved.addictionHook === "string") setAddictionHook(saved.addictionHook);
      if (typeof saved.debtHook === "string") setDebtHook(saved.debtHook);
      if (typeof saved.aiBioGuidance === "string") setAiBioGuidance(saved.aiBioGuidance);
      if (typeof saved.aiContactsGuidance === "string") setAiContactsGuidance(saved.aiContactsGuidance);
      if (saved.kitChoices && typeof saved.kitChoices === "object") setKitChoices(saved.kitChoices as Record<string, string>);
      if (Array.isArray(saved.cartItems)) setCartItems(saved.cartItems as typeof cartItems);
      if (Array.isArray(saved.selectedFashion)) setSelectedFashion(saved.selectedFashion as typeof selectedFashion);
      setDraftRestored(true);
    } else {
      setDraftRestored(false);
    }
    hydratedRef.current = true;
  }, [open, draftKey]);

  useEffect(() => {
    if (!open || !hydratedRef.current) return;
    const hasContent = Boolean(
      name.trim() ||
        realName.trim() ||
        portraitUrl.trim() ||
        gender.trim() ||
        pronouns.trim() ||
        age.trim() ||
        conceptTagline.trim() ||
        backstorySummary.trim() ||
        establishedHistory.trim() ||
        appearanceNotes.trim() ||
        friends.length > 0 ||
        enemies.length > 0 ||
        loveAffairs.length > 0 ||
        cartItems.length > 0 ||
        selectedFashion.length > 0 ||
        selectedRole !== "Solo" ||
        method !== "streetrat" ||
        step !== "identity",
    );
    if (!hasContent) return;
    saveDraft(draftKey, {
      step,
      name,
      realName,
      realNameHidden,
      portraitUrl,
      characterColor,
      gender,
      pronouns,
      age,
      conceptTagline,
      method,
      selectedRole,
      techMakerRanks,
      medtechAlloc,
      medtechRecipes,
      fixerCulture,
      fixerLanguage,
      nomadVehicles,
      execTeamName,
      execTeamRole,
      execTeamLoyalty,
      housing,
      lifestyle,
      traumaTeam,
      streetratRoll,
      edgerunnerRolls,
      customStats,
      edgerunnerSkills,
      customSkills,
      specializations,
      culturalRegion,
      culturalLanguage,
      personality,
      clothingStyle,
      hairstyle,
      affectation,
      valueMost,
      feelingsAboutPeople,
      valuedPerson,
      valuedPossession,
      familyBackground,
      childhoodEnv,
      familyCrisis,
      lifeGoal,
      roleLifepath,
      friends,
      enemies,
      loveAffairs,
      backstorySummary,
      establishedHistory,
      appearanceNotes,
      reputation,
      reputationNote,
      traumaHook,
      addictionHook,
      debtHook,
      aiBioGuidance,
      aiContactsGuidance,
      kitChoices,
      cartItems,
      selectedFashion,
    });
  }, [
    open,
    draftKey,
    step,
    name,
    realName,
    realNameHidden,
    portraitUrl,
    characterColor,
    gender,
    pronouns,
    age,
    conceptTagline,
    method,
    selectedRole,
    techMakerRanks,
    medtechAlloc,
    medtechRecipes,
    fixerCulture,
    fixerLanguage,
    nomadVehicles,
    execTeamName,
    execTeamRole,
    execTeamLoyalty,
    housing,
    lifestyle,
    traumaTeam,
    streetratRoll,
    edgerunnerRolls,
    customStats,
    edgerunnerSkills,
    customSkills,
    specializations,
    culturalRegion,
    culturalLanguage,
    personality,
    clothingStyle,
    hairstyle,
    affectation,
    valueMost,
    feelingsAboutPeople,
    valuedPerson,
    valuedPossession,
    familyBackground,
    childhoodEnv,
    familyCrisis,
    lifeGoal,
    roleLifepath,
    friends,
    enemies,
    loveAffairs,
    backstorySummary,
    establishedHistory,
    appearanceNotes,
    reputation,
    reputationNote,
    traumaHook,
    addictionHook,
    debtHook,
    aiBioGuidance,
    aiContactsGuidance,
    kitChoices,
    cartItems,
    selectedFashion,
  ]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoadingRef(true);
    fetchCreationReference()
      .then((data) => {
        if (cancelled) return;
        setRefData(data);
      })
      .catch((err) => {
        if (!cancelled) onNotify(err instanceof Error ? err.message : "Failed to load Corebook creation data");
      })
      .finally(() => {
        if (!cancelled) setLoadingRef(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  const roleInfo: CreationRoleInfo | undefined = useMemo(
    () => refData?.roles.find((r) => r.name === selectedRole) ?? refData?.roles[0],
    [refData, selectedRole],
  );

  const skillIndex = useMemo(() => {
    const map = new Map<string, CreationSkillInfo>();
    for (const s of refData?.skills ?? []) {
      map.set(s.name.toLowerCase(), s);
    }
    return map;
  }, [refData]);

  // Fill every unset choice with the Corebook's first option.
  useEffect(() => {
    if (!refData) return;
    const tables = refData.lifepath_tables;
    const region = refData.cultural_regions[0];
    const fill = (set: (fn: (v: string) => string) => void, value: string | undefined) => set((v) => v || value || "");
    fill(setCulturalRegion, region?.region);
    fill(setCulturalLanguage, region?.languages[0]);
    fill(setFixerLanguage, region?.languages[0]);
    fill(setPersonality, tables.personality?.[0]);
    fill(setClothingStyle, tables.clothing_style?.[0]);
    fill(setHairstyle, tables.hairstyle?.[0]);
    fill(setAffectation, tables.affectation?.[0]);
    fill(setValueMost, tables.value_most?.[0]);
    fill(setFeelingsAboutPeople, tables.feelings_about_people?.[0]);
    fill(setValuedPerson, tables.valued_person?.[0]);
    fill(setValuedPossession, tables.valued_possession?.[0]);
    fill(setFamilyBackground, tables.family_background?.[0]);
    fill(setChildhoodEnv, tables.childhood_environment?.[0]);
    fill(setFamilyCrisis, tables.family_crisis?.[0]);
    fill(setLifeGoal, tables.life_goal?.[0]);
    setCustomSkills((v) => (Object.keys(v).length ? v : basicSkillRanks(refData.skills)));
    setSpecializations((v) => ({
      Language: region?.languages[0] ?? "",
      "Local Expert": refData.campaign_presets.districts[0]?.name ?? "",
      "Martial Arts": refData.martial_arts_forms[0] ?? "",
      ...v,
    }));
    setNomadVehicles((v) =>
      v.length
        ? v
        : [
            ...refData.nomad_vehicles.slice(0, 2),
            ...refData.nomad_upgrades.filter((u) => u.rank <= 1).slice(0, 2).map((u) => u.name),
          ],
    );
  }, [refData, resetCount]);

  // Initialize Role-dependent defaults cleanly when Role changes (preserving restored drafts)
  useEffect(() => {
    if (!roleInfo || !refData) return;
    const roleChanged = prevRoleRef.current !== null && prevRoleRef.current !== selectedRole;
    prevRoleRef.current = selectedRole;
    if (skipNextRoleResetRef.current && !roleChanged) {
      skipNextRoleResetRef.current = false;
      return;
    }
    if (roleChanged || Object.keys(edgerunnerSkills).length === 0) {
      if (Object.keys(roleInfo.skills).length === 20) {
        setEdgerunnerSkills({ ...roleInfo.skills });
      }
      if (method === "complete_package") {
        setCustomStats({ ...roleInfo.smart_fill });
        setCustomSkills(defaultCompleteSkills(roleInfo, refData.skills));
      }
    }
    if (roleChanged) setKitChoices({});
    if (roleChanged || Object.keys(roleLifepath).length === 0) {
      const nextRoleLp: Record<string, string> = {};
      for (const f of roleInfo.role_lifepath) {
        nextRoleLp[f.key] = f.options[0] ?? "";
      }
      setRoleLifepath(nextRoleLp);
    }
    if (roleChanged) {
      if (selectedRole === "Exec") {
        if (housing === "Cargo Container") setHousing("Corporate Conapt");
        if (traumaTeam === "None") setTraumaTeam("Silver");
      } else if (housing.startsWith("Corporate")) {
        setHousing("Cargo Container");
      }
    }
  }, [selectedRole, roleInfo?.name]);

  // Compute active STAT block
  const activeStats: Record<StatName, number> = useMemo(() => {
    const templates = roleInfo?.templates ?? [];
    if (method === "streetrat" && templates.length === 10) {
      const row = templates[Math.max(0, Math.min(9, streetratRoll - 1))];
      return Object.fromEntries(STAT_NAMES.map((s, i) => [s, row[i]])) as Record<StatName, number>;
    }
    if (method === "edgerunner" && templates.length === 10) {
      return Object.fromEntries(
        STAT_NAMES.map((s, i) => {
          const r = Math.max(0, Math.min(9, (edgerunnerRolls[i] ?? 1) - 1));
          return [s, templates[r][i]];
        }),
      ) as Record<StatName, number>;
    }
    return customStats;
  }, [method, roleInfo, streetratRoll, edgerunnerRolls, customStats]);

  // Compute active Skills map (with specialization + Cultural Language preview)
  const effectiveSkills: Record<string, number> = useMemo(() => {
    let base: Record<string, number> = {};
    if (method === "streetrat" && roleInfo && Object.keys(roleInfo.skills).length > 0) {
      base = { ...roleInfo.skills };
    } else if (method === "edgerunner") {
      base = { ...edgerunnerSkills };
    } else {
      base = { ...customSkills };
    }
    const resolved: Record<string, number> = {};
    for (const [k, v] of Object.entries(base)) {
      if (v <= 0) continue;
      if (k.includes("(choose 1)")) {
        const prefix = k.replace(/\s*\(choose 1\)\s*/i, "").trim();
        const chosen = specializations[prefix]?.trim() || "Specialty";
        resolved[`${prefix} (${chosen})`] = v;
      } else {
        resolved[k] = v;
      }
    }
    const lang = culturalLanguage.trim();
    if (lang && lang.toLowerCase() !== "streetslang") {
      const langKey = `Language (${lang})`;
      if (!(langKey in resolved)) {
        resolved[langKey] = 4;
      }
    }
    if (selectedRole === "Medtech") {
      const surg = (medtechAlloc.Surgery ?? 0) * 2;
      const mtech = (medtechAlloc.Pharmaceuticals ?? 0) + (medtechAlloc["Cryosystem Operation"] ?? 0);
      if (surg > 0) resolved["Surgery"] = Math.max(resolved["Surgery"] ?? 0, surg);
      if (mtech > 0) resolved["Medical Tech"] = Math.max(resolved["Medical Tech"] ?? 0, mtech);
    }
    return resolved;
  }, [method, roleInfo, edgerunnerSkills, customSkills, specializations, culturalLanguage, selectedRole, medtechAlloc]);

  // Point-buy budgets
  const statSum = useMemo(() => Object.values(activeStats).reduce((a, b) => a + b, 0), [activeStats]);
  const skillPointsSpent = useMemo(() => {
    const raw = method === "edgerunner" ? edgerunnerSkills : method === "complete_package" ? customSkills : {};
    return Object.entries(raw).reduce((sum, [k, v]) => sum + v * skillBaseCost(k, skillIndex), 0);
  }, [method, edgerunnerSkills, customSkills, skillIndex]);

  const missingBasicSkills = useMemo(() => {
    if (method !== "complete_package") return [];
    const entries = Object.entries(customSkills);
    const missing: string[] = [];
    for (const req of Object.keys(basicSkillRanks(refData?.skills ?? []))) {
      if (req === "Language (Streetslang)" || req === "Local Expert (Your Home)") {
        const prefix = req.split("(", 1)[0].trim().toLowerCase();
        const ok = entries.some(
          ([k, v]) => (k.toLowerCase() === req.toLowerCase() || k.toLowerCase().startsWith(`${prefix} (`)) && v >= 2,
        );
        if (!ok) missing.push(req);
      } else if ((customSkills[req] ?? 0) < 2) {
        missing.push(req);
      }
    }
    return missing;
  }, [method, customSkills, refData]);

  // Starting Gear & Humanity preview
  const gearSummary = useMemo(() => {
    const inventory: Record<string, number> = {};
    const cyberware: Array<{ name: string; hl: number; install?: string; notes?: string; cost_eb?: number }> = [];
    let equippedWeapon: string | undefined;
    let equippedArmor: { name: string; sp: number } | undefined;
    let equippedHeadArmor: { name: string; sp: number } | undefined;
    let money = 500;
    let fashionSpent = 0;
    let spent = 0;

    const parseSp = (label: string) => Number(label.match(/SP\s*(\d+)/i)?.[1] ?? 0);

    if (method !== "complete_package") {
      if (roleInfo) {
        for (const w of pickKit("weapons", roleInfo.starting_weapons, kitChoices)) {
          inventory[w.item] = (inventory[w.item] ?? 0) + w.qty;
          if (!equippedWeapon && !/ammunition|grenade|shield/i.test(w.item)) {
            equippedWeapon = w.item;
          }
        }
        for (const a of roleInfo.starting_armor) {
          inventory[a] = (inventory[a] ?? 0) + 1;
          if (/head|helmet|cowl/i.test(a)) {
            const sp = parseSp(a);
            if (!equippedHeadArmor || sp > equippedHeadArmor.sp) {
              equippedHeadArmor = { name: a, sp };
            }
          } else if (!/shield/i.test(a) && (!equippedArmor || /Body/i.test(a))) {
            equippedArmor = { name: a, sp: parseSp(a) };
          }
        }
        for (const o of pickKit("outfit", roleInfo.starting_outfit, kitChoices)) {
          inventory[o.item] = (inventory[o.item] ?? 0) + o.qty;
        }
        for (const cw of pickKit<CreationKitCyberware>("cyberware", roleInfo.starting_cyberware, kitChoices)) {
          cyberware.push({ name: cw.item, hl: cw.hl, install: cw.install, notes: cw.notes });
        }
      }
    } else {
      for (const item of cartItems) {
        if (item.category === "cyberware") {
          for (let q = 0; q < item.qty; q += 1) {
            cyberware.push({
              name: item.name,
              hl: item.hl ?? 0,
              install: item.install,
              cost_eb: item.cost_eb,
              notes: item.notes,
            });
          }
        } else {
          inventory[item.name] = (inventory[item.name] ?? 0) + item.qty;
          const isAttachmentOrAmmo = /ammo|magazine|drum|slug|shell|grenade|arrow|sight|mount|suppressor|smartgun link|bayonet/i.test(item.name);
          if (!equippedWeapon && item.category === "weapon" && !isAttachmentOrAmmo) {
            equippedWeapon = item.name;
          }
          if (item.category === "armor") {
            const loc = (item.location ?? "").toLowerCase();
            const isShield = loc === "shield" || /shield/i.test(item.name);
            const isHead = loc.includes("head") || /head|helmet|cowl|bodyweight/i.test(item.name);
            const isBody = !loc || loc.includes("body") || (!isHead && !isShield);
            const itemSp = typeof item.sp === "number" && item.sp > 0 ? item.sp : parseSp(item.name);
            if (!isShield && isHead) {
              if (!equippedHeadArmor || itemSp > equippedHeadArmor.sp) {
                equippedHeadArmor = { name: item.name, sp: itemSp };
              }
            }
            if (!isShield && isBody) {
              if (!equippedArmor || itemSp > equippedArmor.sp) {
                equippedArmor = { name: item.name, sp: itemSp };
              }
            }
          }
        }
        spent += item.cost_eb * item.qty;
      }
      for (const f of selectedFashion) {
        inventory[f.name] = (inventory[f.name] ?? 0) + 1;
        fashionSpent += f.cost_eb;
      }
      money = Math.max(0, 2550 - spent);
    }

    const itemHl = cyberware.reduce((acc, c) => acc + (Number.isFinite(c.hl) ? c.hl : 0), 0);
    // The Corebook prints each starter kit's total Humanity Loss.
    const totalHl = method === "complete_package" ? itemHl : (roleInfo?.starting_hl ?? itemHl);
    return {
      inventory,
      cyberware,
      equippedWeapon,
      equippedArmor,
      equippedHeadArmor,
      money,
      fashionSpent,
      spentEb: method === "complete_package" ? spent : 0,
      totalHl,
    };
  }, [method, roleInfo, kitChoices, cartItems, selectedFashion]);

  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = {
      weapon: 0,
      armor: 0,
      cyberware: 0,
      gear: 0,
      program: 0,
      hardware: 0,
      vehicle: 0,
      drug: 0,
      fashion: selectedFashion.length,
    };
    for (const it of cartItems) {
      const bucket = it.category === "attachment" || it.category === "ammo" ? "weapon" : it.category;
      if (bucket in counts) counts[bucket] += it.qty;
    }
    return counts;
  }, [cartItems, selectedFashion]);

  const { effectiveBody, subdermalSp, subdermalName } = useMemo(() => {
    const graftedCount = gearSummary.cyberware.filter((c) => /grafted muscle/i.test(c.name)).length;
    let body = graftedCount > 0 ? Math.min(10, activeStats.BODY + 2 * graftedCount) : activeStats.BODY;
    let sp = 0;
    let armorName = "";
    for (const cw of gearSummary.cyberware) {
      const low = cw.name.toLowerCase();
      if (/linear frame.*(beta|β)/i.test(low)) body = Math.max(body, 14);
      else if (/linear frame.*(sigma|σ)/i.test(low)) body = Math.max(body, 12);
      if (low.includes("subdermal armor") && sp < 11) {
        sp = 11;
        armorName = "Subdermal Armor";
      } else if (/skin\s*weave/i.test(low) && sp < 7) {
        sp = 7;
        armorName = "Skinweave";
      }
    }
    return { effectiveBody: body, subdermalSp: sp, subdermalName: armorName };
  }, [gearSummary.cyberware, activeStats.BODY]);

  const maxHp = 10 + 5 * Math.ceil((effectiveBody + activeStats.WILL) / 2);
  const woundThreshold = Math.ceil(maxHp / 2);
  const deathSave = effectiveBody;
  const maxHumanity = activeStats.EMP * 10;
  const startingHumanity = Math.max(0, maxHumanity - gearSummary.totalHl);
  const effectiveEmp = Math.floor(startingHumanity / 10);

  const culturalLanguageOverlap = useMemo(() => {
    const lang = culturalLanguage.trim();
    if (!lang) return false;
    const raw =
      method === "edgerunner"
        ? edgerunnerSkills
        : method === "complete_package"
          ? customSkills
          : roleInfo?.skills ?? {};
    const target = `language (${lang.toLowerCase()})`;
    return Object.keys(raw).some((k) => k.toLowerCase() === target);
  }, [culturalLanguage, method, edgerunnerSkills, customSkills, roleInfo]);

  const cyberwareIndex = useMemo(
    () => new Map((refData?.shop.cyberware ?? []).map((c) => [itemKey(c.name), c])),
    [refData],
  );

  /** The foundation(s) an option needs, as the Corebook states them; empty for standalone cyberware. */
  const foundationsOf = (item: CreationShopItem): string[] => {
    const stated = item.description.match(/^(Cyberarm|Cyberleg) Option/)?.[1];
    const all = String(item.stats.foundation ?? "").split(" or ").filter(Boolean);
    if (all.includes(item.name)) return [];
    return stated ? [stated] : all;
  };

  const cyberwarePrereqWarnings = useMemo(() => {
    const owned = new Set(gearSummary.cyberware.map((c) => itemKey(c.name)));
    const warnings: Array<{ option: string; foundation: CreationShopItem }> = [];
    for (const cw of gearSummary.cyberware) {
      const item = cyberwareIndex.get(itemKey(cw.name));
      const needed = item ? foundationsOf(item) : [];
      if (!needed.length || needed.some((f) => owned.has(itemKey(f)))) continue;
      const foundation = cyberwareIndex.get(itemKey(needed[0]));
      if (foundation && !warnings.some((w) => w.foundation.id === foundation.id)) {
        warnings.push({ option: cw.name, foundation });
      }
    }
    return warnings;
  }, [gearSummary.cyberware, cyberwareIndex]);

  const cyberdeckSlotSummary = useMemo(() => {
    const hardware = new Map((refData?.shop.hardware ?? []).map((h) => [itemKey(h.name), h]));
    const programs = new Map((refData?.shop.program ?? []).map((p) => [itemKey(p.name), p]));
    const deckSlots = (name: string) => {
      const slots = hardware.get(itemKey(name))?.stats.slots;
      if (typeof slots === "number") return slots;
      return Number(name.match(/(\d+)\s*slots?/i)?.[1] ?? 0);
    };
    const ownedNames = [...Object.keys(gearSummary.inventory), ...gearSummary.cyberware.map((c) => c.name)];
    const capacities = ownedNames.filter((n) => /cyberdeck/i.test(n)).map(deckSlots);
    let capacity = Math.max(0, ...capacities);
    const hasDeck = capacities.length > 0;
    const hasBodyweight = Object.keys(gearSummary.inventory).some((n) => /bodyweight suit/i.test(n));
    if (capacity > 0 && hasBodyweight) capacity += 1;

    let usedSlots = 0;
    for (const item of cartItems) {
      if (item.category === "program") {
        const isIce = String(programs.get(itemKey(item.name))?.stats.class ?? "").includes("Black ICE");
        usedSlots += (isIce ? 2 : 1) * item.qty;
      } else if (item.category === "hardware" && !/cyberdeck/i.test(item.name)) {
        const text = hardware.get(itemKey(item.name))?.description ?? "";
        usedSlots += Number(text.match(/(\d+)\s*(?:Program\/Hardware )?Slots/i)?.[1] ?? 1) * item.qty;
      }
    }
    return { hasDeck, capacity, usedSlots, overCapacity: capacity > 0 && usedSlots > capacity };
  }, [cartItems, gearSummary.cyberware, gearSummary.inventory, refData]);

  // Option Slot caps, read from the Corebook's foundation and option descriptions
  const cyberwareSlotWarnings = useMemo(() => {
    const slotsTaken = (item: CreationShopItem) =>
      /doesn[’']t take up/i.test(item.description)
        ? 0
        : Number(item.description.match(/takes(?: up)? (\d+) (?:\w+ )?Option Slots?/i)?.[1] ?? 1);
    const used = new Map<string, { usedSlots: number; options: string[] }>();
    for (const cw of gearSummary.cyberware) {
      const item = cyberwareIndex.get(itemKey(cw.name));
      const foundation = item ? foundationsOf(item)[0] : undefined;
      if (!item || !foundation) continue;
      const entry = used.get(foundation) ?? { usedSlots: 0, options: [] };
      used.set(foundation, { usedSlots: entry.usedSlots + slotsTaken(item), options: [...entry.options, cw.name] });
    }
    return Array.from(used, ([foundation, entry]) => {
      const cap = Number(
        cyberwareIndex.get(itemKey(foundation))?.description.match(/(\d+) (?:\w+ )?Option Slots/i)?.[1] ?? 0,
      );
      const count = gearSummary.cyberware.filter((c) => itemKey(c.name) === itemKey(foundation)).length;
      return { foundation, maxSlots: Math.max(1, count) * cap, ...entry };
    }).filter((w) => w.maxSlots > 0 && w.usedSlots > w.maxSlots);
  }, [gearSummary.cyberware, cyberwareIndex]);

  // Validation checks
  const validationIssues = useMemo(() => {
    const issues: string[] = [];
    if (!name.trim() && !realName.trim()) issues.push("Enter a Handle / Name on Step 1 (Identity & Role).");
    if (!refData) issues.push("Corebook creation data has not loaded.");
    if (method === "complete_package") {
      if (statSum !== 62) {
        issues.push(`STAT total must equal 62 for Complete Package (currently ${statSum}).`);
      }
      if (skillPointsSpent !== 86) {
        issues.push(`Skill points must equal 86 for Complete Package (currently ${skillPointsSpent}).`);
      }
      if (missingBasicSkills.length > 0) {
        issues.push(`All 13 Basic Skills must be >= 2 (missing: ${missingBasicSkills.slice(0, 3).join(", ")}${missingBasicSkills.length > 3 ? "…" : ""}).`);
      }
      if (gearSummary.spentEb > 2550) {
        issues.push("Equipment spending exceeds the 2,550 eb Complete Package budget.");
      }
      if (gearSummary.fashionSpent > 800) {
        issues.push("Fashion spending exceeds the 800 eb Complete Package budget.");
      }
    }
    if (method === "edgerunner") {
      if (skillPointsSpent !== 86) {
        issues.push(`Role skill points must total 86 for Edgerunner (currently ${skillPointsSpent}).`);
      }
      if (Object.values(edgerunnerSkills).some((v) => v < 2 || v > 6)) {
        issues.push("All 20 Role Skills in Edgerunner must be between 2 and 6.");
      }
    }
    if (selectedRole === "Tech") {
      const sum = Object.values(techMakerRanks).reduce((a, b) => a + b, 0);
      if (sum !== 8) issues.push(`Tech Maker specialty points must total 8 (currently ${sum}).`);
    }
    if (selectedRole === "Medtech") {
      const sum = Object.values(medtechAlloc).reduce((a, b) => a + b, 0);
      if (sum !== 4) issues.push(`Medtech Medicine specialty points must total 4 (currently ${sum}).`);
    }
    return issues;
  }, [
    name,
    realName,
    method,
    refData,
    statSum,
    skillPointsSpent,
    missingBasicSkills,
    gearSummary,
    edgerunnerSkills,
    selectedRole,
    techMakerRanks,
    medtechAlloc,
  ]);

  const rollFullLifepath = () => {
    const tables = refData?.lifepath_tables;
    const regions = refData?.cultural_regions ?? [];
    if (regions.length > 0) {
      const reg = pickRandom(regions);
      setCulturalRegion(reg.region);
      setCulturalLanguage(pickRandom(reg.languages));
    }
    if (tables) {
      const p = pickRandom(tables.personality);
      const cs = pickRandom(tables.clothing_style);
      const hs = pickRandom(tables.hairstyle);
      const af = pickRandom(tables.affectation);
      const vm = pickRandom(tables.value_most);
      const fp = pickRandom(tables.feelings_about_people);
      const vp = pickRandom(tables.valued_person);
      const vpos = pickRandom(tables.valued_possession);
      const fb = pickRandom(tables.family_background);
      const ce = pickRandom(tables.childhood_environment);
      const fc = pickRandom(tables.family_crisis);
      const lg = pickRandom(tables.life_goal);
      setPersonality(p);
      setClothingStyle(cs);
      setHairstyle(hs);
      setAffectation(af);
      setValueMost(vm);
      setFeelingsAboutPeople(fp);
      setValuedPerson(vp);
      setValuedPossession(vpos);
      setFamilyBackground(fb);
      setChildhoodEnv(ce);
      setFamilyCrisis(fc);
      setLifeGoal(lg);

      const nextRoleLp: Record<string, string> = {};
      for (const f of roleInfo?.role_lifepath ?? []) {
        if (f.options.length) nextRoleLp[f.key] = pickRandom(f.options);
      }
      setRoleLifepath(nextRoleLp);
      setCustomLifepathFields({});

      const friendCount = Math.max(0, d(10) - 7);
      const nextFriends: FriendEntry[] = Array.from({ length: friendCount }, (_, idx) => ({
        name: `Contact #${idx + 1}`,
        relationship: pickRandom(tables.friend_relationship),
        note: "Reliable ally from before Session 1.",
      }));
      setFriends(nextFriends);

      const enemyCount = Math.max(0, d(10) - 7);
      const nextEnemies: EnemyEntry[] = Array.from({ length: enemyCount }, (_, idx) => ({
        who: pickRandom(tables.enemy_who),
        name: `Rival #${idx + 1}`,
        wronged: d(2) === 1 ? "I wronged them" : "They wronged me",
        cause: pickRandom(tables.enemy_cause),
        backup: pickRandom(tables.enemy_backup),
        revenge: pickRandom(tables.sweet_revenge),
      }));
      setEnemies(nextEnemies);

      const loveCount = Math.max(0, d(10) - 7);
      const nextLove: LoveEntry[] = Array.from({ length: loveCount }, (_, idx) => ({
        name: `Former Flame #${idx + 1}`,
        outcome: pickRandom(tables.tragic_love),
      }));
      setLoveAffairs(nextLove);

      weaveStarterBackstory({
        role: selectedRole,
        region: regLabel(regions, culturalRegion),
        family: fb,
        childhood: ce,
        crisis: fc,
        goal: lg,
        friendCount,
        enemyCount,
        loveCount,
      });
    }
  };

  function regLabel(regions: Array<{ region: string }>, cur: string): string {
    return regions.find((r) => r.region === cur)?.region ?? cur;
  }

  const weaveStarterBackstory = (override?: {
    role: string;
    region: string;
    family: string;
    childhood: string;
    crisis: string;
    goal: string;
    friendCount: number;
    enemyCount: number;
    loveCount: number;
  }) => {
    const r = override?.role ?? selectedRole;
    const reg = override?.region ?? culturalRegion;
    const fam = override?.family ?? familyBackground;
    const child = override?.childhood ?? childhoodEnv;
    const cris = override?.crisis ?? familyCrisis;
    const goal = override?.goal ?? lifeGoal;
    const fCnt = override?.friendCount ?? friends.length;
    const eCnt = override?.enemyCount ?? enemies.length;
    const lCnt = override?.loveCount ?? loveAffairs.length;

    const story = `Born into ${fam.split("(", 1)[0].trim()} roots (${reg}), you spent your youth ${child.toLowerCase()}. ${cris} Now running the streets as a ${r}, you're driven to ${goal.replace(/\.$/, "").toLowerCase()}.`;
    const histBits: string[] = [];
    if (fCnt > 0) histBits.push(`${fCnt} trusted contact${fCnt > 1 ? "s" : ""} on The Street`);
    if (eCnt > 0) histBits.push(`${eCnt} active grudge/enem${eCnt > 1 ? "ies" : "y"} waiting to resurface`);
    if (lCnt > 0) histBits.push(`${lCnt} messy past romance${lCnt > 1 ? "s" : ""}`);
    const roleBit = Object.values(roleLifepath).filter(Boolean).slice(0, 2).join("; ");
    const historyText = [
      roleBit ? `Established Role Pedigree: ${roleBit}.` : "",
      histBits.length ? `Pre-campaign ties: ${histBits.join(", ")}.` : "Traveling light in Night City without heavy debts—yet.",
    ]
      .filter(Boolean)
      .join(" ");

    setBackstorySummary(story);
    setEstablishedHistory(historyText);
    setAppearanceNotes(`${clothingStyle.split("(", 1)[0].trim()} style, ${hairstyle.toLowerCase()} hair, always wearing ${affectation.toLowerCase()}.`);
  };

  const aiBusy = aiBusyKey !== null;

  const handleAiAssist = async (
    target: "bio" | "contacts",
    assistMode: "scratch" | "expand",
    field?: string,
    entryIndex?: number,
    subField?: string,
  ) => {
    if (aiBusy) return;
    setAiError("");
    const busySuffix = entryIndex !== undefined && subField ? `${field ?? "all"}:${entryIndex}:${subField}` : (field ?? "all");
    setAiBusyKey(`${target}:${assistMode}:${busySuffix}`);
    try {
      const res = await assistCharacterCreation({
        target,
        mode: assistMode,
        ...(field ? { field } : {}),
        ...(entryIndex !== undefined ? { entry_index: entryIndex } : {}),
        ...(subField ? { sub_field: subField } : {}),
        guidance: (target === "bio" ? aiBioGuidance : aiContactsGuidance).trim() || undefined,
        character: {
          name: name.trim() || realName.trim() || "Unnamed Edgerunner",
          handle: name.trim() || undefined,
          real_name: realName.trim() || undefined,
          real_name_hidden: realNameHidden,
          gender: (gender === "__custom__" ? "" : gender.trim()) || undefined,
          pronouns: pronouns.trim() || undefined,
          age: age.trim() || undefined,
          role: selectedRole,
          method,
          stats: activeStats,
          skills: effectiveSkills,
          lifepath: {
            cultural_origin: culturalRegion,
            native_language: culturalLanguage,
            personality,
            clothing_style: clothingStyle,
            hairstyle,
            affectation,
            value_most: valueMost,
            feelings_about_people: feelingsAboutPeople,
            valued_person: valuedPerson,
            valued_possession: valuedPossession,
            family_background: familyBackground,
            childhood_environment: childhoodEnv,
            family_crisis: familyCrisis,
            life_goal: lifeGoal,
            role_lifepath: roleLifepath,
          },
          starting_gear: {
            equipped_weapon: gearSummary.equippedWeapon,
            equipped_armor: gearSummary.equippedArmor,
            cyberware: gearSummary.cyberware,
          },
        },
        current: {
          concept: conceptTagline.trim() || undefined,
          summary: backstorySummary.trim() || undefined,
          established_history: establishedHistory.trim() || undefined,
          appearance: appearanceNotes.trim() || undefined,
          reputation_note: reputationNote.trim() || undefined,
          trauma_hook: traumaHook.trim() || undefined,
          addiction_hook: addictionHook.trim() || undefined,
          debt_hook: debtHook.trim() || undefined,
          friends,
          enemies,
          tragic_love_affairs: loveAffairs,
        },
      });
      if (target === "bio") {
        if ((!field || field === "concept") && res.concept) setConceptTagline(res.concept);
        if ((!field || field === "summary") && res.summary) setBackstorySummary(res.summary);
        if ((!field || field === "established_history") && res.established_history) setEstablishedHistory(res.established_history);
        if ((!field || field === "appearance") && res.appearance) setAppearanceNotes(res.appearance);
        if ((!field || field === "reputation_note") && res.reputation_note) setReputationNote(res.reputation_note);
        if ((!field || field === "trauma_hook") && res.trauma_hook) setTraumaHook(res.trauma_hook);
        if ((!field || field === "addiction_hook") && res.addiction_hook) setAddictionHook(res.addiction_hook);
        if ((!field || field === "debt_hook") && res.debt_hook) setDebtHook(res.debt_hook);
        const label =
          field === "concept"
            ? "Concept"
            : field === "summary"
              ? "Backstory"
              : field === "established_history"
                ? "Established History"
                : field === "appearance"
                  ? "Signature Look"
                  : field
                    ? field.replace(/_/g, " ")
                    : "backstory & history";
        onNotify(assistMode === "scratch" ? `AI generated ${label}.` : `AI improved your ${label}.`);
      } else {
        if (entryIndex !== undefined && subField) {
          const val = res.value?.trim();
          if (val) {
            if (field === "friends") {
              setFriends((p) => p.map((x, i) => (i === entryIndex ? { ...x, [subField]: val } : x)));
            } else if (field === "enemies") {
              setEnemies((p) => p.map((x, i) => (i === entryIndex ? { ...x, [subField]: val } : x)));
            } else if (field === "tragic_love_affairs") {
              setLoveAffairs((p) => p.map((x, i) => (i === entryIndex ? { ...x, [subField]: val } : x)));
            }
            onNotify(assistMode === "scratch" ? `AI regenerated ${subField.replace(/_/g, " ")}.` : `AI improved ${subField.replace(/_/g, " ")}.`);
          } else {
            onNotify(`AI returned an empty value for ${subField.replace(/_/g, " ")}; existing text kept.`);
          }
        } else {
          const validFriends = (res.friends ?? []).filter((f) => f.name?.trim());
          if ((!field || field === "friends") && validFriends.length > 0) setFriends(validFriends);
          const validEnemies = (res.enemies ?? []).filter((e) => e.name?.trim() || e.who?.trim());
          if ((!field || field === "enemies") && validEnemies.length > 0) {
            setEnemies(
              validEnemies.map((e) => ({
                who: e.who,
                name: e.name,
                wronged: e.wronged === "I wronged them" ? "I wronged them" : "They wronged me",
                cause: e.cause,
                backup: e.backup,
                revenge: e.revenge,
              })),
            );
          }
          const validLoves = (res.tragic_love_affairs ?? []).filter((l) => l.name?.trim());
          if ((!field || field === "tragic_love_affairs") && validLoves.length > 0) {
            setLoveAffairs(validLoves);
          }
          onNotify(
            assistMode === "scratch"
              ? "AI generated Friends, Enemies & Past Romances."
              : `AI improved your ${field ? field.replace(/_/g, " ") : "Contacts"}.`,
          );
        }
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "AI assist failed";
      setAiError(msg);
      onNotify(msg);
    } finally {
      setAiBusyKey(null);
    }
  };

  const buildRoleChoicesPayload = (): Record<string, unknown> => {
    if (selectedRole === "Tech") {
      const flat: string[] = [];
      for (const [k, v] of Object.entries(techMakerRanks)) {
        for (let i = 0; i < v; i += 1) flat.push(k);
      }
      return { maker: flat };
    }
    if (selectedRole === "Medtech") {
      return {
        medicine: { ...medtechAlloc },
        recipes: medtechRecipes.slice(0, medtechAlloc.Pharmaceuticals ?? 0),
      };
    }
    if (selectedRole === "Fixer") {
      return { language: fixerLanguage || culturalLanguage || "Spanish", culture: fixerCulture || culturalRegion || "Night City Street" };
    }
    if (selectedRole === "Nomad") {
      return { moto: nomadVehicles.slice(0, 4) };
    }
    if (selectedRole === "Exec") {
      return {
        team_member: {
          name: execTeamName || "Kaito Reyes",
          role: execTeamRole || "Covert Operative",
          loyalty: execTeamLoyalty,
        },
      };
    }
    return {};
  };

  const handleSubmit = async () => {
    if (!(name.trim() || realName.trim()) || busy || validationIssues.length > 0) return;
    setBusy(true);
    try {
      const lifepathPayload = {
        cultural_origin: culturalRegion,
        native_language: culturalLanguage,
        personality,
        clothing_style: clothingStyle,
        hairstyle,
        affectation,
        value_most: valueMost,
        feelings_about_people: feelingsAboutPeople,
        valued_person: valuedPerson,
        valued_possession: valuedPossession,
        family_background: familyBackground,
        childhood_environment: childhoodEnv,
        family_crisis: familyCrisis,
        life_goal: lifeGoal,
        role_lifepath: roleLifepath,
        friends,
        enemies,
        tragic_love_affairs: loveAffairs,
      };
      const cleanGender = gender === "__custom__" ? "" : gender.trim();
      const startingHooksPayload =
        traumaHook.trim() || addictionHook.trim() || debtHook.trim()
          ? {
              ...(traumaHook.trim() ? { trauma: traumaHook.trim() } : {}),
              ...(addictionHook.trim() ? { addiction: addictionHook.trim() } : {}),
              ...(debtHook.trim() ? { debt: debtHook.trim() } : {}),
            }
          : undefined;
      const backstoryPayload = {
        gender: cleanGender || undefined,
        pronouns: pronouns.trim() || undefined,
        age: age.trim() || undefined,
        concept: conceptTagline.trim() || undefined,
        summary: backstorySummary.trim() || undefined,
        established_history: establishedHistory.trim() || undefined,
        appearance: appearanceNotes.trim() || undefined,
        ...(startingHooksPayload ? { starting_hooks: startingHooksPayload } : {}),
      };

      const primaryName = name.trim() || realName.trim();
      const handleVal = name.trim() || primaryName;
      const realNameVal = realName.trim() || undefined;
      const res = await createRulesPlayerCharacter(campaignId, soloRevision, {
        name: primaryName,
        handle: handleVal,
        real_name: realNameVal,
        real_name_hidden: realNameHidden,
        gender: cleanGender || undefined,
        pronouns: pronouns.trim() || undefined,
        portrait_url: portraitUrl.trim() || undefined,
        color: characterColor,
        role: selectedRole,
        method,
        ...(method === "streetrat" ? { template_rolls: [streetratRoll] } : {}),
        ...(method === "edgerunner" ? { template_rolls: edgerunnerRolls, skills: edgerunnerSkills } : {}),
        ...(method === "complete_package" ? { stats: customStats, skills: customSkills } : {}),
        specializations,
        role_choices: buildRoleChoicesPayload(),
        cultural_language: culturalLanguage.trim().toLowerCase() === "streetslang" ? undefined : culturalLanguage.trim() || undefined,
        housing,
        lifestyle,
        trauma_team: traumaTeam,
        reputation,
        ...(reputationNote.trim() ? { reputation_note: reputationNote.trim() } : {}),
        ...(startingHooksPayload ? { starting_hooks: startingHooksPayload } : {}),
        lifepath: lifepathPayload,
        backstory: backstoryPayload,
        starting_gear: {
          inventory: gearSummary.inventory,
          cyberware: gearSummary.cyberware,
          humanity_loss: gearSummary.totalHl,
          equipped_weapon: gearSummary.equippedWeapon,
          equipped_armor: gearSummary.equippedArmor,
          ...(gearSummary.equippedHeadArmor ? { equipped_head_armor: gearSummary.equippedHeadArmor } : {}),
          fashion: selectedFashion,
          money_spent_eb: gearSummary.spentEb,
        },
      });
      clearDraft(draftKey);
      await onCreated(res.character_id, primaryName);
      resetCharacterDefaults();
      onClose();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Failed to create character");
    } finally {
      setBusy(false);
    }
  };

  if (!open) return null;

  const methodsList: CreationMethodInfo[] = refData?.methods ?? [];

  const specializationOptions: Record<(typeof SPECIALIZATION_BASES)[number], string[]> = {
    Language: Array.from(new Set((refData?.cultural_regions ?? []).flatMap((r) => r.languages))).sort(),
    "Local Expert": ["Your Home", ...(refData?.campaign_presets.districts ?? []).map((d) => d.name)],
    Science: [],
    "Play Instrument": [],
    "Martial Arts": refData?.martial_arts_forms ?? [],
  };

  const availableSkillsForEdit: CreationSkillInfo[] = (() => {
    if (method === "edgerunner" && roleInfo) {
      return Object.keys(edgerunnerSkills).map((skillName) => {
        const meta = skillIndex.get(skillName.split("(", 1)[0].trim().toLowerCase());
        return {
          name: skillName,
          stat: skillStat(skillName, skillIndex),
          cost: skillBaseCost(skillName, skillIndex),
          basic: meta?.basic ?? false,
          specializable: skillName.includes("(choose 1)"),
          group: meta?.group ?? "Role",
          printed_page: meta?.printed_page,
          summary: meta?.summary ?? `${skillName} (${skillStat(skillName, skillIndex)})`,
          description: meta?.description ?? `${skillName} skill.`,
        };
      });
    }
    const baseList = refData?.skills ?? [];
    if (method === "complete_package") {
      const known = new Set(baseList.map((s) => (s.basic_skill_name || s.name).toLowerCase()));
      const extras: CreationSkillInfo[] = [];
      for (const skillName of Object.keys(customSkills)) {
        if (known.has(skillName.toLowerCase())) continue;
        const basePart = skillName.split("(", 1)[0].trim().toLowerCase();
        const meta = skillIndex.get(basePart);
        extras.push({
          name: skillName,
          stat: meta?.stat ?? skillStat(skillName, skillIndex),
          cost: meta?.cost ?? skillBaseCost(skillName, skillIndex),
          basic: false,
          specializable: true,
          group: meta?.group ?? "Education",
          printed_page: meta?.printed_page,
          summary: meta?.summary ?? `${skillName} (Specialized skill)`,
          description: meta?.description ?? `Specialized proficiency in ${skillName}.`,
        });
      }
      return [...extras, ...baseList];
    }
    return baseList;
  })();

  const filteredSkills = availableSkillsForEdit.filter((s) => {
    if (skillGroupFilter === "Basic") {
      if (!s.basic) return false;
    } else if (skillGroupFilter === "Role") {
      if (!(s.name in (roleInfo?.skills ?? {}))) return false;
    } else if (skillGroupFilter !== "All" && s.group !== skillGroupFilter) {
      return false;
    }
    if (skillFilter.trim()) {
      const q = skillFilter.trim().toLowerCase();
      return s.name.toLowerCase().includes(q) || s.summary.toLowerCase().includes(q) || s.stat.toLowerCase().includes(q);
    }
    return true;
  });

  const weaponItemsForFilter: CreationShopItem[] = (() => {
    const baseWeapons = refData?.shop.weapon ?? [];
    const seen = new Set(baseWeapons.map((w) => w.name.toLowerCase()));
    const combined = [...baseWeapons];
    if (weaponGenres.length === 0 || weaponGenres.includes("attachment")) {
      for (const a of refData?.shop?.attachment ?? []) {
        if (!seen.has(a.name.toLowerCase())) {
          seen.add(a.name.toLowerCase());
          combined.push(a);
        }
      }
    }
    if (weaponGenres.length === 0 || weaponGenres.includes("ammo")) {
      for (const am of refData?.shop?.ammo ?? []) {
        if (!seen.has(am.name.toLowerCase())) {
          seen.add(am.name.toLowerCase());
          combined.push(am);
        }
      }
    }
    return combined;
  })();

  const classifyCyberwareSubcategory = (
    item: CreationShopItem,
  ): "foundation" | "neural" | "cyberoptic" | "cyberaudio" | "cyberlimb" | "body" | "fashionware" => {
    const foundations = String(item.stats.foundation ?? "").split(" or ");
    if (foundations.includes(item.name)) return "foundation";
    const groups: Record<string, "neural" | "cyberoptic" | "cyberaudio" | "cyberlimb" | "fashionware"> = {
      Neuralware: "neural",
      Cyberoptics: "cyberoptic",
      Cyberaudio: "cyberaudio",
      Cyberlimbs: "cyberlimb",
      Fashionware: "fashionware",
    };
    return groups[String(item.stats.group ?? "")] ?? "body";
  };

  const classifyProgramSubcategory = (item: CreationShopItem): "booster" | "defender" | "attacker" | "black_ice" => {
    const cls = String(item.stats.class ?? "");
    if (cls.includes("Black ICE") || item.stats.kind === "demon") return "black_ice";
    if (cls.includes("Defender")) return "defender";
    if (cls.includes("Attacker")) return "attacker";
    return "booster";
  };

  const remainingGearEb = 2550 - gearSummary.spentEb;
  const remainingFashionEb = 800 - gearSummary.fashionSpent;

  const shopItemsForCategory: CreationShopItem[] = (() => {
    if (shopCategory === "fashion") return [];
    const rawList = shopCategory === "weapon" ? weaponItemsForFilter : (refData?.shop[shopCategory] ?? []);
    const filtered = rawList.filter((item) => {
      const stats = item.stats ?? {};
      if (shopCategory === "weapon") {
        if (weaponGenres.length > 0) {
          const g = classifyWeaponGenre(item);
          if (!weaponGenres.includes(g)) return false;
        }
        if (weaponTiers.length > 0) {
          const t = classifyWeaponTiers(item);
          if (!t.tiers.some((tier) => weaponTiers.includes(tier))) return false;
        }
      }
      if (shopCategory === "armor" && armorSubFilter !== "all") {
        const locations = Array.isArray(stats.locations) ? stats.locations : [];
        if (!locations.includes(armorSubFilter)) return false;
      }
      if (shopCategory === "cyberware" && cyberwareSubFilter !== "all") {
        if (classifyCyberwareSubcategory(item) !== cyberwareSubFilter) return false;
      }
      if (shopCategory === "program" && programSubFilter !== "all") {
        if (classifyProgramSubcategory(item) !== programSubFilter) return false;
      }
      if (
        selectedOnly &&
        !cartItems.some(
          (c) => c.category === item.category && (c.name === item.name || c.name.startsWith(`${item.name} — `)),
        )
      ) {
        return false;
      }
      if (affordableOnly && method === "complete_package" && item.cost_eb > remainingGearEb) {
        return false;
      }
      if (!shopSearch.trim()) return true;
      const q = shopSearch.trim().toLowerCase();
      return (
        item.name.toLowerCase().includes(q) ||
        item.summary.toLowerCase().includes(q) ||
        String(stats.weapon_class ?? "").toLowerCase().includes(q) ||
        String(stats.group ?? "").toLowerCase().includes(q)
      );
    });
    return [...filtered].sort((a, b) => {
      if (shopSort === "cost_desc") return b.cost_eb - a.cost_eb || a.name.localeCompare(b.name);
      if (shopSort === "name_asc") return a.name.localeCompare(b.name);
      if (shopSort === "sp_desc") return parseSpVal(b.stats) - parseSpVal(a.stats) || a.cost_eb - b.cost_eb;
      if (shopSort === "hl_asc") return parseHlVal(a.stats) - parseHlVal(b.stats) || a.cost_eb - b.cost_eb;
      if (shopSort === "tier_asc") {
        return classifyWeaponTiers(a).sortRank - classifyWeaponTiers(b).sortRank || a.cost_eb - b.cost_eb || a.name.localeCompare(b.name);
      }
      if (shopSort === "tier_desc") {
        const ra = classifyWeaponTiers(a).sortRank;
        const rb = classifyWeaponTiers(b).sortRank;
        const normA = ra === 99 ? -1 : ra;
        const normB = rb === 99 ? -1 : rb;
        return normB - normA || b.cost_eb - a.cost_eb || a.name.localeCompare(b.name);
      }
      return a.cost_eb - b.cost_eb || a.name.localeCompare(b.name);
    });
  })();

  const fashionItemsForDisplay = (() => {
    const q = shopSearch.trim().toLowerCase();
    const list = (refData?.fashion ?? []).filter((f) => {
      if (fashionStyleFilter !== "All" && f.style !== fashionStyleFilter) return false;
      if (selectedOnly && !selectedFashion.some((x) => x.name === f.name)) return false;
      if (affordableOnly && method === "complete_package" && f.cost_eb > remainingFashionEb) return false;
      if (!q) return true;
      return f.name.toLowerCase().includes(q) || f.summary.toLowerCase().includes(q) || f.style.toLowerCase().includes(q);
    });
    return [...list].sort((a, b) => {
      if (shopSort === "cost_desc") return b.cost_eb - a.cost_eb || a.name.localeCompare(b.name);
      if (shopSort === "name_asc") return a.name.localeCompare(b.name);
      return a.cost_eb - b.cost_eb || a.name.localeCompare(b.name);
    });
  })();

  const currentStepIdx = STEPS.findIndex((s) => s.id === step);

  const busyFor = (target: "bio" | "contacts", field: string, entryIndex?: number, subField?: string): "improve" | "regen" | null => {
    const suffix = entryIndex !== undefined && subField ? `${field}:${entryIndex}:${subField}` : field;
    return aiBusyKey === `${target}:expand:${suffix}`
      ? "improve"
      : aiBusyKey === `${target}:scratch:${suffix}`
        ? "regen"
        : null;
  };

  const modalNode = (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-2 sm:p-4 backdrop-blur-sm"
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
      }}
    >
      <CyberFrame
        variant="modal"
        role="dialog"
        aria-modal="true"
        aria-label="Edgerunner Character Sheet Creator"
        className="flex h-[92dvh] max-h-[95dvh] w-full max-w-7xl flex-col overflow-hidden text-[var(--hud-text)]"
      >
        {/* Slim Crimson Header Band with Cyber Chrome Banner */}
        <div className="relative flex flex-wrap items-center justify-between gap-2 overflow-hidden border-b border-[var(--hud-line)] bg-[#5a0b1c]/55 px-4 py-3 sm:px-5">
          <img
            src={edgerunnerChromeBanner}
            alt=""
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 h-full w-full object-cover opacity-20"
          />
          <div className="pointer-events-none absolute inset-0 bg-gradient-to-r from-[#3a0712]/80 via-[#5a0b1c]/55 to-[#12070c]/85" />
          <div className="relative z-10 flex min-w-0 items-center gap-3">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center border border-[var(--hud-line)] bg-[var(--hud-row)] text-[var(--hud-accent)]">
              <UserPlus className="h-4 w-4" />
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2
                  data-text="Edgerunner Character Sheet Creator"
                  className="cp-glitch truncate font-cyber-display text-sm font-semibold uppercase tracking-wider text-[var(--hud-text)]"
                >
                  Edgerunner Character Sheet Creator
                </h2>
                {draftRestored && (
                  <span className="border border-[var(--hud-accent-line)] bg-[var(--hud-accent-navy)] px-1.5 py-0.5 font-cyber-ui text-[10px] font-semibold uppercase tracking-wider text-[var(--hud-accent)]">
                    Draft Restored
                  </span>
                )}
              </div>
              <p className="truncate font-cyber-ui text-[11px] text-[var(--hud-muted)]">
                {name.trim() || "Unnamed Punk"} · {selectedRole} (R4) · {methodsList.find((m) => m.id === method)?.name ?? method}
              </p>
            </div>
          </div>

          <div className="relative z-10 flex items-center gap-2">
            {loadingRef && (
              <span className="font-cyber-ui text-[11px] text-[var(--hud-accent)]">
                Loading Corebook data…
              </span>
            )}
            <HudButton
              variant="tactical"
              size="xs"
              onClick={() => {
                clearDraft(draftKey);
                resetCharacterDefaults();
                onNotify("Character draft cleared.");
              }}
              title="Clear unsaved draft and reset form"
              className="text-[11px]"
            >
              <RotateCcw className="h-3 w-3" />
              <span className="hidden sm:inline">Reset</span>
            </HudButton>
            <HudButton
              variant="tactical"
              size="xs"
              onClick={onClose}
              aria-label="Close character creator"
              className="px-2 py-1"
            >
              <X className="h-4 w-4" />
            </HudButton>
          </div>
        </div>

        {/* Step Navigation Pills */}
        <div className="flex flex-wrap items-center gap-1 border-b border-[var(--hud-line)] bg-black/50 px-4 py-2">
          {STEPS.map((s) => {
            const activeStep = step === s.id;
            return (
              <button
                key={s.id}
                type="button"
                onClick={() => setStep(s.id)}
                className={`px-2.5 py-1 font-cyber-ui text-xs font-semibold transition ${
                  activeStep
                    ? "border border-[var(--hud-accent-line)] bg-[var(--hud-accent-navy)] text-[var(--hud-accent)]"
                    : "border border-transparent text-[var(--hud-muted)] hover:border-[var(--hud-line-soft)] hover:text-[var(--hud-text)]"
                }`}
              >
                <span className="hidden sm:inline">{s.label}</span>
                <span className="sm:hidden">{s.short}</span>
              </button>
            );
          })}
        </div>

        {/* Body: 2-Column Interactive Sheet + Live Preview/Inspector */}
        <div className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden lg:grid-cols-12">
          {/* Left 8 cols: Interactive Editor */}
          <div className="min-h-0 space-y-5 overflow-y-auto p-4 font-cyber-ui sm:p-5 lg:col-span-8">
            {/* STEP 1: IDENTITY & ROLE */}
            {step === "identity" && (
              <div className="space-y-5">
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-12">
                  <div className="sm:col-span-4">
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <label className="cyber-field-label mb-0">Street Handle / Name *</label>
                      <button
                        type="button"
                        onClick={() => setName(pickRandom(HANDLE_SUGGESTIONS))}
                        className="cyber-btn-tac cp-fx-hover px-2 py-0.5 font-cyber-ui text-[11px] text-[var(--hud-accent)]"
                      >
                        <Dices className="h-3 w-3" /> Roll Handle
                      </button>
                    </div>
                    <input
                      type="text"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      placeholder="e.g. Vee Mercer"
                      className="cyber-input px-3 py-2"
                    />
                  </div>
                  <div className="sm:col-span-3">
                    <div className="mb-1 flex items-center justify-between gap-1">
                      <label className="cyber-field-label mb-0 truncate">Real / Legal Name</label>
                      <label className="inline-flex shrink-0 cursor-pointer items-center gap-1 font-cyber-ui text-[10px] font-normal text-[var(--hud-warn)]" title="When checked, NPCs and the street only know your character by their Handle unless revealed in play.">
                        <input
                          type="checkbox"
                          checked={realNameHidden}
                          onChange={(e) => setRealNameHidden(e.target.checked)}
                          className="accent-[var(--hud-warn)]"
                        />
                        {realNameHidden ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
                        <span>{realNameHidden ? "Hidden" : "Public"}</span>
                      </label>
                    </div>
                    <input
                      type="text"
                      value={realName}
                      onChange={(e) => setRealName(e.target.value)}
                      placeholder="Optional legal name"
                      className="cyber-input px-3 py-2"
                    />
                  </div>
                  <div className="sm:col-span-2">
                    <label className="cyber-field-label">Gender</label>
                    <input
                      type="text"
                      aria-label="Gender"
                      list="cpr-gender-list"
                      value={gender === "__custom__" ? "" : gender}
                      onChange={(e) => setGender(e.target.value)}
                      placeholder="Woman, Man, Non-Binary…"
                      className="cyber-input px-2.5 py-2"
                    />
                    <datalist id="cpr-gender-list">
                      <option value="Woman" />
                      <option value="Man" />
                      <option value="Non-Binary" />
                      <option value="Genderfluid" />
                      <option value="Agender" />
                    </datalist>
                  </div>
                  <div className="sm:col-span-2">
                    <label className="cyber-field-label">Pronouns</label>
                    <input
                      type="text"
                      list="cpr-pronouns-list"
                      value={pronouns}
                      onChange={(e) => setPronouns(e.target.value)}
                      placeholder="they/them…"
                      className="cyber-input px-2.5 py-2"
                    />
                    <datalist id="cpr-pronouns-list">
                      <option value="she/her" />
                      <option value="he/him" />
                      <option value="they/them" />
                      <option value="she/they" />
                      <option value="he/they" />
                      <option value="any/all" />
                    </datalist>
                  </div>
                  <div className="sm:col-span-1">
                    <label className="cyber-field-label">Age</label>
                    <input
                      type="text"
                      value={age}
                      onChange={(e) => setAge(e.target.value)}
                      placeholder="24"
                      className="cyber-input px-2.5 py-2 font-cyber-data"
                    />
                  </div>
                </div>

                {/* Portrait & Chat Color Tag Row */}
                <div className="grid grid-cols-1 gap-3 border border-[var(--hud-line-soft)] bg-[var(--hud-row)] p-3 sm:grid-cols-12">
                  <div className="flex items-center gap-3 sm:col-span-7">
                    {portraitUrl.trim() ? (
                      <img
                        src={portraitUrl}
                        alt={name || "Portrait"}
                        className="h-12 w-12 shrink-0 border border-[var(--hud-accent-line)] object-cover"
                      />
                    ) : (
                      <div className="flex h-12 w-12 shrink-0 items-center justify-center border border-[var(--hud-line-soft)] bg-black/60 text-[var(--hud-muted)]">
                        <ImagePlus className="h-5 w-5" />
                      </div>
                    )}
                    <div className="min-w-0 flex-1 space-y-1">
                      <div className="flex flex-wrap items-center justify-between gap-1.5">
                        <span className="font-cyber-ui text-xs font-semibold text-[var(--hud-text)]">
                          Character Portrait (optional)
                        </span>
                        <div className="flex items-center gap-1.5">
                          <label className="cyber-btn-tac cp-fx-hover cursor-pointer px-2 py-0.5 font-cyber-ui text-[11px] font-medium text-[var(--hud-accent)]">
                            <ImagePlus className="h-3 w-3" /> Upload Image
                            <input
                              type="file"
                              accept="image/*"
                              onChange={(e) => handlePortraitUpload(e.target.files?.[0])}
                              className="hidden"
                            />
                          </label>
                          {portraitUrl && (
                            <button
                              type="button"
                              onClick={() => setPortraitUrl("")}
                              className="border border-[var(--hud-line-soft)] bg-black/60 px-1.5 py-0.5 font-cyber-ui text-[10px] text-[var(--hud-muted)] hover:border-[var(--hud-primary-bright)] hover:text-[var(--hud-primary-bright)]"
                            >
                              Clear
                            </button>
                          )}
                        </div>
                      </div>
                      <input
                        type="url"
                        value={portraitUrl.startsWith("data:") ? "" : portraitUrl}
                        onChange={(e) => setPortraitUrl(e.target.value)}
                        placeholder={portraitUrl.startsWith("data:") ? "Custom image uploaded from device" : "Or paste an image URL (https://…)"}
                        className="w-full border border-[var(--hud-line-soft)] bg-black/60 px-2.5 py-1 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                      />
                    </div>
                  </div>

                  <div className="flex flex-col justify-center sm:col-span-5">
                    <span className="mb-1.5 flex items-center gap-1 font-cyber-ui text-xs font-semibold text-[var(--hud-text)]">
                      <Palette className="h-3.5 w-3.5 text-[var(--hud-accent)]" /> Chat Name Tag Color
                    </span>
                    <div className="flex flex-wrap items-center gap-1.5">
                      {Object.entries(CHARACTER_COLOR_THEMES).map(([cid, theme]) => {
                        const active = characterColor === cid;
                        return (
                          <button
                            key={cid}
                            type="button"
                            onClick={() => setCharacterColor(cid)}
                            className={`inline-flex items-center gap-1.5 border px-2 py-1 font-cyber-ui text-[11px] font-medium transition ${
                              active
                                ? `${theme.nameBadgeClass} ring-1 ring-white/40`
                                : "border-[var(--hud-line-soft)] bg-black/60 text-[var(--hud-muted)] hover:border-[var(--hud-line)] hover:text-[var(--hud-text)]"
                            }`}
                          >
                            <span className={`h-2.5 w-2.5 rounded-full ${theme.dotClass}`} />
                            <span>{theme.label.split(" ")[1] || theme.label}</span>
                          </button>
                        );
                      })}
                      <label
                        className="relative inline-flex cursor-pointer items-center gap-1.5 border border-[var(--hud-line-soft)] bg-black/60 px-2 py-1 font-cyber-ui text-[11px] font-medium text-[var(--hud-text)] transition hover:border-[var(--hud-accent)]"
                        style={isHexColor(characterColor) ? resolveCharacterColor(characterColor).nameBadgeStyle : undefined}
                      >
                        <span
                          className="h-2.5 w-2.5 shrink-0 rounded-full border border-white/25"
                          style={{ backgroundColor: normalizeColorHex(characterColor) }}
                        />
                        <input
                          type="color"
                          aria-label="Custom chat color wheel"
                          value={normalizeColorHex(characterColor)}
                          onChange={(e) => setCharacterColor(e.target.value)}
                          className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
                        />
                        <span className={isHexColor(characterColor) ? "font-cyber-data" : "font-cyber-ui"}>
                          {isHexColor(characterColor) ? characterColor.toUpperCase() : "Color Wheel"}
                        </span>
                      </label>
                    </div>
                  </div>
                </div>

                <div>
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <label className="cyber-field-label mb-0">
                      One-Line Concept (optional)
                    </label>
                    <FieldAiActions
                      label="Concept"
                      disabled={aiBusy}
                      busyAction={busyFor("bio", "concept")}
                      onImprove={() => void handleAiAssist("bio", "expand", "concept")}
                      onRegen={() => void handleAiAssist("bio", "scratch", "concept")}
                    />
                  </div>
                  <input
                    type="text"
                    value={conceptTagline}
                    onChange={(e) => setConceptTagline(e.target.value)}
                    placeholder="e.g. Ex-Trauma Team medic running black-market clinic jobs in Watson"
                    className="cyber-input px-3 py-2"
                  />
                </div>

                {/* Creation Method Picker */}
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-cyber-display text-xs font-semibold uppercase tracking-wider text-[var(--hud-text)]">
                      Build Method
                    </span>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-cyber-ui text-[11px] text-[var(--hud-muted)]">
                        Hover any card for rules breakdown
                      </span>
                    </div>
                  </div>
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                    {methodsList.map((m) => {
                      const active = method === m.id;
                      return (
                        <button
                          key={m.id}
                          type="button"
                          onMouseEnter={() =>
                            setInspector({
                              title: m.name,
                              subtitle: m.badge,
                              body: m.summary,
                              mechanics: m.rules,
                            })
                          }
                          onFocus={() =>
                            setInspector({
                              title: m.name,
                              subtitle: m.badge,
                              body: m.summary,
                              mechanics: m.rules,
                            })
                          }
                          onClick={() => {
                            setMethod(m.id);
                            if (m.id === "complete_package" && roleInfo) {
                              setCustomStats({ ...roleInfo.smart_fill });
                              setCustomSkills(defaultCompleteSkills(roleInfo, refData?.skills ?? []));
                            }
                          }}
                          className={`${
                            active ? "cyber-card-active" : "cyber-card"
                          } p-3 text-left`}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span
                              className={`font-cyber-ui text-[13px] ${
                                active ? "font-bold text-white" : "font-semibold text-[var(--hud-text)]"
                              }`}
                            >
                              {m.name}
                            </span>
                            <span
                              className={`border px-1.5 py-0.5 font-cyber-ui text-[10px] font-semibold uppercase tracking-wider ${
                                active
                                  ? "border-[var(--hud-accent-line)] bg-[var(--hud-accent-navy)] text-[var(--hud-accent)]"
                                  : "border-white/15 bg-black/50 text-[var(--hud-muted)]"
                              }`}
                            >
                              {m.badge}
                            </span>
                          </div>
                          <p className="mt-1 font-cyber-ui text-[11px] leading-relaxed text-[var(--hud-muted)]">
                            {m.summary}
                          </p>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* All 10 Roles Grid */}
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-cyber-display text-xs font-semibold uppercase tracking-wider text-[var(--hud-text)]">
                      Choose Your Role (Starts at Rank 4)
                    </span>
                    <div className="flex items-center gap-2">
                      {["Tech", "Medtech", "Fixer", "Nomad", "Exec"].includes(selectedRole) && (
                        <HudButton
                          variant="tactical"
                          size="xs"
                          onClick={() => roleExtrasRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" })}
                          className="border-[var(--hud-warn)]/60 text-[var(--hud-warn)]"
                        >
                          Configure {selectedRole} Options ↓
                        </HudButton>
                      )}
                      <span className="font-cyber-ui text-[11px] text-[var(--hud-muted)]">
                        Hover or select for Role Ability info
                      </span>
                    </div>
                  </div>
                  <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                    {(refData?.roles ?? []).map((role) => {
                      const active = selectedRole === role.name;
                      const hasRoleExtras = ["Tech", "Medtech", "Fixer", "Nomad", "Exec"].includes(role.name);
                      return (
                        <button
                          key={role.name}
                          type="button"
                          onMouseEnter={() =>
                            setInspector({
                              title: `${role.name} · Role Ability: ${role.ability}`,
                              subtitle: role.printed_page ? `Corebook p.${role.printed_page}` : undefined,
                              body: role.description,
                            })
                          }
                          onFocus={() =>
                            setInspector({
                              title: `${role.name} · Role Ability: ${role.ability}`,
                              subtitle: role.printed_page ? `Corebook p.${role.printed_page}` : undefined,
                              body: role.description,
                            })
                          }
                          onClick={() => {
                            setSelectedRole(role.name);
                            if (hasRoleExtras) {
                              window.setTimeout(() => {
                                roleExtrasRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
                              }, 40);
                            }
                          }}
                          className={`${
                            active ? "cyber-card-active" : "cyber-card"
                          } p-2.5 text-left`}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span
                              className={`font-cyber-ui text-[13px] ${
                                active ? "font-bold text-white" : "font-semibold text-[var(--hud-text)]"
                              }`}
                            >
                              {role.name}
                            </span>
                            <div className="flex items-center gap-1.5">
                              {hasRoleExtras && (
                                <span
                                  className={`border px-1 py-0.5 font-cyber-ui text-[9px] font-semibold uppercase tracking-wider ${
                                    active
                                      ? "border-[var(--hud-warn)]/60 bg-[var(--hud-warn)]/15 text-[var(--hud-warn)]"
                                      : "border-white/15 bg-black/40 text-[var(--hud-muted)]"
                                  }`}
                                >
                                  Role Options
                                </span>
                              )}
                              <RoleTag role={role.ability} tone={active ? "accent" : "muted"} />
                            </div>
                          </div>
                          <p className="mt-0.5 font-cyber-ui text-[11px] italic text-[var(--hud-muted)]">{role.summary}</p>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Role-Specific Ability Choices */}
                <div ref={roleExtrasRef} className="space-y-2">
                {selectedRole === "Tech" && (
                  <div className="cyber-card-active space-y-2 p-3">
                    <div className="flex items-center justify-between">
                      <span className="font-cyber-ui text-xs font-bold text-[var(--hud-warn)]">
                        Tech Maker Specialties (8 pts total, max 4 each)
                      </span>
                      <span className="font-cyber-data text-xs text-[var(--hud-accent)]">
                        {Object.values(techMakerRanks).reduce((a, b) => a + b, 0)} / 8
                      </span>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      {MAKER_SPECIALTIES.map((spec) => (
                        <div key={spec} className="flex items-center justify-between border border-[var(--hud-line-soft)] bg-black/55 px-2.5 py-1.5 text-xs">
                          <span className="font-cyber-ui text-[var(--hud-text)]">{spec}</span>
                          <div className="flex items-center gap-1.5 font-cyber-data">
                            <button
                              type="button"
                              onClick={() => setTechMakerRanks((p) => ({ ...p, [spec]: Math.max(0, (p[spec] ?? 0) - 1) }))}
                              className="cyber-btn-tac cp-fx-hover px-1.5 py-0.5 font-cyber-data text-xs"
                            >-</button>
                            <span>{techMakerRanks[spec] ?? 0}</span>
                            <button
                              type="button"
                              onClick={() => setTechMakerRanks((p) => ({ ...p, [spec]: Math.min(4, (p[spec] ?? 0) + 1) }))}
                              className="cyber-btn-tac cp-fx-hover px-1.5 py-0.5 font-cyber-data text-xs"
                            >+</button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {selectedRole === "Medtech" && (
                  <div className="cyber-card-active space-y-2 p-3">
                    <div className="flex items-center justify-between">
                      <span className="font-cyber-ui text-xs font-bold text-[var(--hud-accent)]">
                        Medtech Medicine Allocations (4 pts total)
                      </span>
                      <span className="font-cyber-data text-xs text-[var(--hud-accent)]">
                        {Object.values(medtechAlloc).reduce((a, b) => a + b, 0)} / 4
                      </span>
                    </div>
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                      {(["Surgery", "Pharmaceuticals", "Cryosystem Operation"] as const).map((field) => (
                        <div key={field} className="flex items-center justify-between border border-[var(--hud-line-soft)] bg-black/55 px-2.5 py-1.5 text-xs">
                          <span className="truncate font-cyber-ui text-[var(--hud-text)]">{field}</span>
                          <div className="flex items-center gap-1.5 font-cyber-data">
                            <button
                              type="button"
                              onClick={() => setMedtechAlloc((p) => ({ ...p, [field]: Math.max(0, (p[field] ?? 0) - 1) }))}
                              className="cyber-btn-tac cp-fx-hover px-1.5 py-0.5 font-cyber-data text-xs"
                            >-</button>
                            <span>{medtechAlloc[field] ?? 0}</span>
                            <button
                              type="button"
                              onClick={() => setMedtechAlloc((p) => ({ ...p, [field]: Math.min(4, (p[field] ?? 0) + 1) }))}
                              className="cyber-btn-tac cp-fx-hover px-1.5 py-0.5 font-cyber-data text-xs"
                            >+</button>
                          </div>
                        </div>
                      ))}
                    </div>
                    {(medtechAlloc.Pharmaceuticals ?? 0) > 0 && (
                      <div className="space-y-1 pt-1">
                        <span className="font-cyber-ui text-[11px] text-[var(--hud-muted)]">
                          Starting Pharmaceutical Recipes ({medtechAlloc.Pharmaceuticals}):
                        </span>
                        <div className="flex flex-wrap gap-1.5">
                          {Array.from({ length: medtechAlloc.Pharmaceuticals }).map((_, idx) => (
                            <select
                              key={idx}
                              value={medtechRecipes[idx] ?? "Speedheal"}
                              onChange={(e) => {
                                const next = [...medtechRecipes];
                                next[idx] = e.target.value;
                                setMedtechRecipes(next);
                              }}
                              className="border border-[var(--hud-line-soft)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                            >
                              {(refData?.pharmaceuticals ?? []).map((r) => (
                                <option key={r} value={r}>{r}</option>
                              ))}
                            </select>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {selectedRole === "Fixer" && (
                  <div className="cyber-card-active grid grid-cols-1 gap-2 p-3 sm:grid-cols-2">
                    <div>
                      <label className="cyber-field-label text-[var(--hud-accent)]">
                        Fixer Street Culture
                      </label>
                      <input
                        type="text"
                        value={fixerCulture}
                        onChange={(e) => setFixerCulture(e.target.value)}
                        className="cyber-input px-2.5 py-1.5"
                      />
                    </div>
                    <div>
                      <label className="cyber-field-label text-[var(--hud-accent)]">
                        Operator Reach Language
                      </label>
                      <input
                        type="text"
                        value={fixerLanguage}
                        onChange={(e) => setFixerLanguage(e.target.value)}
                        className="cyber-input px-2.5 py-1.5"
                      />
                    </div>
                  </div>
                )}

                {selectedRole === "Nomad" && (
                  <div className="cyber-card-active space-y-2 p-3">
                    <span className="font-cyber-ui text-xs font-bold text-[var(--hud-warn)]">
                      Nomad Moto Picks (4 Starting Vehicles / Upgrades)
                    </span>
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                      {Array.from({ length: 4 }).map((_, idx) => (
                        <select
                          key={idx}
                          value={nomadVehicles[idx] ?? ""}
                          onChange={(e) => {
                            const next = [...nomadVehicles];
                            next[idx] = e.target.value;
                            setNomadVehicles(next);
                          }}
                          className="cyber-input px-2 py-1.5"
                        >
                          <optgroup label="Base Vehicles">
                            {(refData?.nomad_vehicles ?? []).map((v) => (
                              <option key={v} value={v}>{v}</option>
                            ))}
                          </optgroup>
                          <optgroup label="Vehicle Upgrades">
                            {(refData?.nomad_upgrades ?? []).map((u) => (
                              <option key={u.name} value={u.name}>
                                {u.name} (Rank {u.rank}+)
                              </option>
                            ))}
                          </optgroup>
                        </select>
                      ))}
                    </div>
                  </div>
                )}

                {selectedRole === "Exec" && (
                  <div className="cyber-card-active space-y-2 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-cyber-ui text-xs font-bold text-[var(--hud-text)]">
                        Exec Team Member &amp; Corporate Perks
                      </span>
                      <span className="border border-[var(--hud-accent-line)] bg-[var(--hud-accent-navy)] px-2 py-0.5 font-cyber-ui text-[10px] font-semibold text-[var(--hud-accent)]">
                        Includes Corporate Conapt + Trauma Team Silver
                      </span>
                    </div>
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                      <div>
                        <label className="cyber-field-label">
                          Exec Team Member Name
                        </label>
                        <input
                          type="text"
                          value={execTeamName}
                          onChange={(e) => setExecTeamName(e.target.value)}
                          className="cyber-input px-2.5 py-1.5"
                        />
                      </div>
                      <div>
                        <label className="cyber-field-label">
                          Team Member Specialty
                        </label>
                        <input
                          type="text"
                          value={execTeamRole}
                          onChange={(e) => setExecTeamRole(e.target.value)}
                          aria-label="Exec Team Member Specialty"
                          placeholder="e.g. Bodyguard"
                          className="cyber-input px-2.5 py-1.5"
                        />
                      </div>
                      <div>
                        <label className="cyber-field-label">
                          Starting Loyalty (1–10)
                        </label>
                        <input
                          type="number"
                          min={1}
                          max={10}
                          value={execTeamLoyalty}
                          onChange={(e) => setExecTeamLoyalty(Math.max(1, Math.min(10, parseInt(e.target.value, 10) || 4)))}
                          className="cyber-input px-2.5 py-1.5 font-cyber-data"
                        />
                      </div>
                    </div>
                  </div>
                )}
                </div>
              </div>
            )}

            {/* STEP 2: STATS & VITALS */}
            {step === "stats" && (
              <div className="space-y-4">
                <div className="sticky -top-4 sm:-top-5 z-10 -mx-4 sm:-mx-5 flex flex-wrap items-center justify-between gap-2 border-b border-[var(--hud-line)] bg-[var(--hud-bg)]/95 px-4 py-3 backdrop-blur sm:px-5">
                  <div>
                    <div className="flex flex-wrap items-center gap-2 font-cyber-display text-xs font-semibold uppercase tracking-wider text-[var(--hud-text)]">
                      <span>
                        {method === "streetrat" && `${selectedRole} Template Row #${streetratRoll}`}
                        {method === "edgerunner" && `${selectedRole} Per-STAT Template Rolls`}
                        {method === "complete_package" && "Complete Package Point-Buy"}
                      </span>
                      {method === "complete_package" && (
                        <span className="border border-[var(--hud-accent-line)] bg-[var(--hud-accent-navy)] px-2 py-0.5 font-cyber-data text-[10px] text-[var(--hud-accent)]">
                          {statSum} / 62 STAT PTS
                        </span>
                      )}
                      {method === "complete_package" && (() => {
                        const statRemaining = 62 - statSum;
                        const remainingCls =
                          statRemaining === 0
                            ? "border-[var(--hud-ok)]/60 bg-[var(--hud-ok)]/15 text-[var(--hud-ok)]"
                            : statRemaining > 0
                              ? "border-[var(--hud-warn)]/60 bg-[var(--hud-warn)]/15 text-[var(--hud-warn)]"
                              : "border-[var(--hud-primary-bright)]/70 bg-[var(--hud-primary-bright)]/15 text-[var(--hud-primary-bright)]";
                        return (
                          <span className={`border px-2 py-0.5 font-cyber-data text-[10px] font-bold ${remainingCls}`}>
                            {statRemaining === 0 ? "0 PTS LEFT" : `${statRemaining} PTS LEFT`}
                          </span>
                        );
                      })()}
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {method === "streetrat" && (
                      <HudButton
                        variant="tactical"
                        size="sm"
                        onClick={() => setStreetratRoll(d(10))}
                      >
                        <Dices className="h-3.5 w-3.5 text-[var(--hud-accent)]" /> Roll 1d10 Template
                      </HudButton>
                    )}
                    {method === "edgerunner" && (
                      <HudButton
                        variant="tactical"
                        size="sm"
                        onClick={() => setEdgerunnerRolls(Array.from({ length: 10 }, () => d(10)))}
                      >
                        <Dices className="h-3.5 w-3.5 text-[var(--hud-accent)]" /> Roll 1d10 × 10 STATs
                      </HudButton>
                    )}
                    {method === "complete_package" && roleInfo && (
                      <HudButton
                        variant="tactical"
                        size="sm"
                        onClick={() => setCustomStats({ ...roleInfo.smart_fill })}
                      >
                        <Wand2 className="h-3.5 w-3.5 text-[var(--hud-accent)]" /> Role Smart Fill (62 pts)
                      </HudButton>
                    )}
                  </div>
                </div>

                {/* 10 STAT Cards */}
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
                  {STAT_NAMES.map((stat, idx) => {
                    const val = activeStats[stat];
                    const info = refData?.stats[stat];
                    const isKey = roleInfo?.key_stats.includes(stat);
                    const showInfo = () => {
                      if (!info) return;
                      setInspector({
                        title: `${stat} · ${info.name}`,
                        subtitle: [isKey ? `Key STAT for ${selectedRole}` : "", info.printed_page ? `Corebook p.${info.printed_page}` : ""]
                          .filter(Boolean)
                          .join(" · "),
                        body: info.description,
                      });
                    };
                    return (
                      <div
                        key={stat}
                        onMouseEnter={showInfo}
                        onClick={showInfo}
                        title={info?.description}
                        className="cyber-card p-3 text-[var(--hud-text)]"
                      >
                        <span className="font-cyber-display text-xs font-bold uppercase tracking-wider text-white">
                          {stat}
                        </span>
                        {isKey && (
                          <span className="ml-1.5 border border-[var(--hud-accent-line)] bg-[var(--hud-accent-navy)] px-1.5 py-0.5 font-cyber-data text-[9px] font-bold uppercase text-[var(--hud-accent)]">
                            Key
                          </span>
                        )}
                        <div className="truncate font-cyber-ui text-[10px] text-[var(--hud-muted)]">{info?.name}</div>

                        {method === "streetrat" ? (
                          <div className="mt-2 text-center font-cyber-data text-xl font-bold text-[var(--hud-accent)]">{val}</div>
                        ) : method === "edgerunner" ? (
                          <div className="mt-2 flex items-center justify-between gap-1">
                            <span className="font-cyber-data text-lg font-bold text-[var(--hud-accent)]">{val}</span>
                            <button
                              type="button"
                              title={`Reroll ${stat} column`}
                              onClick={() =>
                                setEdgerunnerRolls((prev) => {
                                  const next = [...prev];
                                  next[idx] = d(10);
                                  return next;
                                })
                              }
                              className="cyber-btn-tac cp-fx-hover px-1.5 py-0.5 font-cyber-data text-[10px]"
                            >
                              r{edgerunnerRolls[idx]} ↻
                            </button>
                          </div>
                        ) : (
                          <div className="mt-2 flex items-center justify-between gap-1">
                            <button
                              type="button"
                              onClick={() =>
                                setCustomStats((prev) => ({
                                  ...prev,
                                  [stat]: Math.max(2, prev[stat] - 1),
                                }))
                              }
                              className="cyber-btn-tac cp-fx-hover px-2 py-0.5 font-cyber-data text-xs"
                            >-</button>
                            <span className="font-cyber-data text-base font-bold text-[var(--hud-text)]">{val}</span>
                            <button
                              type="button"
                              onClick={() =>
                                setCustomStats((prev) => ({
                                  ...prev,
                                  [stat]: Math.min(8, prev[stat] + 1),
                                }))
                              }
                              className="cyber-btn-tac cp-fx-hover px-2 py-0.5 font-cyber-data text-xs"
                            >+</button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>

                {/* Streetrat Clickable 10-Row Corebook Template Table */}
                {method === "streetrat" && roleInfo && roleInfo.templates.length === 10 && (
                  <div className="space-y-2 border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] p-3">
                    <div className="font-cyber-ui text-xs font-semibold text-[var(--hud-text)]">
                      Corebook {selectedRole} Templates (Click any row 1–10 or Roll 1d10)
                    </div>
                    <div className="overflow-x-auto">
                      <table className="w-full text-center font-cyber-data text-[11px]">
                        <thead>
                          <tr className="border-b border-[var(--hud-line-soft)] font-cyber-ui text-[var(--hud-muted)]">
                            <th className="py-1 pr-2 text-left">Roll</th>
                            {STAT_NAMES.map((s) => (
                              <th key={s} className="px-1 py-1">{s}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {roleInfo.templates.map((row, idx) => {
                            const rollNum = idx + 1;
                            const chosen = streetratRoll === rollNum;
                            return (
                              <tr
                                key={rollNum}
                                onClick={() => setStreetratRoll(rollNum)}
                                className={`cursor-pointer border-b border-[var(--hud-line-soft)]/50 transition ${
                                  chosen
                                    ? "bg-[var(--hud-accent-navy)] font-bold text-[var(--hud-accent)]"
                                    : "text-[var(--hud-text)] hover:bg-[var(--hud-row)]"
                                }`}
                              >
                                <td className="py-1 pr-2 text-left">#{rollNum}</td>
                                {row.map((num, cIdx) => (
                                  <td key={cIdx} className="px-1 py-1">{num}</td>
                                ))}
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* STEP 3: SKILLS */}
            {step === "skills" && (
              <div className="space-y-4">
                <div className="sticky -top-4 sm:-top-5 z-10 -mx-4 sm:-mx-5 space-y-2.5 border-b border-[var(--hud-line)] bg-[var(--hud-bg)]/95 px-4 pt-3 pb-2.5 backdrop-blur sm:px-5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <div className="flex flex-wrap items-center gap-2 font-cyber-display text-xs font-semibold uppercase tracking-wider text-[var(--hud-text)]">
                        <span>
                          {method === "streetrat" && `Preset ${selectedRole} Skills (20 Role Skills + Native Language)`}
                          {method === "edgerunner" && "Role Skill Allocation"}
                          {method === "complete_package" && "Full Skill Allocation (x2 costs double)"}
                        </span>
                        {(method === "edgerunner" || method === "complete_package") && (() => {
                          const skillRemaining = 86 - skillPointsSpent;
                          const remainingCls =
                            skillRemaining === 0
                              ? "border-[var(--hud-ok)]/60 bg-[var(--hud-ok)]/15 text-[var(--hud-ok)]"
                              : skillRemaining > 0
                                ? "border-[var(--hud-warn)]/60 bg-[var(--hud-warn)]/15 text-[var(--hud-warn)]"
                                : "border-[var(--hud-primary-bright)]/70 bg-[var(--hud-primary-bright)]/15 text-[var(--hud-primary-bright)]";
                          return (
                            <>
                              <span className="border border-[var(--hud-accent-line)] bg-[var(--hud-accent-navy)] px-2 py-0.5 font-cyber-data text-[10px] text-[var(--hud-accent)]">
                                {skillPointsSpent} / 86 PTS USED
                              </span>
                              <span className={`border px-2.5 py-0.5 font-cyber-data text-[11px] font-bold ${remainingCls}`}>
                                {skillRemaining} PTS LEFT
                              </span>
                            </>
                          );
                        })()}
                      </div>
                      <p className="font-cyber-ui text-[11px] text-[var(--hud-muted)]">
                        Skill Check = STAT + Skill Rank + 1d10. Hover any skill to see what it does &amp; what DVs you beat.
                      </p>
                    </div>

                    <div className="flex items-center gap-2">
                      {method === "complete_package" && roleInfo && (
                        <HudButton
                          variant="tactical"
                          size="xs"
                          onClick={() => setCustomSkills(defaultCompleteSkills(roleInfo, refData?.skills ?? []))}
                        >
                          <Wand2 className="h-3 w-3 text-[var(--hud-accent)]" /> Role Starter Build (86 pts)
                        </HudButton>
                      )}
                      {method === "edgerunner" && roleInfo && (
                        <HudButton
                          variant="tactical"
                          size="xs"
                          onClick={() => setEdgerunnerSkills({ ...roleInfo.skills })}
                        >
                          Reset to Template
                        </HudButton>
                      )}
                    </div>
                  </div>

                  {/* Search & Group Filter */}
                  <div className="flex flex-wrap items-center gap-2">
                    <div className="relative min-w-[180px] flex-1">
                      <Search className="pointer-events-none absolute left-2.5 top-2 h-3.5 w-3.5 text-[var(--hud-muted)]" />
                      <input
                        type="text"
                        value={skillFilter}
                        onChange={(e) => setSkillFilter(e.target.value)}
                        placeholder="Filter skills (e.g. Handgun, Stealth, REF)…"
                        className="cyber-input py-1.5 pl-8 pr-3 text-xs"
                      />
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {["All", "Basic", "Role", ...Array.from(new Set((refData?.skills ?? []).map((s) => s.group)))].map((grp) => (
                        <button
                          key={grp}
                          type="button"
                          onClick={() => setSkillGroupFilter(grp)}
                          className={`border px-2 py-1 font-cyber-ui text-[11px] font-semibold transition ${
                            skillGroupFilter === grp
                              ? "border-[var(--hud-accent-line)] bg-[var(--hud-accent-navy)] text-[var(--hud-accent)]"
                              : "border-[var(--hud-line-soft)] bg-[var(--hud-panel)] text-[var(--hud-muted)] hover:border-[var(--hud-line)] hover:text-[var(--hud-text)]"
                          }`}
                        >
                          {grp}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Compact Specialization Builder (Complete Package) */}
                  {method === "complete_package" && (
                    <div className="space-y-1.5 border border-[var(--hud-line-soft)] bg-[var(--hud-row)] px-2.5 py-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-cyber-display text-[10px] font-semibold uppercase tracking-wider text-[var(--hud-muted)]">
                          + Specialization
                        </span>
                        <select
                          aria-label="Specialization Category"
                          value={specBasePick}
                          onChange={(e) => setSpecBasePick(e.target.value as typeof specBasePick)}
                          className="cyber-input w-auto px-2 py-1 text-xs"
                        >
                          {SPECIALIZATION_BASES.map((b) => (
                            <option key={b} value={b}>{b}</option>
                          ))}
                        </select>
                        <input
                          type="text"
                          value={specFocusInput}
                          onChange={(e) => setSpecFocusInput(e.target.value)}
                          list="specialization-focus-options"
                          placeholder="Specialization focus…"
                          className="cyber-input min-w-[160px] flex-1 px-2.5 py-1 text-xs"
                        />
                        <datalist id="specialization-focus-options">
                          {specializationOptions[specBasePick].map((opt) => (
                            <option key={opt} value={opt} />
                          ))}
                        </datalist>
                        <HudButton
                          variant="tactical"
                          size="xs"
                          onClick={() => {
                            const focus = specFocusInput.trim();
                            if (!focus) return;
                            const fullName = `${specBasePick} (${focus})`;
                            setCustomSkills((p) => ({ ...p, [fullName]: p[fullName] ?? 2 }));
                            setSpecFocusInput("");
                          }}
                        >
                          + Add Specialization
                        </HudButton>
                      </div>
                    </div>
                  )}
                </div>

                {/* Skills List */}
                <div className="space-y-1.5">
                  {filteredSkills.map((sk) => {
                    const storageKey =
                      method === "complete_package" && sk.basic_skill_name
                        ? sk.basic_skill_name
                        : sk.name;
                    const rank =
                      method === "streetrat"
                        ? (roleInfo?.skills[sk.name] ?? effectiveSkills[sk.name] ?? 0)
                        : method === "edgerunner"
                          ? (edgerunnerSkills[sk.name] ?? 0)
                          : (customSkills[storageKey] ?? customSkills[sk.name] ?? 0);
                    const statVal = activeStats[sk.stat] ?? 6;
                    const baseTotal = statVal + rank;
                    const minRank =
                      method === "edgerunner"
                        ? 2
                        : method === "complete_package" && sk.basic
                          ? 2
                          : 0;
                    const maxRank = 6;
                    const lockedMedtechSkill =
                      method === "complete_package" && /^(Surgery|Medical Tech)$/i.test(sk.name);

                    const hoverPayload: InspectorCard = {
                      title: `${sk.name} (${sk.stat}${sk.cost === 2 ? " · x2 Cost" : ""})`,
                      subtitle: `Base = ${statVal} ${sk.stat} + ${rank} Skill = +${baseTotal}${sk.printed_page ? ` · Corebook p.${sk.printed_page}` : ""}`,
                      body: sk.description,
                      mechanics: `With Base +${baseTotal} + 1d10 (avg ${baseTotal + 5}), you easily clear Simple (DV 9) and Everyday (DV 13) tasks.${sk.cost === 2 ? " Difficult (x2): every +1 rank costs 2 skill points." : ""}`,
                      tip: sk.basic ? "One of the 13 Basic Skills every Edgerunner starts at Rank 2+." : undefined,
                    };

                    const updateRank = (next: number) => {
                      const clamped = Math.max(minRank, Math.min(maxRank, next));
                      if (method === "edgerunner") {
                        setEdgerunnerSkills((p) => ({ ...p, [sk.name]: clamped }));
                      } else {
                        setCustomSkills((p) => {
                          const copy = { ...p };
                          if (clamped === 0 && !sk.basic) delete copy[storageKey];
                          else copy[storageKey] = clamped;
                          return copy;
                        });
                      }
                    };

                    return (
                      <div
                        key={sk.name}
                        onMouseEnter={() => setInspector(hoverPayload)}
                        onClick={() => setInspector(hoverPayload)}
                        className={`flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-xs ${
                          rank > minRank ? "cyber-card-active" : "cyber-card"
                        }`}
                      >
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className="font-cyber-ui text-[13px] font-semibold text-white">{storageKey}</span>
                            <span className="border border-[var(--hud-line-soft)] bg-black/50 px-1.5 py-0.5 font-cyber-ui text-[10px] font-semibold text-[var(--hud-muted)]">
                              {sk.stat}
                            </span>
                            {sk.basic && (
                              <span className="border border-[var(--hud-accent-line)]/50 bg-[var(--hud-accent-navy)] px-1.5 py-0.5 font-cyber-ui text-[10px] font-semibold text-[var(--hud-accent)]">
                                BASIC
                              </span>
                            )}
                            {sk.cost === 2 && (
                              <span className="border border-[var(--hud-warn)]/50 bg-[var(--hud-warn)]/10 px-1.5 py-0.5 font-cyber-data text-[10px] text-[var(--hud-warn)]">
                                x2 pts
                              </span>
                            )}
                          </div>
                          <p className="mt-0.5 truncate font-cyber-ui text-xs text-[var(--hud-muted)]">{sk.summary}</p>
                        </div>

                        <div className="flex shrink-0 items-center gap-3">
                          <span className="font-cyber-ui text-[11px] text-[var(--hud-muted)]">
                            Base <strong className="font-cyber-data text-[var(--hud-accent)]">{baseTotal}</strong>
                          </span>
                          {method === "streetrat" ? (
                            <span className="w-8 text-center font-cyber-data text-sm font-bold text-[var(--hud-text)]">+{rank}</span>
                          ) : (
                            <div className="flex items-center gap-1 font-cyber-data">
                              <button
                                type="button"
                                disabled={lockedMedtechSkill || rank <= minRank}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  updateRank(rank - 1);
                                }}
                                className="cyber-btn-tac cp-fx-hover px-2 py-0.5 font-cyber-data disabled:opacity-30"
                              >-</button>
                              <span className="w-6 text-center font-bold text-[var(--hud-text)]">{rank}</span>
                              <button
                                type="button"
                                disabled={lockedMedtechSkill || rank >= maxRank}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  updateRank(rank + 1);
                                }}
                                className="cyber-btn-tac cp-fx-hover px-2 py-0.5 font-cyber-data disabled:opacity-30"
                              >+</button>
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* STEP 4: BACKSTORY, LIFEPATH & ESTABLISHED HISTORY */}
            {step === "lifepath" && (
              <div className="space-y-5">
                <div className="flex flex-wrap items-center justify-between gap-2 border border-[var(--hud-line)] bg-[#5a0b1c]/35 p-3">
                  <div>
                    <div className="font-cyber-display text-xs font-semibold uppercase tracking-wider text-[var(--hud-text)]">
                      Lifepath, Backstory &amp; Established History
                    </div>
                    <p className="font-cyber-ui text-[11px] text-[var(--hud-muted)]">
                      Roll origin tables or customize freely—the AI GM reads every ally, grudge, and backstory line from Turn 1.
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    <HudButton
                      variant="tactical"
                      size="sm"
                      onClick={rollFullLifepath}
                    >
                      <Dices className="h-3.5 w-3.5 text-[var(--hud-accent)]" /> Roll Full Lifepath
                    </HudButton>
                    <HudButton
                      variant="tactical"
                      size="sm"
                      onClick={() => weaveStarterBackstory()}
                    >
                      <Wand2 className="h-3.5 w-3.5 text-[var(--hud-accent)]" /> Weave Starter Bio
                    </HudButton>
                  </div>
                </div>

                {/* A. Written Backstory & Established History */}
                <div className="space-y-3 border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] p-3.5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="font-cyber-display text-xs font-semibold uppercase tracking-wider text-[var(--hud-accent)]">
                      Written Backstory &amp; Already-Established History
                    </div>
                    <HudButton
                      variant="tactical"
                      size="xs"
                      disabled={aiBusy}
                      onClick={() => void handleAiAssist("bio", "scratch")}
                    >
                      <Sparkles className="h-3 w-3 text-[var(--hud-accent)]" />
                      {aiBusyKey === "bio:scratch:all" ? "Generating…" : "Generate from Scratch"}
                    </HudButton>
                  </div>
                  {aiError && (
                    <div className="border border-[var(--hud-primary-bright)]/60 bg-[var(--hud-row)] px-2.5 py-1.5 font-cyber-ui text-[11px] text-rose-200">
                      {aiError}
                    </div>
                  )}
                  <div>
                    <label className="mb-1 block font-cyber-ui text-[11px] font-medium text-[var(--hud-muted)]">
                      Optional Prompt / Direction (stays faithful to your Role, STATs, Skills, Gear &amp; Corebook)
                    </label>
                    <input
                      type="text"
                      value={aiBioGuidance}
                      onChange={(e) => setAiBioGuidance(e.target.value)}
                      placeholder="e.g. Smuggler running spare parts out of Rancho Coronado, owes a local ripperdoc…"
                      className="w-full border border-[var(--hud-line-soft)] bg-black/60 px-3 py-1.5 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                    />
                  </div>
                  <div>
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <label className="block font-cyber-ui text-xs font-medium text-[var(--hud-text)]">
                        One-Line Concept
                      </label>
                      <FieldAiActions
                        label="Concept"
                        disabled={aiBusy}
                        busyAction={busyFor("bio", "concept")}
                        onImprove={() => void handleAiAssist("bio", "expand", "concept")}
                        onRegen={() => void handleAiAssist("bio", "scratch", "concept")}
                      />
                    </div>
                    <input
                      type="text"
                      value={conceptTagline}
                      onChange={(e) => setConceptTagline(e.target.value)}
                      placeholder="Short one-line character hook or street reputation"
                      className="w-full border border-[var(--hud-line-soft)] bg-black/60 px-3 py-1.5 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                    />
                  </div>
                  <div>
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <label className="block font-cyber-ui text-xs font-medium text-[var(--hud-text)]">
                        Character Backstory (Where do you come from? What shaped you?)
                      </label>
                      <FieldAiActions
                        label="Backstory"
                        disabled={aiBusy}
                        busyAction={busyFor("bio", "summary")}
                        onImprove={() => void handleAiAssist("bio", "expand", "summary")}
                        onRegen={() => void handleAiAssist("bio", "scratch", "summary")}
                      />
                    </div>
                    <textarea
                      rows={3}
                      value={backstorySummary}
                      onChange={(e) => setBackstorySummary(e.target.value)}
                      placeholder="Write a few sentences about your life before Session 1, or click 'Roll Full Lifepath' / 'Weave Starter Bio'…"
                      className="w-full border border-[var(--hud-line-soft)] bg-black/60 px-3 py-2 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                    />
                  </div>
                  <div>
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <label className="block font-cyber-ui text-xs font-medium text-[var(--hud-text)]">
                        Already-Established Night City History (Past gigs, crew ties, favors owed, local turf)
                      </label>
                      <FieldAiActions
                        label="Established History"
                        disabled={aiBusy}
                        busyAction={busyFor("bio", "established_history")}
                        onImprove={() => void handleAiAssist("bio", "expand", "established_history")}
                        onRegen={() => void handleAiAssist("bio", "scratch", "established_history")}
                      />
                    </div>
                    <textarea
                      rows={2}
                      value={establishedHistory}
                      onChange={(e) => setEstablishedHistory(e.target.value)}
                      placeholder="e.g. Owes 200 eb to Mama Welles, regular at the Afterlife, survived a Militech convoy ambush last winter…"
                      className="w-full border border-[var(--hud-line-soft)] bg-black/60 px-3 py-2 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                    />
                  </div>
                  <div>
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <label className="block font-cyber-ui text-xs font-medium text-[var(--hud-text)]">
                        Signature Look &amp; Mannerisms
                      </label>
                      <FieldAiActions
                        label="Signature Look"
                        disabled={aiBusy}
                        busyAction={busyFor("bio", "appearance")}
                        onImprove={() => void handleAiAssist("bio", "expand", "appearance")}
                        onRegen={() => void handleAiAssist("bio", "scratch", "appearance")}
                      />
                    </div>
                    <input
                      type="text"
                      value={appearanceNotes}
                      onChange={(e) => setAppearanceNotes(e.target.value)}
                      placeholder="e.g. Scuffed red leather jacket, silver nose ring, faint burn scar across left cheek"
                      className="w-full border border-[var(--hud-line-soft)] bg-black/60 px-3 py-1.5 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                    />
                  </div>
                </div>

                {/* B. General Lifepath Tables */}
                <div className="space-y-3 border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] p-3.5">
                  <div className="font-cyber-display text-xs font-semibold uppercase tracking-wider text-[var(--hud-text)]">
                    Street Origins &amp; Background
                  </div>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <div>
                      <div className="mb-1 flex items-center justify-between gap-2">
                        <label className="cyber-field-label mb-0">Cultural Region</label>
                        <button
                          type="button"
                          onClick={() => {
                            const reg = pickRandom(refData?.cultural_regions ?? []);
                            if (reg) {
                              setCulturalRegion(reg.region);
                              setCulturalLanguage(pickRandom(reg.languages));
                            }
                          }}
                          className="font-cyber-data text-[11px] text-[var(--hud-accent)] hover:text-white"
                        >d10 ↻</button>
                      </div>
                      <select
                        value={culturalRegion}
                        onChange={(e) => {
                          setCulturalRegion(e.target.value);
                          const match = refData?.cultural_regions.find((r) => r.region === e.target.value);
                          if (match?.languages.length) setCulturalLanguage(match.languages[0]);
                        }}
                        className="cyber-input px-2.5 py-1.5"
                      >
                        {(refData?.cultural_regions ?? []).map((r) => (
                          <option key={r.region} value={r.region}>{r.region}</option>
                        ))}
                      </select>
                    </div>

                    <div>
                      <label className="cyber-field-label">
                        Native Language (+4 Free Skill!)
                      </label>
                      <input
                        type="text"
                        value={culturalLanguage}
                        onChange={(e) => setCulturalLanguage(e.target.value)}
                        list="cultural-lang-options"
                        className="cyber-input px-2.5 py-1.5"
                      />
                      <datalist id="cultural-lang-options">
                        {(refData?.cultural_regions.find((r) => r.region === culturalRegion)?.languages ?? []).map((l) => (
                          <option key={l} value={l} />
                        ))}
                      </datalist>
                      {culturalLanguageOverlap && (
                        <p className="mt-1 font-cyber-ui text-[10px] text-[var(--hud-warn)]">
                          Overlaps paid Language ({culturalLanguage}) in Step 3 — pick another native language for +4 free cleanly.
                        </p>
                      )}
                    </div>

                    {(() => {
                      const sourceSkills =
                        method === "streetrat" || method === "edgerunner"
                          ? Object.keys(roleInfo?.skills ?? {})
                          : Object.keys(customSkills);
                      const bases = SPECIALIZATION_BASES.filter((base) =>
                        sourceSkills.some((sk) => {
                          const cleaned = sk.replace(/\s*\(choose\s*1\)\s*/i, "").trim();
                          return (
                            cleaned.toLowerCase() === base.toLowerCase() &&
                            (method === "streetrat" || method === "edgerunner"
                              ? sk.toLowerCase().includes("choose") || !sk.includes("(")
                              : !sk.includes("("))
                          );
                        }),
                      );
                      return bases.map((specBase) => (
                        <div key={specBase}>
                          <label className="cyber-field-label">
                            {specBase} Specialization
                          </label>
                          {specializationOptions[specBase].length ? (
                            <select
                              aria-label={`${specBase} Specialization`}
                              value={specializations[specBase] ?? specializationOptions[specBase][0]}
                              onChange={(e) => setSpecializations((p) => ({ ...p, [specBase]: e.target.value }))}
                              className="cyber-input px-2.5 py-1.5"
                            >
                              {specializationOptions[specBase].map((opt) => (
                                <option key={opt} value={opt}>{opt}</option>
                              ))}
                            </select>
                          ) : (
                            <input
                              type="text"
                              aria-label={`${specBase} Specialization`}
                              value={specializations[specBase] ?? ""}
                              onChange={(e) => setSpecializations((p) => ({ ...p, [specBase]: e.target.value }))}
                              placeholder="Your specialization…"
                              className="cyber-input px-2.5 py-1.5"
                            />
                          )}
                        </div>
                      ));
                    })()}

                    {([
                      { key: "personality", label: "Personality", val: personality, set: setPersonality },
                      { key: "clothing_style", label: "Clothing Style", val: clothingStyle, set: setClothingStyle },
                      { key: "hairstyle", label: "Hairstyle", val: hairstyle, set: setHairstyle },
                      { key: "affectation", label: "Signature Affectation", val: affectation, set: setAffectation },
                      { key: "value_most", label: "What Do You Value Most?", val: valueMost, set: setValueMost },
                      { key: "feelings_about_people", label: "Feelings About People", val: feelingsAboutPeople, set: setFeelingsAboutPeople },
                      { key: "valued_person", label: "Most Valued Person", val: valuedPerson, set: setValuedPerson },
                      { key: "valued_possession", label: "Most Valued Possession", val: valuedPossession, set: setValuedPossession },
                      { key: "family_background", label: "Family Background", val: familyBackground, set: setFamilyBackground },
                      { key: "childhood_environment", label: "Childhood Environment", val: childhoodEnv, set: setChildhoodEnv },
                      { key: "family_crisis", label: "Family Crisis", val: familyCrisis, set: setFamilyCrisis },
                      { key: "life_goal", label: "Life Goal", val: lifeGoal, set: setLifeGoal },
                    ] as const).map((field) => {
                      const opts = refData?.lifepath_tables[field.key] ?? [];
                      const isCustom =
                        Boolean(customLifepathFields[field.key]) ||
                        (field.val !== "" && !opts.includes(field.val));
                      return (
                        <div key={field.key}>
                          <div className="mb-1 flex items-center justify-between gap-2">
                            <label className="cyber-field-label mb-0">{field.label}</label>
                            <div className="flex items-center gap-2">
                              <button
                                type="button"
                                onClick={() =>
                                  setCustomLifepathFields((p) => ({ ...p, [field.key]: !isCustom }))
                                }
                                className="font-cyber-ui text-[10px] text-[var(--hud-muted)] hover:text-[var(--hud-accent)]"
                              >
                                {isCustom ? "Presets" : "Custom ✎"}
                              </button>
                              {opts.length > 0 && (
                                <button
                                  type="button"
                                  onClick={() => {
                                    field.set(pickRandom(opts));
                                    setCustomLifepathFields((p) => ({ ...p, [field.key]: false }));
                                  }}
                                  className="font-cyber-data text-[11px] text-[var(--hud-accent)] hover:text-white"
                                >
                                  d{opts.length} ↻
                                </button>
                              )}
                            </div>
                          </div>
                          {!isCustom ? (
                            <select
                              value={opts.includes(field.val) ? field.val : (opts[0] ?? "__custom__")}
                              onChange={(e) => {
                                if (e.target.value === "__custom__") {
                                  setCustomLifepathFields((p) => ({ ...p, [field.key]: true }));
                                } else {
                                  field.set(e.target.value);
                                }
                              }}
                              className="cyber-input px-2.5 py-1.5"
                            >
                              {opts.map((o, i) => (
                                <option key={i} value={o}>{o}</option>
                              ))}
                              <option value="__custom__">Custom…</option>
                            </select>
                          ) : (
                            <input
                              type="text"
                              value={field.val}
                              onChange={(e) => field.set(e.target.value)}
                              placeholder={`Custom ${field.label.toLowerCase()}…`}
                              className="cyber-input px-2.5 py-1.5"
                            />
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* C. Role-Specific Lifepath */}
                {roleInfo && roleInfo.role_lifepath.length > 0 && (
                  <div className="space-y-2.5 border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] p-3.5">
                    <div className="font-cyber-display text-xs font-semibold uppercase tracking-wider text-[var(--hud-warn)]">
                      {selectedRole} Role Lifepath
                    </div>
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                      {roleInfo.role_lifepath.map((f) => {
                        const opts = f.options;
                        const val = roleLifepath[f.key] ?? "";
                        const lpKey = `role:${f.key}`;
                        const isCustom =
                          Boolean(customLifepathFields[lpKey]) ||
                          (val !== "" && !opts.includes(val));
                        return (
                          <div key={f.key}>
                            <div className="mb-1 flex items-center justify-between gap-2">
                              <label className="cyber-field-label mb-0">{f.label}</label>
                              <div className="flex items-center gap-2">
                                <button
                                  type="button"
                                  onClick={() =>
                                    setCustomLifepathFields((p) => ({ ...p, [lpKey]: !isCustom }))
                                  }
                                  className="font-cyber-ui text-[10px] text-[var(--hud-muted)] hover:text-[var(--hud-accent)]"
                                >
                                  {isCustom ? "Presets" : "Custom ✎"}
                                </button>
                                <button
                                  type="button"
                                  onClick={() => {
                                    setRoleLifepath((p) => ({ ...p, [f.key]: pickRandom(opts) }));
                                    setCustomLifepathFields((p) => ({ ...p, [lpKey]: false }));
                                  }}
                                  className="font-cyber-data text-[11px] text-[var(--hud-accent)] hover:text-white"
                                >Roll ↻</button>
                              </div>
                            </div>
                            {!isCustom ? (
                              <select
                                value={opts.includes(val) ? val : (opts[0] ?? "__custom__")}
                                onChange={(e) => {
                                  if (e.target.value === "__custom__") {
                                    setCustomLifepathFields((p) => ({ ...p, [lpKey]: true }));
                                  } else {
                                    setRoleLifepath((p) => ({ ...p, [f.key]: e.target.value }));
                                  }
                                }}
                                className="cyber-input px-2.5 py-1.5"
                              >
                                {opts.map((o, i) => (
                                  <option key={i} value={o}>{o}</option>
                                ))}
                                <option value="__custom__">Custom…</option>
                              </select>
                            ) : (
                              <input
                                type="text"
                                value={val}
                                onChange={(e) => setRoleLifepath((p) => ({ ...p, [f.key]: e.target.value }))}
                                placeholder={`Custom ${f.label.toLowerCase()}…`}
                                className="cyber-input px-2.5 py-1.5"
                              />
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* D. Established Contacts: Friends, Enemies, Tragic Loves */}
                <div className="space-y-3 border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] p-3.5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="inline-flex items-center gap-1.5 font-cyber-display text-xs font-semibold uppercase tracking-wider text-[var(--hud-text)]">
                      <Users className="h-3.5 w-3.5 text-[var(--hud-accent)]" />
                      Friends, Enemies &amp; Past Romances
                    </span>
                    <div className="flex flex-wrap gap-1.5">
                      <HudButton
                        variant="tactical"
                        size="xs"
                        disabled={aiBusy}
                        onClick={() => void handleAiAssist("contacts", "scratch")}
                      >
                        <Sparkles className="h-3 w-3 text-[var(--hud-accent)]" />
                        {aiBusyKey === "contacts:scratch:all" ? "Writing…" : "Generate Contacts"}
                      </HudButton>
                      <HudButton
                        variant="tactical"
                        size="xs"
                        onClick={() =>
                          setFriends((p) => [
                            ...p,
                            {
                              name: `Ally #${p.length + 1}`,
                              relationship: pickRandom(refData?.lifepath_tables.friend_relationship ?? [""]),
                              note: "Has your back when things go sideways.",
                            },
                          ])
                        }
                      >
                        <Plus className="h-3 w-3 text-[var(--hud-ok)]" /> Friend
                      </HudButton>
                      <HudButton
                        variant="tactical"
                        size="xs"
                        onClick={() =>
                          setEnemies((p) => [
                            ...p,
                            {
                              who: pickRandom(refData?.lifepath_tables.enemy_who ?? [""]),
                              name: `Rival #${p.length + 1}`,
                              wronged: "They wronged me",
                              cause: pickRandom(refData?.lifepath_tables.enemy_cause ?? [""]),
                              backup: pickRandom(refData?.lifepath_tables.enemy_backup ?? [""]),
                              revenge: pickRandom(refData?.lifepath_tables.sweet_revenge ?? [""]),
                            },
                          ])
                        }
                      >
                        <Plus className="h-3 w-3 text-[var(--hud-primary-bright)]" /> Enemy
                      </HudButton>
                      <HudButton
                        variant="tactical"
                        size="xs"
                        onClick={() =>
                          setLoveAffairs((p) => [
                            ...p,
                            {
                              name: `Ex #${p.length + 1}`,
                              outcome: pickRandom(refData?.lifepath_tables.tragic_love ?? [""]),
                            },
                          ])
                        }
                      >
                        <Plus className="h-3 w-3 text-[var(--hud-warn)]" /> Tragic Love
                      </HudButton>
                    </div>
                  </div>
                  <input
                    type="text"
                    value={aiContactsGuidance}
                    onChange={(e) => setAiContactsGuidance(e.target.value)}
                    placeholder="Optional AI direction for Friends, Enemies & Romances (e.g. a Chromatic Rock fixer friend, Maelstrom rival)…"
                    className="w-full border border-[var(--hud-line-soft)] bg-black/60 px-2.5 py-1.5 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                  />

                  {friends.length === 0 && enemies.length === 0 && loveAffairs.length === 0 && (
                    <p className="font-cyber-ui text-xs text-[var(--hud-muted)]">
                      No friends, enemies, or tragic romances added yet. Add your own NPCs or click Roll Full Lifepath!
                    </p>
                  )}

                  {friends.length > 0 && (
                    <div className="space-y-1.5">
                      <div className="flex items-center justify-between">
                        <span className="font-cyber-ui text-[11px] font-semibold text-[var(--hud-ok)]">
                          Friends ({friends.length})
                        </span>
                      </div>
                      {friends.map((fr, idx) => (
                        <div key={idx} className="grid grid-cols-1 gap-2 border border-[var(--hud-ok)]/40 bg-[var(--hud-row)] p-2.5 sm:grid-cols-12">
                          <div className="flex items-center gap-1 sm:col-span-3">
                            <input
                              type="text"
                              value={fr.name}
                              onChange={(e) => setFriends((p) => p.map((x, i) => (i === idx ? { ...x, name: e.target.value } : x)))}
                              placeholder="Friend name"
                              className="min-w-0 flex-1 border border-[var(--hud-line-soft)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                            />
                            <FieldAiActions
                              compact
                              label={`Friend ${idx + 1} Name`}
                              disabled={aiBusy}
                              busyAction={busyFor("contacts", "friends", idx, "name")}
                              onImprove={() => void handleAiAssist("contacts", "expand", "friends", idx, "name")}
                              onRegen={() => void handleAiAssist("contacts", "scratch", "friends", idx, "name")}
                            />
                          </div>
                          <div className="flex items-center gap-1 sm:col-span-4">
                            <input
                              type="text"
                              value={fr.relationship}
                              onChange={(e) => setFriends((p) => p.map((x, i) => (i === idx ? { ...x, relationship: e.target.value } : x)))}
                              placeholder="Relationship"
                              className="min-w-0 flex-1 border border-[var(--hud-line-soft)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                            />
                            <FieldAiActions
                              compact
                              label={`Friend ${idx + 1} Relationship`}
                              disabled={aiBusy}
                              busyAction={busyFor("contacts", "friends", idx, "relationship")}
                              onImprove={() => void handleAiAssist("contacts", "expand", "friends", idx, "relationship")}
                              onRegen={() => void handleAiAssist("contacts", "scratch", "friends", idx, "relationship")}
                            />
                          </div>
                          <div className="flex items-center gap-1 sm:col-span-4">
                            <input
                              type="text"
                              value={fr.note}
                              onChange={(e) => setFriends((p) => p.map((x, i) => (i === idx ? { ...x, note: e.target.value } : x)))}
                              placeholder="Shared history / favor"
                              className="min-w-0 flex-1 border border-[var(--hud-line-soft)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                            />
                            <FieldAiActions
                              compact
                              label={`Friend ${idx + 1} Note`}
                              disabled={aiBusy}
                              busyAction={busyFor("contacts", "friends", idx, "note")}
                              onImprove={() => void handleAiAssist("contacts", "expand", "friends", idx, "note")}
                              onRegen={() => void handleAiAssist("contacts", "scratch", "friends", idx, "note")}
                            />
                          </div>
                          <button
                            type="button"
                            onClick={() => setFriends((p) => p.filter((_, i) => i !== idx))}
                            className="justify-self-end text-[var(--hud-muted)] hover:text-[var(--hud-primary-bright)] sm:col-span-1"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      ))}
                    </div>
                  )}

                  {enemies.length > 0 && (
                    <div className="space-y-1.5">
                      <div className="flex items-center justify-between">
                        <span className="font-cyber-ui text-[11px] font-semibold text-[var(--hud-primary-bright)]">
                          Enemies ({enemies.length})
                        </span>
                      </div>
                      {enemies.map((en, idx) => (
                        <div key={idx} className="space-y-1.5 border border-[var(--hud-line)] bg-[var(--hud-row)] p-2.5 text-xs">
                          <div className="flex flex-wrap items-center gap-2">
                            <div className="flex items-center gap-1">
                              <input
                                type="text"
                                value={en.name}
                                onChange={(e) => setEnemies((p) => p.map((x, i) => (i === idx ? { ...x, name: e.target.value } : x)))}
                                placeholder="Enemy name"
                                className="border border-[var(--hud-line-soft)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                              />
                              <FieldAiActions
                                compact
                                label={`Enemy ${idx + 1} Name`}
                                disabled={aiBusy}
                                busyAction={busyFor("contacts", "enemies", idx, "name")}
                                onImprove={() => void handleAiAssist("contacts", "expand", "enemies", idx, "name")}
                                onRegen={() => void handleAiAssist("contacts", "scratch", "enemies", idx, "name")}
                              />
                            </div>
                            <div className="flex items-center gap-1">
                              <input
                                type="text"
                                value={en.who}
                                onChange={(e) => setEnemies((p) => p.map((x, i) => (i === idx ? { ...x, who: e.target.value } : x)))}
                                placeholder="Who they are"
                                className="border border-[var(--hud-line-soft)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                              />
                              <FieldAiActions
                                compact
                                label={`Enemy ${idx + 1} Archetype`}
                                disabled={aiBusy}
                                busyAction={busyFor("contacts", "enemies", idx, "who")}
                                onImprove={() => void handleAiAssist("contacts", "expand", "enemies", idx, "who")}
                                onRegen={() => void handleAiAssist("contacts", "scratch", "enemies", idx, "who")}
                              />
                            </div>
                            <select
                              value={en.wronged}
                              onChange={(e) =>
                                setEnemies((p) =>
                                  p.map((x, i) => (i === idx ? { ...x, wronged: e.target.value as EnemyEntry["wronged"] } : x)),
                                )
                              }
                              className="border border-[var(--hud-line-soft)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                            >
                              <option value="They wronged me">They wronged me</option>
                              <option value="I wronged them">I wronged them</option>
                            </select>
                            <button
                              type="button"
                              onClick={() => setEnemies((p) => p.filter((_, i) => i !== idx))}
                              className="ml-auto text-[var(--hud-muted)] hover:text-[var(--hud-primary-bright)]"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                          <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-3">
                            <div className="flex items-center gap-1">
                              <input
                                type="text"
                                value={en.cause}
                                onChange={(e) => setEnemies((p) => p.map((x, i) => (i === idx ? { ...x, cause: e.target.value } : x)))}
                                placeholder="What caused it"
                                className="min-w-0 flex-1 border border-[var(--hud-line-soft)] bg-black/60 px-2 py-1 font-cyber-ui text-[11px] text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                              />
                              <FieldAiActions
                                compact
                                label={`Enemy ${idx + 1} Cause`}
                                disabled={aiBusy}
                                busyAction={busyFor("contacts", "enemies", idx, "cause")}
                                onImprove={() => void handleAiAssist("contacts", "expand", "enemies", idx, "cause")}
                                onRegen={() => void handleAiAssist("contacts", "scratch", "enemies", idx, "cause")}
                              />
                            </div>
                            <div className="flex items-center gap-1">
                              <input
                                type="text"
                                value={en.backup}
                                onChange={(e) => setEnemies((p) => p.map((x, i) => (i === idx ? { ...x, backup: e.target.value } : x)))}
                                placeholder="What they can throw at you"
                                className="min-w-0 flex-1 border border-[var(--hud-line-soft)] bg-black/60 px-2 py-1 font-cyber-ui text-[11px] text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                              />
                              <FieldAiActions
                                compact
                                label={`Enemy ${idx + 1} Backup`}
                                disabled={aiBusy}
                                busyAction={busyFor("contacts", "enemies", idx, "backup")}
                                onImprove={() => void handleAiAssist("contacts", "expand", "enemies", idx, "backup")}
                                onRegen={() => void handleAiAssist("contacts", "scratch", "enemies", idx, "backup")}
                              />
                            </div>
                            <div className="flex items-center gap-1">
                              <input
                                type="text"
                                value={en.revenge}
                                onChange={(e) => setEnemies((p) => p.map((x, i) => (i === idx ? { ...x, revenge: e.target.value } : x)))}
                                placeholder="Sweet revenge"
                                className="min-w-0 flex-1 border border-[var(--hud-line-soft)] bg-black/60 px-2 py-1 font-cyber-ui text-[11px] text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                              />
                              <FieldAiActions
                                compact
                                label={`Enemy ${idx + 1} Revenge`}
                                disabled={aiBusy}
                                busyAction={busyFor("contacts", "enemies", idx, "revenge")}
                                onImprove={() => void handleAiAssist("contacts", "expand", "enemies", idx, "revenge")}
                                onRegen={() => void handleAiAssist("contacts", "scratch", "enemies", idx, "revenge")}
                              />
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {loveAffairs.length > 0 && (
                    <div className="space-y-1.5">
                      <div className="flex items-center justify-between">
                        <span className="font-cyber-ui text-[11px] font-semibold text-[var(--hud-warn)]">
                          Past Romances ({loveAffairs.length})
                        </span>
                      </div>
                      {loveAffairs.map((lv, idx) => (
                        <div key={idx} className="flex flex-wrap items-center gap-2 border border-[var(--hud-line-soft)] bg-[var(--hud-row)] p-2.5 text-xs">
                          <div className="flex items-center gap-1">
                            <input
                              type="text"
                              value={lv.name}
                              onChange={(e) => setLoveAffairs((p) => p.map((x, i) => (i === idx ? { ...x, name: e.target.value } : x)))}
                              placeholder="Lover's name"
                              className="w-40 border border-[var(--hud-line-soft)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                            />
                            <FieldAiActions
                              compact
                              label={`Romance ${idx + 1} Name`}
                              disabled={aiBusy}
                              busyAction={busyFor("contacts", "tragic_love_affairs", idx, "name")}
                              onImprove={() => void handleAiAssist("contacts", "expand", "tragic_love_affairs", idx, "name")}
                              onRegen={() => void handleAiAssist("contacts", "scratch", "tragic_love_affairs", idx, "name")}
                            />
                          </div>
                          <div className="flex min-w-[200px] flex-1 items-center gap-1">
                            <input
                              type="text"
                              value={lv.outcome}
                              onChange={(e) => setLoveAffairs((p) => p.map((x, i) => (i === idx ? { ...x, outcome: e.target.value } : x)))}
                              placeholder="What happened?"
                              className="min-w-0 flex-1 border border-[var(--hud-line-soft)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                            />
                            <FieldAiActions
                              compact
                              label={`Romance ${idx + 1} Outcome`}
                              disabled={aiBusy}
                              busyAction={busyFor("contacts", "tragic_love_affairs", idx, "outcome")}
                              onImprove={() => void handleAiAssist("contacts", "expand", "tragic_love_affairs", idx, "outcome")}
                              onRegen={() => void handleAiAssist("contacts", "scratch", "tragic_love_affairs", idx, "outcome")}
                            />
                          </div>
                          <button
                            type="button"
                            onClick={() => setLoveAffairs((p) => p.filter((_, i) => i !== idx))}
                            className="text-[var(--hud-muted)] hover:text-[var(--hud-primary-bright)]"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* E. Street Reputation & Starting Trauma / Debt Hooks */}
                <div className="space-y-2.5 border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] p-3.5">
                  <button
                    type="button"
                    onClick={() => setShowRepHooks((v) => !v)}
                    className="flex w-full items-center justify-between font-cyber-display text-xs font-semibold uppercase tracking-wider text-[var(--hud-text)] hover:text-[var(--hud-accent)]"
                  >
                    <span>Street Reputation &amp; Starting Hooks</span>
                    <span className="font-cyber-ui text-[10px] text-[var(--hud-accent)]">{showRepHooks ? "▲ Hide" : "▼ Expand"}</span>
                  </button>
                  {showRepHooks && (
                    <div className="grid grid-cols-1 gap-2.5 border-t border-[var(--hud-line-soft)] pt-2.5 sm:grid-cols-2">
                      <div>
                        <label className="mb-1 block font-cyber-ui text-[11px] font-semibold text-[var(--hud-text)]">
                          Starting Reputation (0–10, default 0)
                        </label>
                        <input
                          type="number"
                          min={0}
                          max={10}
                          aria-label="Starting Reputation"
                          value={reputation}
                          onChange={(e) => setReputation(Math.max(0, Math.min(10, parseInt(e.target.value, 10) || 0)))}
                          className="w-24 border border-[var(--hud-line-soft)] bg-black/60 px-2 py-1 font-cyber-data text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                        />
                      </div>
                      <div>
                        <div className="mb-1 flex items-center justify-between gap-2">
                          <label className="block font-cyber-ui text-[11px] font-semibold text-[var(--hud-text)]">
                            Reputation Reason / Word on the Street
                          </label>
                          <FieldAiActions
                            compact
                            label="Reputation Reason"
                            disabled={aiBusy}
                            busyAction={busyFor("bio", "reputation_note")}
                            onImprove={() => void handleAiAssist("bio", "expand", "reputation_note")}
                            onRegen={() => void handleAiAssist("bio", "scratch", "reputation_note")}
                          />
                        </div>
                        <input
                          type="text"
                          value={reputationNote}
                          onChange={(e) => setReputationNote(e.target.value)}
                          placeholder="e.g. Survived the Watson tunnel collapse"
                          className="w-full border border-[var(--hud-line-soft)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                        />
                      </div>
                      <div>
                        <div className="mb-1 flex items-center justify-between gap-2">
                          <label className="block font-cyber-ui text-[11px] font-semibold text-[var(--hud-text)]">
                            Trauma / Cyberpsychosis Scar
                          </label>
                          <FieldAiActions
                            compact
                            label="Trauma Hook"
                            disabled={aiBusy}
                            busyAction={busyFor("bio", "trauma_hook")}
                            onImprove={() => void handleAiAssist("bio", "expand", "trauma_hook")}
                            onRegen={() => void handleAiAssist("bio", "scratch", "trauma_hook")}
                          />
                        </div>
                        <input
                          type="text"
                          value={traumaHook}
                          onChange={(e) => setTraumaHook(e.target.value)}
                          placeholder="e.g. Haunted by 4th Corporate War clinic fire"
                          className="w-full border border-[var(--hud-line-soft)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                        />
                      </div>
                      <div>
                        <div className="mb-1 flex items-center justify-between gap-2">
                          <label className="block font-cyber-ui text-[11px] font-semibold text-[var(--hud-text)]">
                            Addiction / Vice
                          </label>
                          <FieldAiActions
                            compact
                            label="Addiction Hook"
                            disabled={aiBusy}
                            busyAction={busyFor("bio", "addiction_hook")}
                            onImprove={() => void handleAiAssist("bio", "expand", "addiction_hook")}
                            onRegen={() => void handleAiAssist("bio", "scratch", "addiction_hook")}
                          />
                        </div>
                        <input
                          type="text"
                          value={addictionHook}
                          onChange={(e) => setAddictionHook(e.target.value)}
                          placeholder="e.g. Synthcoke or Smash habit"
                          className="w-full border border-[var(--hud-line-soft)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                        />
                      </div>
                      <div className="sm:col-span-2">
                        <div className="mb-1 flex items-center justify-between gap-2">
                          <label className="block font-cyber-ui text-[11px] font-semibold text-[var(--hud-text)]">
                            Starting Debt / Obligation
                          </label>
                          <FieldAiActions
                            compact
                            label="Debt Hook"
                            disabled={aiBusy}
                            busyAction={busyFor("bio", "debt_hook")}
                            onImprove={() => void handleAiAssist("bio", "expand", "debt_hook")}
                            onRegen={() => void handleAiAssist("bio", "scratch", "debt_hook")}
                          />
                        </div>
                        <input
                          type="text"
                          value={debtHook}
                          onChange={(e) => setDebtHook(e.target.value)}
                          placeholder="e.g. Owes 500 eb to a Kabuki ripperdoc"
                          className="w-full border border-[var(--hud-line-soft)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                        />
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* STEP 5: GEAR, ARMOR & CYBERWARE */}
            {step === "gear" && (
              <div className="space-y-4">
                {/* Housing, Lifestyle & Trauma Team Coverage */}
                <div className="space-y-2.5 border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-cyber-display text-xs font-semibold uppercase tracking-wider text-[var(--hud-accent)]">
                      Housing, Lifestyle &amp; Trauma Team
                    </span>
                    <span className="font-cyber-ui text-[11px] text-[var(--hud-muted)]">
                      Month 1 baseline rent paid; monthly upkeep applies from Month 2.
                    </span>
                  </div>
                  <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
                    <div>
                      <label className="mb-1 block font-cyber-ui text-[11px] font-semibold text-[var(--hud-text)]">Housing</label>
                      <select
                        aria-label="Character Housing"
                        value={housing}
                        onChange={(e) => setHousing(e.target.value)}
                        className="w-full border border-[var(--hud-line-soft)] bg-black/60 px-2 py-1.5 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                      >
                        {(refData?.housing_tiers ?? [])
                          .filter((h) => !h.exec_only || selectedRole === "Exec")
                          .map((h) => (
                            <option key={h.id} value={h.id}>
                              {h.name} ({h.monthly_eb} eb/mo)
                            </option>
                          ))}
                      </select>
                    </div>
                    <div>
                      <label className="mb-1 block font-cyber-ui text-[11px] font-semibold text-[var(--hud-text)]">Lifestyle</label>
                      <select
                        aria-label="Character Lifestyle"
                        value={lifestyle}
                        onChange={(e) => setLifestyle(e.target.value)}
                        className="w-full border border-[var(--hud-line-soft)] bg-black/60 px-2 py-1.5 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                      >
                        {(refData?.lifestyles ?? []).map((l) => (
                          <option key={l.id} value={l.id}>
                            {l.name} ({l.monthly_eb} eb/mo)
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="mb-1 block font-cyber-ui text-[11px] font-semibold text-[var(--hud-text)]">Trauma Team Plan</label>
                      <select
                        aria-label="Trauma Team Plan"
                        value={traumaTeam}
                        onChange={(e) => setTraumaTeam(e.target.value as "None" | "Silver" | "Executive")}
                        className="w-full border border-[var(--hud-line-soft)] bg-black/60 px-2 py-1.5 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                      >
                        <option value="None">None (0 eb/mo)</option>
                        {(["Silver", "Executive"] as const).map((plan) => {
                          const price = refData?.shop.service.find((x) => x.name.startsWith(`Trauma Team ${plan}`))?.cost_eb;
                          return (
                            <option key={plan} value={plan}>
                              Trauma Team {plan} (
                              {plan === "Silver" && selectedRole === "Exec" ? "Included for Exec" : `${price ?? "?"} eb/mo`})
                            </option>
                          );
                        })}
                      </select>
                    </div>
                  </div>
                </div>

                {(method === "streetrat" || method === "edgerunner") && roleInfo ? (
                  <div className="space-y-4">
                    <div className="flex flex-wrap items-center justify-between gap-2 border border-[var(--hud-line-soft)] bg-[var(--hud-row)] p-3">
                      <div>
                        <div className="font-cyber-display text-xs font-semibold uppercase tracking-wider text-[var(--hud-text)]">
                          {selectedRole} Starter Package (+500 eb pocket money)
                        </div>
                        <p className="font-cyber-ui text-[11px] text-[var(--hud-muted)]">
                          The Corebook gives you preset weapons, armor, outfit, and cyberware. Pick between any A/B options below.
                        </p>
                      </div>
                      <HazardBadge tone="warn">
                        Cyberware HL: -{gearSummary.totalHl} Humanity
                      </HazardBadge>
                    </div>

                    {(
                      [
                        ["weapons", "Weapons & Armor", roleInfo.starting_weapons],
                        ["cyberware", `Installed Cyberware (Total Humanity Loss: ${gearSummary.totalHl})`, roleInfo.starting_cyberware],
                        ["outfit", "Starting Outfit", roleInfo.starting_outfit],
                      ] as Array<[string, string, CreationKitEntry<CreationKitItem & Partial<CreationKitCyberware>>[]]>
                    ).map(([section, title, entries]) => (
                      <div key={section} className="space-y-2 border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] p-3">
                        <div className="font-cyber-display text-xs font-semibold uppercase tracking-wider text-[var(--hud-label)]">
                          {title}
                        </div>
                        {entries.map((entry, idx) => {
                          const picked = pickKit(section, [entry], { [`${section}-0`]: kitChoices[`${section}-${idx}`] })[0];
                          const options = entry.type === "choice" ? entry.options : [entry];
                          return (
                            <div key={idx} className="flex flex-wrap items-center gap-1.5 font-cyber-ui text-xs text-[var(--hud-text)]">
                              {entry.type === "choice" && <span className="font-medium text-[var(--hud-accent)]">Pick 1:</span>}
                              {options.map((opt) => {
                                const label = `${opt.item}${opt.qty > 1 ? ` ×${opt.qty}` : ""}${section === "cyberware" ? ` · HL ${opt.hl}` : ""}`;
                                const inspect = () => {
                                  if (opt.notes) {
                                    setInspector({ title: opt.item, subtitle: `${opt.install} · HL ${opt.hl}`, body: opt.notes });
                                  }
                                };
                                return entry.type === "choice" ? (
                                  <button
                                    key={opt.item}
                                    type="button"
                                    aria-pressed={picked.item === opt.item}
                                    onMouseEnter={inspect}
                                    onClick={() => setKitChoices((p) => ({ ...p, [`${section}-${idx}`]: opt.item }))}
                                    className={`border px-2.5 py-1 transition ${
                                      picked.item === opt.item
                                        ? "border-[var(--hud-accent-line)] bg-[var(--hud-accent-navy)] font-semibold text-[var(--hud-accent)]"
                                        : "border-[var(--hud-line-soft)] bg-black/55 hover:border-[var(--hud-line)]"
                                    }`}
                                  >
                                    {label}
                                  </button>
                                ) : (
                                  <span key={opt.item} onMouseEnter={inspect}>• {label}</span>
                                );
                              })}
                            </div>
                          );
                        })}
                        {section === "weapons" &&
                          roleInfo.starting_armor.map((a) => (
                            <div key={a} className="font-cyber-ui text-xs text-[var(--hud-accent)]">• {a}</div>
                          ))}
                      </div>
                    ))}
                  </div>
                ) : (
                  /* Complete Package Night Market Outfitter */
                  <div className="space-y-3">
                    {/* Sticky Outfitter Toolbar (keeps budget, search, sort & filters pinned without jumping) */}
                    <div className="sticky -top-4 sm:-top-5 z-10 -mx-4 sm:-mx-5 space-y-2.5 border-b border-[var(--hud-line)] bg-[var(--hud-bg)]/95 px-4 pt-3 pb-2.5 backdrop-blur sm:px-5">
                      <div className="flex flex-wrap items-center justify-between gap-2 border border-[var(--hud-line-soft)] bg-[var(--hud-row)] px-3 py-2">
                        <div className="font-cyber-ui text-xs">
                          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
                            <span>
                              Gear: <strong className={`font-cyber-data ${remainingGearEb < 0 ? "text-[var(--hud-primary-bright)]" : "text-[var(--hud-ok)]"}`}>{remainingGearEb} / 2,550 eb</strong>
                            </span>
                            <span>
                              Fashion: <strong className={`font-cyber-data ${remainingFashionEb < 0 ? "text-[var(--hud-primary-bright)]" : "text-[var(--hud-accent)]"}`}>{remainingFashionEb} / 800 eb</strong>
                            </span>
                            <span>
                              HL: <strong className="font-cyber-data text-[var(--hud-warn)]">-{gearSummary.totalHl}</strong>
                            </span>
                          </span>
                        </div>
                        <div className="flex flex-wrap items-center gap-1.5">
                          <HudButton
                            variant="tactical"
                            size="xs"
                            active={loadoutOpen}
                            onClick={() => setLoadoutOpen((v) => !v)}
                            className={
                              cyberwarePrereqWarnings.length > 0 || cyberwareSlotWarnings.length > 0 || cyberdeckSlotSummary.overCapacity
                                ? "border-[var(--hud-warn)]/70 text-[var(--hud-warn)]"
                                : ""
                            }
                          >
                            <Backpack className="h-3 w-3 text-[var(--hud-accent)]" />
                            Bag ({cartItems.reduce((a, b) => a + b.qty, 0) + selectedFashion.length})
                            {loadoutOpen ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                          </HudButton>
                          <HudButton
                            variant="tactical"
                            size="xs"
                            onClick={() => {
                              const wanted: Array<[CreationShopItem["category"], string, number]> = [
                                ["weapon", "Very Heavy Pistol", 1],
                                ["armor", "Light Armorjack", 2],
                                ["gear", "Agent", 1],
                                ["cyberware", "Neural Link", 1],
                              ];
                              setCartItems(
                                wanted.flatMap(([category, itemName, qty]) => {
                                  const item = refData?.shop[category].find((x) => x.name === itemName);
                                  if (!item) return [];
                                  const install = typeof item.stats.install === "string" ? item.stats.install : undefined;
                                  const sp = parseSpVal(item.stats) || undefined;
                                  return [{ name: item.name, category, cost_eb: item.cost_eb, hl: parseHlVal(item.stats), sp, install, qty }];
                                }),
                              );
                              setSelectedFashion([]);
                            }}
                          >
                            <Wand2 className="h-3 w-3 text-[var(--hud-accent)]" /> Starter Loadout
                          </HudButton>
                        </div>
                      </div>

                      {/* Collapsible Loadout Bag */}
                      {loadoutOpen && (
                        <div className="max-h-52 space-y-2 overflow-y-auto border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] p-2.5 text-xs">
                          {cartItems.length === 0 && selectedFashion.length === 0 ? (
                            <p className="font-cyber-ui text-[11px] text-[var(--hud-muted)]">
                              Your bag is empty. Add weapons, armor, cyberware, or fashion below.
                            </p>
                          ) : (
                            <div className="space-y-2">
                              <div className="flex items-center justify-between border-b border-[var(--hud-line-soft)] pb-1.5">
                                <span className="font-cyber-ui text-[10px] font-semibold uppercase tracking-wider text-[var(--hud-muted)]">
                                  Active Loadout ({cartItems.reduce((a, b) => a + b.qty, 0) + selectedFashion.length} selected)
                                </span>
                                <button
                                  type="button"
                                  onClick={() => {
                                    setCartItems([]);
                                    setSelectedFashion([]);
                                  }}
                                  className="border border-[var(--hud-line-soft)] bg-black/55 px-1.5 py-0.5 font-cyber-ui text-[10px] text-[var(--hud-muted)] hover:border-[var(--hud-primary-bright)] hover:text-[var(--hud-primary-bright)]"
                                >
                                  Clear Loadout
                                </button>
                              </div>
                              <div className="flex flex-wrap gap-1.5">
                                {cartItems.map((it) => (
                                  <span
                                    key={`${it.category}-${it.name}`}
                                    className={`inline-flex items-center gap-1.5 border px-2 py-0.5 text-xs ${
                                      it.category === "cyberware"
                                        ? "border-[var(--hud-accent-line)]/50 bg-[var(--hud-accent-navy)] text-[var(--hud-accent)]"
                                        : it.category === "weapon" || it.category === "armor"
                                          ? "border-[var(--hud-line)] bg-[var(--hud-row)] text-[var(--hud-text)]"
                                          : "border-[var(--hud-line-soft)] bg-black/55 text-[var(--hud-text)]"
                                    }`}
                                  >
                                    <span className="font-cyber-ui text-[9px] font-semibold uppercase text-[var(--hud-muted)]">{it.category}</span>
                                    <span className="font-cyber-ui font-medium">{it.name} {it.qty > 1 ? `×${it.qty}` : ""}</span>
                                    <span className="font-cyber-data text-[10px] text-[var(--hud-ok)]">{it.cost_eb * it.qty}eb</span>
                                    <button
                                      type="button"
                                      aria-label={`Remove ${it.name}`}
                                      onClick={() =>
                                        setCartItems((p) =>
                                          p.flatMap((x) =>
                                            x.name === it.name && x.category === it.category
                                              ? x.qty > 1
                                                ? [{ ...x, qty: x.qty - 1 }]
                                                : []
                                              : [x],
                                          ),
                                        )
                                      }
                                      className="text-[var(--hud-muted)] hover:text-[var(--hud-primary-bright)]"
                                    >×</button>
                                  </span>
                                ))}
                                {selectedFashion.map((f, idx) => (
                                  <span key={idx} className="inline-flex items-center gap-1.5 border border-[var(--hud-accent-line)]/45 bg-[var(--hud-accent-navy)]/60 px-2 py-0.5 text-xs">
                                    <span className="font-cyber-ui text-[9px] font-semibold uppercase text-[var(--hud-accent)]">fashion</span>
                                    <span className="font-cyber-ui">{f.name}</span>
                                    <span className="font-cyber-data text-[10px] text-[var(--hud-accent)]">{f.cost_eb}eb</span>
                                    <button
                                      type="button"
                                      aria-label={`Remove ${f.name}`}
                                      onClick={() => setSelectedFashion((p) => p.filter((_, i) => i !== idx))}
                                      className="text-[var(--hud-muted)] hover:text-[var(--hud-primary-bright)]"
                                    >×</button>
                                  </span>
                                ))}
                              </div>
                            </div>
                          )}

                          {cyberdeckSlotSummary.hasDeck && !cyberdeckSlotSummary.overCapacity && (
                            <div className="flex items-center justify-between border border-[var(--hud-accent-line)]/50 bg-[var(--hud-accent-navy)]/50 px-2 py-1.5 font-cyber-ui text-[11px] text-[var(--hud-accent)]">
                              <span>Cyberdeck Program &amp; Hardware Slots:</span>
                              <span className="font-cyber-data font-bold">
                                Deck Slots: {cyberdeckSlotSummary.usedSlots} / {cyberdeckSlotSummary.capacity}
                              </span>
                            </div>
                          )}
                        </div>
                      )}

                      {/* Always-Visible Cyberware & Deck Rule Warnings */}
                      {(cyberwarePrereqWarnings.length > 0 || cyberwareSlotWarnings.length > 0 || cyberdeckSlotSummary.overCapacity) && (
                        <div className="max-h-40 space-y-1.5 overflow-y-auto">
                          {cyberwarePrereqWarnings.length > 0 && (
                            <div className="cyber-hazard-thin space-y-1 border border-[var(--hud-warn)]/60 p-2">
                              <HazardBadge tone="warn">Cyberware Foundation Needed</HazardBadge>
                              {cyberwarePrereqWarnings.map((w) => (
                                <div key={w.foundation.id} className="flex flex-wrap items-center justify-between gap-2 font-cyber-ui text-[11px] text-[var(--hud-text)]">
                                  <span>
                                    <strong>{w.option}</strong> requires <strong>{w.foundation.name}</strong>.
                                  </span>
                                  <button
                                    type="button"
                                    onClick={() =>
                                      setCartItems((p) => [
                                        ...p,
                                        {
                                          name: w.foundation.name,
                                          category: "cyberware",
                                          cost_eb: w.foundation.cost_eb,
                                          hl: parseHlVal(w.foundation.stats),
                                          install: String(w.foundation.stats.install ?? ""),
                                          qty: 1,
                                        },
                                      ])
                                    }
                                    className="cyber-btn-tac cp-fx-hover px-2 py-0.5 font-cyber-data text-[10px] text-[var(--hud-warn)]"
                                  >
                                    + Add {w.foundation.name} ({w.foundation.cost_eb}eb)
                                  </button>
                                </div>
                              ))}
                            </div>
                          )}

                          {cyberwareSlotWarnings.length > 0 && (
                            <div className="cyber-hazard-thin space-y-1 border border-[var(--hud-warn)]/60 p-2">
                              <HazardBadge tone="warn">Cyberware Slot Cap Exceeded</HazardBadge>
                              {cyberwareSlotWarnings.map((w) => (
                                <div key={w.foundation} className="font-cyber-ui text-[11px] text-[var(--hud-text)]">
                                  <strong>{w.foundation}</strong>: <span className="font-cyber-data">{w.usedSlots}/{w.maxSlots}</span> slots ({w.options.join(", ")}).
                                </div>
                              ))}
                            </div>
                          )}

                          {cyberdeckSlotSummary.hasDeck && cyberdeckSlotSummary.overCapacity && (
                            <div className="cyber-hazard-thin flex items-center justify-between border border-[var(--hud-warn)]/60 px-2 py-1.5 font-cyber-ui text-[11px] text-[var(--hud-warn)]">
                              <span>Cyberdeck Program &amp; Hardware Slots:</span>
                              <span className="font-cyber-data font-bold">
                                Deck Slots: {cyberdeckSlotSummary.usedSlots} / {cyberdeckSlotSummary.capacity}
                              </span>
                            </div>
                          )}
                        </div>
                      )}

                      {/* Category Tabs */}
                      <div className="flex flex-wrap items-center gap-1">
                        {(["weapon", "armor", "cyberware", "gear", "program", "hardware", "vehicle", "drug", "fashion"] as const).map((cat) => {
                          const count = categoryCounts[cat] ?? 0;
                          return (
                            <button
                              key={cat}
                              type="button"
                              aria-label={cat}
                              onClick={() => setShopCategory(cat)}
                              className={`border px-2.5 py-1 font-cyber-ui text-xs capitalize transition ${
                                shopCategory === cat
                                  ? "border-[var(--hud-accent-line)] bg-[var(--hud-accent-navy)] font-semibold text-[var(--hud-accent)]"
                                  : "border-[var(--hud-line-soft)] bg-[var(--hud-panel)] text-[var(--hud-muted)] hover:border-[var(--hud-line)] hover:text-[var(--hud-text)]"
                              }`}
                            >
                              {cat === "vehicle" ? "Vehicles" : cat === "drug" ? "Drugs & Pharma" : cat}
                              {count > 0 && (
                                <span className="ml-1 inline-flex items-center justify-center border border-[var(--hud-ok)]/60 bg-[var(--hud-ok)]/20 px-1 font-cyber-data text-[10px] font-bold text-[var(--hud-ok)]">
                                  {count}
                                </span>
                              )}
                            </button>
                          );
                        })}
                      </div>

                      {/* Search, Sort & Affordable Controls */}
                      <div className="flex flex-wrap items-center gap-2">
                        <div className="relative min-w-[160px] flex-1">
                          <Search className="pointer-events-none absolute left-2.5 top-2 h-3.5 w-3.5 text-[var(--hud-muted)]" />
                          <input
                            type="text"
                            value={shopSearch}
                            onChange={(e) => setShopSearch(e.target.value)}
                            placeholder={`Search ${shopCategory === "fashion" ? "fashion" : shopCategory}…`}
                            className="w-full border border-[var(--hud-line-soft)] bg-black/60 py-1 pl-8 pr-7 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                          />
                          {shopSearch && (
                            <button
                              type="button"
                              aria-label="Clear catalog search"
                              onClick={() => setShopSearch("")}
                              className="absolute right-2 top-1.5 text-[var(--hud-muted)] hover:text-[var(--hud-text)]"
                            >
                              <X className="h-3.5 w-3.5" />
                            </button>
                          )}
                        </div>

                        <div className="inline-flex items-center gap-1 border border-[var(--hud-line-soft)] bg-black/60 px-2 py-1 text-xs">
                          <ArrowUpDown className="h-3 w-3 text-[var(--hud-muted)]" />
                          <select
                            aria-label="Sort catalog"
                            value={shopSort}
                            onChange={(e) => setShopSort(e.target.value as typeof shopSort)}
                            className="bg-transparent font-cyber-ui text-xs text-[var(--hud-text)] focus:outline-none"
                          >
                            <option value="cost_asc" className="bg-[#090d16]">Price: Low → High</option>
                            <option value="cost_desc" className="bg-[#090d16]">Price: High → Low</option>
                            <option value="name_asc" className="bg-[#090d16]">Name: A → Z</option>
                            {shopCategory === "weapon" && <option value="tier_asc" className="bg-[#090d16]">Tier: Poor → Exotic</option>}
                            {shopCategory === "weapon" && <option value="tier_desc" className="bg-[#090d16]">Tier: Exotic → Poor</option>}
                            {shopCategory === "armor" && <option value="sp_desc" className="bg-[#090d16]">Armor SP: High → Low</option>}
                            {shopCategory === "cyberware" && <option value="hl_asc" className="bg-[#090d16]">Humanity Loss: Low → High</option>}
                          </select>
                        </div>

                        <button
                          type="button"
                          onClick={() => setSelectedOnly((v) => !v)}
                          className={`cyber-btn-tac cp-fx-hover px-2 py-1 font-cyber-ui text-[11px] font-medium ${
                            selectedOnly ? "is-active" : ""
                          }`}
                        >
                          Selected Only
                        </button>

                        {method === "complete_package" && (
                          <button
                            type="button"
                            onClick={() => setAffordableOnly((v) => !v)}
                            className={`cyber-btn-tac cp-fx-hover px-2 py-1 font-cyber-ui text-[11px] font-medium ${
                              affordableOnly ? "is-active" : ""
                            }`}
                          >
                            Affordable Only
                          </button>
                        )}
                      </div>

                      {/* Sub-filters */}
                      {shopCategory === "weapon" && (
                        <div className="space-y-1">
                          <div className="flex flex-wrap items-center gap-1 text-[11px]">
                            <span className="mr-0.5 font-cyber-ui text-[10px] font-semibold uppercase tracking-wider text-[var(--hud-muted)]">
                              Genre:
                            </span>
                            <button
                              type="button"
                              onClick={() => setWeaponGenres([])}
                              className={`border px-1.5 py-0.5 font-cyber-ui text-[11px] transition ${
                                weaponGenres.length === 0
                                  ? "border-[var(--hud-accent-line)] bg-[var(--hud-accent-navy)] font-semibold text-[var(--hud-accent)]"
                                  : "border-[var(--hud-line-soft)] bg-[var(--hud-panel)] text-[var(--hud-muted)] hover:text-[var(--hud-text)]"
                              }`}
                            >
                              All Weapons
                            </button>
                            {(
                              [
                                ["pistols", "Pistols & SMGs"],
                                ["rifles", "Rifles & Shotguns"],
                                ["heavy", "Heavy Weapons"],
                                ["melee", "Melee & Brawling"],
                                ["attachment", "Attachments"],
                                ["ammo", "Ammo"],
                              ] as const
                            ).map(([id, label]) => {
                              const active = weaponGenres.includes(id);
                              return (
                                <button
                                  key={id}
                                  type="button"
                                  aria-pressed={active}
                                  onClick={() =>
                                    setWeaponGenres((prev) =>
                                      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
                                    )
                                  }
                                  className={`border px-1.5 py-0.5 font-cyber-ui text-[11px] transition ${
                                    active
                                      ? "border-[var(--hud-primary-bright)] bg-[var(--hud-row)] font-semibold text-[var(--hud-text)]"
                                      : "border-[var(--hud-line-soft)] bg-[var(--hud-panel)] text-[var(--hud-muted)] hover:text-[var(--hud-text)]"
                                  }`}
                                >
                                  {label}
                                </button>
                              );
                            })}

                            <span className="mx-1 h-3.5 w-px bg-[var(--hud-line-soft)]" aria-hidden="true" />

                            <span className="mr-0.5 font-cyber-ui text-[10px] font-semibold uppercase tracking-wider text-[var(--hud-muted)]">
                              Tier:
                            </span>
                            <button
                              type="button"
                              onClick={() => setWeaponTiers([])}
                              className={`border px-1.5 py-0.5 font-cyber-ui text-[11px] transition ${
                                weaponTiers.length === 0
                                  ? "border-[var(--hud-accent-line)] bg-[var(--hud-accent-navy)] font-semibold text-[var(--hud-accent)]"
                                  : "border-[var(--hud-line-soft)] bg-[var(--hud-panel)] text-[var(--hud-muted)] hover:text-[var(--hud-text)]"
                              }`}
                            >
                              All Tiers
                            </button>
                            {(
                              [
                                ["poor", "Poor"],
                                ["standard", "Standard"],
                                ["excellent", "Excellent (+1 Hit)"],
                                ["exotic", "Exotic"],
                              ] as const
                            ).map(([tid, label]) => {
                              const active = weaponTiers.includes(tid);
                              const tierTheme = getWeaponTierTheme(tid);
                              return (
                                <button
                                  key={tid}
                                  type="button"
                                  aria-pressed={active}
                                  onClick={() =>
                                    setWeaponTiers((prev) =>
                                      prev.includes(tid) ? prev.filter((x) => x !== tid) : [...prev, tid],
                                    )
                                  }
                                  className={`inline-flex items-center gap-1 border px-1.5 py-0.5 font-cyber-ui text-[11px] transition ${
                                    active
                                      ? `${tierTheme.pillActiveClass} font-semibold`
                                      : "border-[var(--hud-line-soft)] bg-[var(--hud-panel)] text-[var(--hud-muted)] hover:text-[var(--hud-text)]"
                                  }`}
                                >
                                  <span className={`h-1.5 w-1.5 rounded-full ${tierTheme.dotClass}`} />
                                  {label}
                                </button>
                              );
                            })}
                          </div>
                          {weaponGenres.includes("ammo") && (
                            <div className="flex flex-wrap items-center gap-2 border border-[var(--hud-line-soft)] bg-black/55 px-2.5 py-1.5 text-[11px]">
                              <span className="font-cyber-ui font-semibold text-[var(--hud-text)]">Ammo Caliber Tag:</span>
                              <select
                                aria-label="Ammo Caliber"
                                value={ammoCaliber}
                                onChange={(e) => setAmmoCaliber(e.target.value)}
                                className="border border-[var(--hud-line-soft)] bg-black/70 px-2 py-0.5 font-cyber-ui text-[11px] text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                              >
                                <option value="">Standard / As Listed</option>
                                {Array.from(
                                  new Set(
                                    (refData?.shop.weapon ?? [])
                                      .filter((w) => w.stats.weapon_class === "ranged" && !w.stats.quality)
                                      .map((w) => w.name),
                                  ),
                                ).map((cal) => (
                                  <option key={cal} value={cal}>{cal}</option>
                                ))}
                              </select>
                            </div>
                          )}
                        </div>
                      )}

                      {shopCategory === "armor" && (
                        <div className="flex flex-wrap gap-1">
                          {(
                            [
                              ["all", "All Armor"],
                              ["body", "Body Armor"],
                              ["head", "Head / Helmets"],
                              ["shield", "Shields"],
                            ] as const
                          ).map(([id, label]) => (
                            <button
                              key={id}
                              type="button"
                              onClick={() => setArmorSubFilter(id)}
                              className={`border px-2 py-0.5 font-cyber-ui text-[11px] transition ${
                                armorSubFilter === id
                                  ? "border-[var(--hud-accent-line)] bg-[var(--hud-accent-navy)] text-[var(--hud-accent)]"
                                  : "border-[var(--hud-line-soft)] bg-[var(--hud-panel)] text-[var(--hud-muted)] hover:text-[var(--hud-text)]"
                              }`}
                            >
                              {label}
                            </button>
                          ))}
                        </div>
                      )}

                      {shopCategory === "cyberware" && (
                        <div className="flex flex-wrap gap-1">
                          {(
                            [
                              ["all", "All Cyberware"],
                              ["foundation", "Foundations"],
                              ["neural", "Neuralware"],
                              ["cyberoptic", "Cyberoptics"],
                              ["cyberaudio", "Cyberaudio"],
                              ["cyberlimb", "Cyberlimbs"],
                              ["body", "Internal / External"],
                              ["fashionware", "Fashionware"],
                            ] as const
                          ).map(([id, label]) => (
                            <button
                              key={id}
                              type="button"
                              onClick={() => setCyberwareSubFilter(id)}
                              className={`border px-2 py-0.5 font-cyber-ui text-[11px] transition ${
                                cyberwareSubFilter === id
                                  ? "border-[var(--hud-accent-line)] bg-[var(--hud-accent-navy)] text-[var(--hud-accent)]"
                                  : "border-[var(--hud-line-soft)] bg-[var(--hud-panel)] text-[var(--hud-muted)] hover:text-[var(--hud-text)]"
                              }`}
                            >
                              {label}
                            </button>
                          ))}
                        </div>
                      )}

                      {(shopCategory === "program" || shopCategory === "hardware") && (
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          {shopCategory === "program" && (
                            <div className="flex flex-wrap gap-1">
                              {(
                                [
                                  ["all", "All Programs"],
                                  ["booster", "Boosters"],
                                  ["defender", "Defenders"],
                                  ["attacker", "Attackers"],
                                  ["black_ice", "Black ICE"],
                                ] as const
                              ).map(([id, label]) => (
                                <button
                                  key={id}
                                  type="button"
                                  onClick={() => setProgramSubFilter(id)}
                                  className={`border px-2 py-0.5 font-cyber-ui text-[11px] transition ${
                                    programSubFilter === id
                                      ? "border-[var(--hud-accent-line)] bg-[var(--hud-accent-navy)] text-[var(--hud-accent)]"
                                      : "border-[var(--hud-line-soft)] bg-[var(--hud-panel)] text-[var(--hud-muted)] hover:text-[var(--hud-text)]"
                                  }`}
                                >
                                  {label}
                                </button>
                              ))}
                            </div>
                          )}
                          {cyberdeckSlotSummary.hasDeck && (
                            <span
                              className={`border px-2 py-0.5 font-cyber-data text-[10px] ${
                                cyberdeckSlotSummary.overCapacity
                                  ? "border-[var(--hud-warn)]/60 bg-[var(--hud-warn)]/15 text-[var(--hud-warn)]"
                                  : "border-[var(--hud-accent-line)]/50 bg-[var(--hud-accent-navy)] text-[var(--hud-accent)]"
                              }`}
                            >
                              Deck Slots: {cyberdeckSlotSummary.usedSlots} / {cyberdeckSlotSummary.capacity}
                            </span>
                          )}
                        </div>
                      )}

                      {shopCategory === "fashion" && (
                        <div className="flex flex-wrap gap-1">
                          {["All", ...Array.from(new Set((refData?.fashion ?? []).map((f) => f.style)))].map((styleOpt) => (
                            <button
                              key={styleOpt}
                              type="button"
                              onClick={() => setFashionStyleFilter(styleOpt)}
                              className={`border px-2 py-0.5 font-cyber-ui text-[11px] transition ${
                                fashionStyleFilter === styleOpt
                                  ? "border-[var(--hud-accent-line)] bg-[var(--hud-accent-navy)] font-semibold text-[var(--hud-accent)]"
                                  : "border-[var(--hud-line-soft)] bg-[var(--hud-panel)] text-[var(--hud-muted)] hover:text-[var(--hud-text)]"
                              }`}
                            >
                              {styleOpt}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>

                    {/* Catalog Items (single smooth scroll flow, no nested scrollboxes or hover-thrash) */}
                    <div className="space-y-1.5 pt-1">
                      {shopCategory === "fashion" ? (
                        fashionItemsForDisplay.length === 0 ? (
                          <p className="py-6 text-center font-cyber-ui text-xs text-[var(--hud-muted)]">
                            No fashion items match your filter.
                          </p>
                        ) : (
                          fashionItemsForDisplay.map((f) => {
                            const qty = selectedFashion.filter((x) => x.name === f.name).length;
                            const overBudget = method === "complete_package" && f.cost_eb > remainingFashionEb;
                            return (
                              <div
                                key={f.name}
                                className={`flex items-center justify-between gap-3 px-3 py-2 text-xs transition ${
                                  qty > 0
                                    ? "cyber-card-active border-l-4 border-l-[var(--hud-ok)] bg-emerald-950/25"
                                    : "cyber-card"
                                }`}
                              >
                                <div className="min-w-0 flex-1">
                                  <div className="flex flex-wrap items-center gap-1.5">
                                    <span className="font-cyber-ui text-[13px] sm:text-sm font-semibold text-white">{f.name}</span>
                                    {qty > 0 && (
                                      <span className="border border-[var(--hud-ok)] bg-[var(--hud-ok)]/15 px-1.5 py-0.5 font-cyber-data text-[10px] font-bold uppercase text-[var(--hud-ok)]">
                                        IN BAG ×{qty}
                                      </span>
                                    )}
                                    <span className="border border-[var(--hud-accent-line)]/45 bg-[var(--hud-accent-navy)] px-1.5 py-0.5 font-cyber-ui text-[10px] text-[var(--hud-accent)]">
                                      {f.style}
                                    </span>
                                  </div>
                                  <p className="mt-1 font-cyber-ui text-xs text-[var(--hud-muted)] leading-snug">{f.summary}</p>
                                </div>
                                <div className="flex shrink-0 items-center gap-1.5">
                                  {qty > 0 && (
                                    <button
                                      type="button"
                                      onClick={() => {
                                        const idx = selectedFashion.findIndex((x) => x.name === f.name);
                                        if (idx >= 0) setSelectedFashion((p) => p.filter((_, i) => i !== idx));
                                      }}
                                      aria-label={`Remove ${f.name}`}
                                      className="cyber-btn-tac cp-fx-hover px-1.5 py-1"
                                    >
                                      <Minus className="h-3 w-3" />
                                    </button>
                                  )}
                                  <button
                                    type="button"
                                    onClick={() => setSelectedFashion((p) => [...p, { name: f.name, cost_eb: f.cost_eb, style: f.style }])}
                                    className={`px-3 py-1.5 font-cyber-data text-xs font-bold transition ${
                                      overBudget
                                        ? "border border-[var(--hud-line-soft)] bg-black/40 text-[var(--hud-muted)] hover:border-[var(--hud-line)]"
                                        : "border border-[var(--hud-ok)]/50 bg-emerald-950/35 text-[var(--hud-ok)] hover:border-[var(--hud-ok)] hover:bg-[var(--hud-ok)]/20"
                                    }`}
                                  >
                                    +{f.cost_eb}eb{qty > 0 ? ` (${qty})` : ""}
                                  </button>
                                </div>
                              </div>
                            );
                          })
                        )
                      ) : shopItemsForCategory.length === 0 ? (
                        <p className="py-6 text-center font-cyber-ui text-xs text-[var(--hud-muted)]">
                          No {shopCategory} items match your current filter or search.
                        </p>
                      ) : (
                        shopItemsForCategory.map((item) => {
                          const hlVal = parseHlVal(item.stats);
                          const spVal = parseSpVal(item.stats);
                          const locVal = Array.isArray(item.stats.locations) ? item.stats.locations.join(" & ") : undefined;
                          const installVal = typeof item.stats.install === "string" ? item.stats.install : undefined;
                          const qualityVal = typeof item.stats.quality === "string" ? item.stats.quality : undefined;
                          const dmgVal = typeof item.stats.damage === "string" ? item.stats.damage : undefined;
                          const weaponTierInfo =
                            shopCategory === "weapon" ? classifyWeaponTiers(item) : null;
                          const weaponTierTheme = weaponTierInfo
                            ? getWeaponTierTheme(weaponTierInfo.primaryTier)
                            : null;
                          const isAmmoEntry = item.category === "ammo";
                          const cartItemName =
                            isAmmoEntry && ammoCaliber ? `${item.name} — ${ammoCaliber}` : item.name;
                          const inCart = cartItems.find((x) => x.name === cartItemName && x.category === item.category);
                          const isPrimaryWeapon = item.category === "weapon";
                          const overBudget = method === "complete_package" && item.cost_eb > remainingGearEb;
                          const inspectPayload: InspectorCard = {
                            title: `${item.name} (${item.cost_eb} eb)`,
                            subtitle: `${item.category.toUpperCase()}${qualityVal ? ` · ${qualityVal}` : ""}${item.printed_page ? ` · Corebook p.${item.printed_page}` : ""}${hlVal ? ` · HL ${hlVal}` : ""}${spVal ? ` · SP ${spVal}` : ""}`,
                            body: item.description || item.summary,
                            mechanics: dmgVal ? `Damage: ${dmgVal}` : undefined,
                          };
                          return (
                            <div
                              key={item.id}
                              onClick={() => {
                                setInspectedItemId(item.id);
                                setInspector(inspectPayload);
                              }}
                              className={`flex items-center justify-between gap-3 px-3 py-2 text-xs transition ${
                                inCart
                                  ? "cyber-card-active border-l-4 border-l-[var(--hud-ok)] bg-emerald-950/25"
                                  : inspectedItemId === item.id
                                    ? "cyber-card border-[var(--hud-accent-line)] bg-[var(--hud-accent-navy)]/50"
                                    : weaponTierTheme
                                      ? weaponTierTheme.cardClass
                                      : "cyber-card"
                              }`}
                            >
                              <div className="min-w-0 flex-1">
                                <div className="flex flex-wrap items-center gap-1.5">
                                  <span className="font-cyber-ui text-[13px] sm:text-sm font-semibold text-white">{item.name}</span>
                                  {inCart && (
                                    <span className="border border-[var(--hud-ok)] bg-[var(--hud-ok)]/15 px-1.5 py-0.5 font-cyber-data text-[10px] font-bold uppercase text-[var(--hud-ok)]">
                                      IN BAG ×{inCart.qty}
                                    </span>
                                  )}
                                  {dmgVal && (
                                    <span className="border border-[var(--hud-primary-bright)]/50 bg-[var(--hud-primary)]/15 px-1.5 py-0.5 font-cyber-data text-[10px] font-semibold text-rose-200">
                                      DMG {dmgVal}
                                    </span>
                                  )}
                                  {spVal > 0 && (
                                    <span className="border border-[var(--hud-accent-line)]/50 bg-[var(--hud-accent-navy)] px-1.5 py-0.5 font-cyber-data text-[10px] font-semibold text-[var(--hud-accent)]">
                                      SP {spVal}{locVal ? ` · ${locVal}` : ""}
                                    </span>
                                  )}
                                  {hlVal > 0 && (
                                    <span className="border border-[var(--hud-warn)]/50 bg-[var(--hud-warn)]/15 px-1.5 py-0.5 font-cyber-data text-[10px] font-semibold text-[var(--hud-warn)]">
                                      HL {hlVal}{installVal ? ` · ${installVal}` : ""}
                                    </span>
                                  )}
                                  {weaponTierInfo && weaponTierInfo.primaryTier !== "other" && (
                                    <>
                                      {weaponTierInfo.tiers.includes("exotic") && (
                                        <span className={`px-1.5 py-0.5 font-cyber-ui text-[9px] font-bold ${getWeaponTierTheme("exotic").badgeClass}`}>
                                          EXOTIC
                                        </span>
                                      )}
                                      {weaponTierInfo.tiers.includes("excellent") && (
                                        <span className={`px-1.5 py-0.5 font-cyber-ui text-[9px] font-bold ${getWeaponTierTheme("excellent").badgeClass}`}>
                                          EXCELLENT (+1 HIT)
                                        </span>
                                      )}
                                      {weaponTierInfo.primaryTier === "standard" && (
                                        <span className={`px-1.5 py-0.5 font-cyber-ui text-[9px] font-bold ${getWeaponTierTheme("standard").badgeClass}`}>
                                          STANDARD
                                        </span>
                                      )}
                                      {weaponTierInfo.primaryTier === "poor" && (
                                        <span className={`px-1.5 py-0.5 font-cyber-ui text-[9px] font-bold ${getWeaponTierTheme("poor").badgeClass}`}>
                                          POOR
                                        </span>
                                      )}
                                    </>
                                  )}
                                  {isPrimaryWeapon && (
                                    <span className="border border-[var(--hud-line-soft)] bg-black/55 px-1.5 py-0.5 font-cyber-data text-[10px] text-[var(--hud-muted)]">
                                      {qualityVal === "poor" ? "2 Att. Slots" : "3 Att. Slots"}
                                    </span>
                                  )}
                                  {item.printed_page && (
                                    <span className="border border-[var(--hud-line-soft)] bg-black/40 px-1.5 py-0.5 font-cyber-data text-[10px] text-[var(--hud-muted)]">p.{item.printed_page}</span>
                                  )}
                                </div>
                                <p className="mt-1 font-cyber-ui text-xs text-[var(--hud-muted)] leading-snug">{item.summary}</p>
                              </div>

                              <div className="flex shrink-0 items-center gap-1.5">
                                {inCart ? (
                                  <div className="inline-flex items-center gap-1 border border-[var(--hud-ok)]/60 bg-black/60 px-1.5 py-0.5 font-cyber-data text-[11px]">
                                    <button
                                      type="button"
                                      aria-label={`Decrease ${item.name}`}
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        setCartItems((p) =>
                                          p.flatMap((x) =>
                                            x.name === cartItemName && x.category === item.category
                                              ? x.qty > 1
                                                ? [{ ...x, qty: x.qty - 1 }]
                                                : []
                                              : [x],
                                          ),
                                        );
                                      }}
                                      className="p-0.5 text-[var(--hud-muted)] hover:text-[var(--hud-primary-bright)]"
                                    >
                                      <Minus className="h-3 w-3" />
                                    </button>
                                    <span className="min-w-[1.2rem] text-center font-bold text-[var(--hud-ok)]">{inCart.qty}</span>
                                    <button
                                      type="button"
                                      aria-label={`Increase ${item.name}`}
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        setCartItems((p) =>
                                          p.map((x) =>
                                            x.name === cartItemName && x.category === item.category ? { ...x, qty: x.qty + 1 } : x,
                                          ),
                                        );
                                      }}
                                      className="p-0.5 text-[var(--hud-ok)] hover:text-white"
                                    >
                                      <Plus className="h-3 w-3" />
                                    </button>
                                  </div>
                                ) : (
                                  <button
                                    type="button"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setCartItems((p) => [
                                        ...p,
                                        {
                                          name: cartItemName,
                                          category: item.category,
                                          cost_eb: item.cost_eb,
                                          hl: hlVal,
                                          sp: spVal || undefined,
                                          location: locVal,
                                          install: installVal,
                                          notes: item.summary,
                                          qty: 1,
                                        },
                                      ]);
                                    }}
                                    className={`px-3 py-1.5 font-cyber-data text-xs font-bold transition ${
                                      overBudget
                                        ? "border border-[var(--hud-line-soft)] bg-black/40 text-[var(--hud-muted)] hover:border-[var(--hud-line)]"
                                        : "border border-[var(--hud-ok)]/50 bg-emerald-950/35 text-[var(--hud-ok)] hover:border-[var(--hud-ok)] hover:bg-[var(--hud-ok)]/20"
                                    }`}
                                  >
                                    +{item.cost_eb}eb
                                  </button>
                                )}
                              </div>
                            </div>
                          );
                        })
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* STEP 6: SHEET REVIEW */}
            {step === "review" && (
              <div className="space-y-4">
                {validationIssues.length > 0 && (
                  <div className="cyber-hazard-thin space-y-2 border border-[var(--hud-warn)]/60 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <HazardBadge tone="warn">
                        <AlertTriangle className="h-3.5 w-3.5" /> Check Before Launching
                      </HazardBadge>
                    </div>
                    <ul className="list-disc space-y-0.5 pl-5 font-cyber-ui text-xs text-[var(--hud-text)]">
                      {validationIssues.map((msg) => (
                        <li key={msg}>{msg}</li>
                      ))}
                    </ul>
                  </div>
                )}

                <CyberFrame variant="default" className="space-y-4 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--hud-line-soft)] pb-3">
                    <div className="flex items-center gap-3">
                      {portraitUrl.trim() && (
                        <img
                          src={portraitUrl}
                          alt={name.trim() || realName.trim() || "Portrait"}
                          className="h-12 w-12 border border-[var(--hud-accent-line)] object-cover"
                        />
                      )}
                      <div>
                        <h3 className="font-cyber-display text-base font-bold uppercase tracking-wider text-[var(--hud-text)]">
                          {name.trim() || realName.trim() || "Unnamed Edgerunner"}
                        </h3>
                        {realName.trim() && (
                          <div className="flex items-center gap-1 font-cyber-ui text-[11px] text-[var(--hud-muted)]">
                            <span>Real Name: <strong className="text-[var(--hud-text)]">{realName.trim()}</strong></span>
                            <span className="font-cyber-ui text-[10px] text-[var(--hud-warn)]">
                              ({realNameHidden ? "Hidden / Known by Handle" : "Publicly Known"})
                            </span>
                          </div>
                        )}
                        <div className="flex flex-wrap items-center gap-1.5 font-cyber-ui text-xs text-[var(--hud-accent)]">
                          <RoleTag role={selectedRole} rank={4} />
                          <span>({roleInfo?.ability}) · {culturalRegion} ({culturalLanguage})</span>
                        </div>
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-3 font-cyber-data text-xs">
                      <span className="text-[var(--hud-primary-bright)]">HP {maxHp}</span>
                      {effectiveBody !== activeStats.BODY && (
                        <span className="text-[var(--hud-warn)]">BODY {activeStats.BODY} → {effectiveBody}</span>
                      )}
                      {subdermalSp > 0 && (
                        <span className="text-[var(--hud-accent)]">{subdermalName} SP {subdermalSp}</span>
                      )}
                      <span className="text-[var(--hud-accent)]">HUM {startingHumanity}/{maxHumanity}</span>
                      {reputation > 0 && <span className="text-[var(--hud-warn)]">REP {reputation}</span>}
                      <span className="text-[var(--hud-ok)]">{gearSummary.money} eb</span>
                    </div>
                  </div>

                  {/* HP & Humanity Telemetry Bars */}
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <div className="space-y-1 border border-[var(--hud-line-soft)] bg-black/45 p-2.5">
                      <div className="flex items-center justify-between font-cyber-ui text-[11px]">
                        <span className="text-[var(--hud-muted)]">Starting Hit Points</span>
                        <span className="font-cyber-data font-semibold text-[var(--hud-text)]">{maxHp} / {maxHp} HP</span>
                      </div>
                      <SegmentedBar
                        value={maxHp}
                        max={maxHp}
                        segments={20}
                        thresholdRatio={0.5}
                        tone="primary"
                        aria-label={`Starting HP ${maxHp} of ${maxHp}`}
                      />
                    </div>
                    <div className="space-y-1 border border-[var(--hud-line-soft)] bg-black/45 p-2.5">
                      <div className="flex items-center justify-between font-cyber-ui text-[11px]">
                        <span className="text-[var(--hud-muted)]">Starting Humanity</span>
                        <span className="font-cyber-data font-semibold text-[var(--hud-accent)]">{startingHumanity} / {maxHumanity}</span>
                      </div>
                      <SegmentedBar
                        value={startingHumanity}
                        max={maxHumanity}
                        segments={10}
                        tone={startingHumanity < maxHumanity * 0.4 ? "warn" : "accent"}
                        aria-label={`Starting Humanity ${startingHumanity} of ${maxHumanity}`}
                      />
                    </div>
                  </div>

                  {/* STAT Grid */}
                  <div className="grid grid-cols-5 gap-1.5 text-center text-xs sm:grid-cols-10">
                    {STAT_NAMES.map((s) => (
                      <div key={s} className="border border-[var(--hud-line-soft)] bg-black/50 p-1.5">
                        <div className="font-cyber-ui text-[10px] text-[var(--hud-muted)]">{s}</div>
                        <div className="font-cyber-data font-bold text-[var(--hud-text)]">{activeStats[s]}</div>
                      </div>
                    ))}
                  </div>

                  {/* Backstory & Established Ties */}
                  <div className="space-y-1.5 font-cyber-ui text-xs">
                    <div className="font-cyber-display font-semibold uppercase tracking-wider text-[var(--hud-muted)]">
                      Backstory &amp; History
                    </div>
                    <p className="text-[var(--hud-text)]">
                      {backstorySummary.trim() || `${personality}; ${familyBackground.split(" — ", 1)[0]} upbringing. Goal: ${lifeGoal}`}
                    </p>
                    {establishedHistory.trim() && (
                      <p className="text-[var(--hud-text)]/85"><strong>Established Ties:</strong> {establishedHistory}</p>
                    )}
                    {(friends.length > 0 || enemies.length > 0) && (
                      <p className="text-[var(--hud-muted)]">
                        Connections: {friends.length} friend{friends.length === 1 ? "" : "s"}, {enemies.length} enem{enemies.length === 1 ? "y" : "ies"}, {loveAffairs.length} past romance{loveAffairs.length === 1 ? "" : "s"}.
                      </p>
                    )}
                  </div>

                  {/* Trained Skills Summary */}
                  <div className="space-y-1.5">
                    <div className="font-cyber-display text-xs font-semibold uppercase tracking-wider text-[var(--hud-muted)]">
                      Skills (<span className="font-cyber-data">{Object.keys(effectiveSkills).length}</span>)
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {Object.entries(effectiveSkills)
                        .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
                        .map(([skName, lvl]) => (
                          <span key={skName} className="border border-[var(--hud-line-soft)] bg-black/55 px-2 py-0.5 font-cyber-ui text-[11px] text-[var(--hud-text)]">
                            {skName} <strong className="font-cyber-data text-[var(--hud-accent)]">+{lvl}</strong>
                          </span>
                        ))}
                    </div>
                  </div>

                  {/* Gear & Cyberware Summary */}
                  <div className="space-y-1.5">
                    <div className="font-cyber-display text-xs font-semibold uppercase tracking-wider text-[var(--hud-muted)]">
                      Starting Loadout &amp; Cyberware (<span className="font-cyber-data">{Object.keys(gearSummary.inventory).length}</span> items, <span className="font-cyber-data">{gearSummary.cyberware.length}</span> cyberware)
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {gearSummary.cyberware.map((cw, i) => (
                        <span key={i} className="border border-[var(--hud-accent-line)]/50 bg-[var(--hud-accent-navy)] px-2 py-0.5 font-cyber-ui text-[11px] text-[var(--hud-accent)]">
                          {cw.name} {cw.hl ? <span className="font-cyber-data">(-{cw.hl} HL)</span> : ""}
                        </span>
                      ))}
                      {Object.entries(gearSummary.inventory).map(([itemName, qty]) => (
                        <span key={itemName} className="border border-[var(--hud-line-soft)] bg-black/55 px-2 py-0.5 font-cyber-ui text-[11px] text-[var(--hud-text)]">
                          {itemName}{qty > 1 ? <span className="font-cyber-data"> ×{qty}</span> : ""}
                        </span>
                      ))}
                    </div>
                    {cyberwarePrereqWarnings.length > 0 && (
                      <p className="font-cyber-ui text-[11px] text-[var(--hud-warn)]">
                        Cyberware Note: {cyberwarePrereqWarnings.map((w) => `${w.option} needs ${w.foundation.name}`).join("; ")}.
                      </p>
                    )}
                    {cyberwareSlotWarnings.length > 0 && (
                      <p className="font-cyber-ui text-[11px] text-[var(--hud-warn)]">
                        Cyberware Slot Cap Warning: {cyberwareSlotWarnings.map((w) => `${w.foundation} exceeds slot cap (${w.usedSlots}/${w.maxSlots} slots)`).join("; ")}.
                      </p>
                    )}
                    <div className="border border-[var(--hud-line-soft)] bg-black/45 px-2.5 py-1.5 font-cyber-ui text-[11px] text-[var(--hud-muted)]">
                      <strong className="text-[var(--hud-text)]">Starting Housing &amp; Lifestyle:</strong>{" "}
                      {housing} + {lifestyle} Lifestyle
                      {traumaTeam !== "None" ? ` · Trauma Team ${traumaTeam}` : ""} (Month 1 covered).
                    </div>
                  </div>
                </CyberFrame>
              </div>
            )}
          </div>

          {/* Right 4 cols: Sticky Live Sheet Preview + Hover Rulebook Inspector */}
          <aside className="hidden min-h-0 flex-col space-y-4 overflow-hidden border-l border-[var(--hud-line)] bg-black/35 p-4 lg:col-span-4 lg:flex">
            {/* Live Vitals Card */}
            <CyberFrame variant="hex" className="shrink-0 space-y-3 p-3.5">
              <div className="flex items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                  {portraitUrl.trim() && (
                    <img
                      src={portraitUrl}
                      alt={name.trim() || "Portrait"}
                      className="h-8 w-8 shrink-0 border border-[var(--hud-accent-line)] object-cover"
                    />
                  )}
                  <div className="min-w-0">
                    <div className="truncate font-cyber-display text-sm font-bold text-[var(--hud-text)]">
                      {name.trim() || realName.trim() || "New Edgerunner"}
                    </div>
                    {realName.trim() && (
                      <div className="truncate font-cyber-ui text-[10px] text-[var(--hud-muted)]">
                        {realName.trim()} {realNameHidden ? "(Hidden)" : "(Public)"}
                      </div>
                    )}
                  </div>
                </div>
                <RoleTag role={selectedRole} rank={4} className="shrink-0 border border-[var(--hud-accent-line)]/45 bg-[var(--hud-accent-navy)] px-1.5 py-0.5 text-[var(--hud-accent)]" />
              </div>

              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="border border-[var(--hud-line-soft)] bg-black/55 p-2">
                  <div className="flex items-center gap-1 font-cyber-ui text-[10px] text-[var(--hud-muted)]">
                    <Heart className="h-3 w-3 text-[var(--hud-primary-bright)]" /> HP / Wound
                  </div>
                  <div className="mt-0.5 font-cyber-data font-bold text-[var(--hud-text)]">
                    {maxHp} HP <span className="text-[10px] text-[var(--hud-muted)]" title={`Seriously Wounded: < ${woundThreshold} HP`}>(SW &lt;{woundThreshold})</span>
                  </div>
                  <SegmentedBar value={maxHp} max={maxHp} segments={10} thresholdRatio={0.5} tone="primary" className="mt-1" />
                </div>
                <div className="border border-[var(--hud-line-soft)] bg-black/55 p-2">
                  <div className="flex items-center gap-1 font-cyber-ui text-[10px] text-[var(--hud-muted)]">
                    <Cpu className="h-3 w-3 text-[var(--hud-accent)]" /> Humanity
                  </div>
                  <div className="mt-0.5 font-cyber-data font-bold text-[var(--hud-accent)]">
                    {startingHumanity}/{maxHumanity} <span className="text-[10px] text-[var(--hud-muted)]">(EMP {effectiveEmp})</span>
                  </div>
                  <SegmentedBar
                    value={startingHumanity}
                    max={maxHumanity}
                    segments={10}
                    tone={startingHumanity < maxHumanity * 0.4 ? "warn" : "accent"}
                    className="mt-1"
                  />
                </div>
                <div className="border border-[var(--hud-line-soft)] bg-black/55 p-2">
                  <div className="flex items-center gap-1 font-cyber-ui text-[10px] text-[var(--hud-muted)]">
                    <Shield className="h-3 w-3 text-[var(--hud-warn)]" /> Death / Dodge
                  </div>
                  <div className="mt-0.5 font-cyber-data text-[11px] font-bold text-[var(--hud-text)]">
                    Death Save: {deathSave} · <span className="font-cyber-ui">{activeStats.REF >= 8 ? "Bullet Dodge" : "Melee Dodge"}</span>
                  </div>
                </div>
                <div className="border border-[var(--hud-line-soft)] bg-black/55 p-2">
                  <div className="flex items-center gap-1 font-cyber-ui text-[10px] text-[var(--hud-muted)]">
                    <Backpack className="h-3 w-3 text-[var(--hud-ok)]" /> Eddies / Gear
                  </div>
                  <div className="mt-0.5 font-cyber-data font-bold text-[var(--hud-ok)]">
                    {gearSummary.money} eb · {Object.keys(gearSummary.inventory).length} items
                  </div>
                </div>
              </div>

              {subdermalSp > 0 && (
                <div className="border border-[var(--hud-accent-line)]/50 bg-[var(--hud-accent-navy)] px-2 py-1 font-cyber-data text-[10px] text-[var(--hud-accent)]">
                  Passive Cyberware Armor: {subdermalName} (SP {subdermalSp})
                </div>
              )}

              <div className="grid grid-cols-5 gap-1 text-center text-[11px]">
                {STAT_NAMES.map((s) => (
                  <div key={s} className="border border-[var(--hud-line-soft)] bg-black/55 py-1">
                    <div className="font-cyber-ui text-[9px] text-[var(--hud-muted)]">{s}</div>
                    <div className="font-cyber-data font-bold text-[var(--hud-text)]">{activeStats[s]}</div>
                  </div>
                ))}
              </div>
            </CyberFrame>

            {/* Contextual Hover / Click Inspector */}
            <CyberFrame variant="default" className="min-h-0 flex-1 space-y-2.5 overflow-y-auto p-3.5">
              <div className="cyber-section-header mb-0">
                <div className="cyber-section-title">
                  <BookOpen className="h-3.5 w-3.5 text-[var(--hud-accent)]" />
                  <span>Live Rulebook Inspector</span>
                </div>
              </div>
              <div className="space-y-1.5">
                <h4 className="font-cyber-ui text-sm font-bold text-white">{inspector.title}</h4>
                {inspector.subtitle && (
                  <span className="inline-block border border-[var(--hud-accent-line)]/50 bg-[var(--hud-accent-navy)] px-2 py-0.5 font-cyber-ui text-[10px] font-semibold uppercase tracking-wider text-[var(--hud-accent)]">
                    {inspector.subtitle}
                  </span>
                )}
              </div>
              <p className="font-cyber-ui text-xs leading-relaxed text-[var(--hud-text)]/90">{inspector.body}</p>
              {inspector.mechanics && (
                <div className="border border-[var(--hud-line-soft)] bg-black/45 p-2 font-cyber-ui text-[11px] leading-relaxed text-[var(--hud-text)]/85">
                  <strong className="text-[var(--hud-accent)]">Mechanics: </strong>
                  {inspector.mechanics}
                </div>
              )}
              {inspector.tip && (
                <div className="cyber-hazard-thin border border-[var(--hud-warn)]/45 p-2 font-cyber-ui text-[11px] leading-relaxed text-[var(--hud-warn)]">
                  <Sparkles className="mr-1 inline h-3 w-3" />
                  <strong>Beginner Tip: </strong>
                  {inspector.tip}
                </div>
              )}
            </CyberFrame>
          </aside>
        </div>

        {/* Bottom Footer Controls */}
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[var(--hud-line)] bg-[#5a0b1c]/25 px-4 py-3 sm:px-5">
          <HudButton
            variant="ghost"
            size="md"
            disabled={currentStepIdx === 0}
            onClick={() => setStep(STEPS[Math.max(0, currentStepIdx - 1)].id)}
          >
            <ChevronLeft className="h-3.5 w-3.5" /> Previous
          </HudButton>

          <div className="flex items-center gap-2">
            {step !== "review" ? (
              <HudButton
                variant="tactical"
                size="md"
                onClick={() => setStep(STEPS[Math.min(STEPS.length - 1, currentStepIdx + 1)].id)}
              >
                Next: {STEPS[Math.min(STEPS.length - 1, currentStepIdx + 1)].short}
                <ChevronRight className="h-3.5 w-3.5" />
              </HudButton>
            ) : null}

            <HudButton
              variant="cta"
              size="md"
              disabled={busy || validationIssues.length > 0}
              onClick={handleSubmit}
            >
              <Check className="h-3.5 w-3.5" />
              {busy ? "Creating…" : "Create & Attach to Campaign"}
            </HudButton>
          </div>
        </div>
      </CyberFrame>
    </div>
  );

  return typeof document !== "undefined" ? createPortal(modalNode, document.body) : modalNode;
}
