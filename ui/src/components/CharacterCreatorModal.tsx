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
  HelpCircle,
  Heart,
  Minus,
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
  createAndAttachCharacter,
  createRulesPlayerCharacter,
  fetchCreationReference,
} from "../api";
import { clearDraft, loadDraft, saveDraft } from "../draftStorage";
import {
  STAT_NAMES,
  type CreationMethodInfo,
  type CreationReference,
  type CreationRoleInfo,
  type CreationShopItem,
  type CreationSkillInfo,
  type StatName,
} from "../types";
import { FieldAiActions } from "./FieldAiActions";

interface CharacterCreatorModalProps {
  open: boolean;
  campaignId: string;
  campaignRevision: number;
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

const BASIC_SKILL_DEFAULTS: Record<string, number> = {
  Athletics: 2,
  Brawling: 2,
  Concentration: 2,
  Conversation: 2,
  Education: 2,
  Evasion: 2,
  "First Aid": 2,
  "Human Perception": 2,
  "Language (Streetslang)": 2,
  "Local Expert (Your Home)": 2,
  Perception: 2,
  Persuasion: 2,
  Stealth: 2,
};

const MAKER_SPECIALTIES = [
  "Field Expertise",
  "Upgrade Expertise",
  "Fabrication Expertise",
  "Invention Expertise",
] as const;

const PHARMA_RECIPES = ["Speedheal", "Rapidetox", "Stim", "Surge", "Antibiotic"] as const;

const NOMAD_MOTO_PRESETS = [
  "Compact Groundcar",
  "High Performance Groundcar",
  "Superbike",
  "Armored Chassis",
  "Smuggling Compartment",
  "Heavy Chassis",
  "NOS (Nitrous Boost)",
  "Bulletproof Glass",
];

const SPECIALIZATION_SUGGESTIONS: Record<string, string[]> = {
  Language: ["English", "Spanish", "Japanese", "Mandarin Chinese", "Arabic", "Russian", "French", "German", "Korean"],
  "Local Expert": ["Your Home", "Watson", "Heywood", "Pacifica", "Westbrook", "City Center", "Santo Domingo", "Badlands"],
  Science: ["Biology", "Chemistry", "Physics", "Computer Science", "Botany", "Genetics"],
  "Play Instrument": ["Electric Guitar", "Synth", "Drums", "Saxophone", "Vocals", "Bass"],
  "Martial Arts": ["Karate", "Taekwondo", "Judo", "Aikido"],
};

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

function isBasicSkillName(name: string): boolean {
  const lower = name.trim().toLowerCase();
  if (lower in Object.fromEntries(Object.keys(BASIC_SKILL_DEFAULTS).map((k) => [k.toLowerCase(), true]))) {
    return true;
  }
  return lower.startsWith("language (") || lower.startsWith("local expert (");
}

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

function buildSmart62Stats(keyStats: StatName[]): Record<StatName, number> {
  const res: Record<StatName, number> = {
    INT: 6,
    REF: 6,
    DEX: 6,
    TECH: 5,
    COOL: 6,
    WILL: 6,
    LUCK: 6,
    MOVE: 6,
    BODY: 6,
    EMP: 6,
  };
  // Sum above is 59 -> +3 points into keyStats (capped at 8)
  let remaining = 62 - Object.values(res).reduce((a, b) => a + b, 0);
  for (const s of keyStats) {
    while (remaining > 0 && res[s] < 8) {
      res[s] += 1;
      remaining -= 1;
    }
  }
  for (const s of STAT_NAMES) {
    if (remaining <= 0) break;
    while (remaining > 0 && res[s] < 8) {
      res[s] += 1;
      remaining -= 1;
    }
  }
  return res;
}

function defaultCompleteSkills(roleInfo: CreationRoleInfo | undefined): Record<string, number> {
  const out: Record<string, number> = { ...BASIC_SKILL_DEFAULTS };
  // 13 Basic skills * 2 = 26 pts; 60 pts left to hit 86.
  const roleKeys = Object.keys(roleInfo?.skills ?? {}).filter(
    (k) => !isBasicSkillName(k) && !/autofire|martial arts|paramedic|heavy weapons|pilot|electronics|demolitions/i.test(k),
  );
  // Allocate 6 points each to top 4 role skills (24) + boost 9 core/basic/role skills cleanly to 86
  const focus = [
    ...roleKeys.slice(0, 5),
    "Perception",
    "Evasion",
    "Handgun",
    "Athletics",
    "Stealth",
    "Persuasion",
    "First Aid",
    "Brawling",
  ];
  let budget = 86 - Object.values(out).reduce((a, b) => a + b, 0);
  for (const name of focus) {
    if (budget <= 0) break;
    const cur = out[name] ?? 0;
    const add = Math.min(6 - cur, budget, cur === 0 ? 6 : 4);
    if (add > 0) {
      out[name] = cur + add;
      budget -= add;
    }
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
  campaignRevision,
  soloRevision,
  onClose,
  onCreated,
  onNotify,
}: CharacterCreatorModalProps) {
  const [refData, setRefData] = useState<CreationReference | null>(null);
  const [loadingRef, setLoadingRef] = useState(false);
  const [step, setStep] = useState<CreatorStep>("identity");
  const [inspector, setInspector] = useState<InspectorCard>(DEFAULT_INSPECTOR);
  const [busy, setBusy] = useState(false);

  // Core Identity & Mode
  const [name, setName] = useState("");
  const [pronouns, setPronouns] = useState("");
  const [age, setAge] = useState("");
  const [conceptTagline, setConceptTagline] = useState("");
  const [method, setMethod] = useState<"streetrat" | "edgerunner" | "complete_package" | "freeform">("streetrat");
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
  const [fixerLanguage, setFixerLanguage] = useState("Spanish");
  const [nomadVehicles, setNomadVehicles] = useState<string[]>([
    "Compact Groundcar",
    "Superbike",
    "Smuggling Compartment",
    "Armored Chassis",
  ]);
  const [execTeamName, setExecTeamName] = useState("Kaito Reyes");
  const [execTeamRole, setExecTeamRole] = useState("Covert Operative / Driver");

  // STATs & template dice
  const [streetratRoll, setStreetratRoll] = useState<number>(1);
  const [edgerunnerRolls, setEdgerunnerRolls] = useState<number[]>([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
  const [customStats, setCustomStats] = useState<Record<StatName, number>>({ ...FALLBACK_STATS });

  // Skills
  const [edgerunnerSkills, setEdgerunnerSkills] = useState<Record<string, number>>({});
  const [customSkills, setCustomSkills] = useState<Record<string, number>>({ ...BASIC_SKILL_DEFAULTS, Handgun: 6, Perception: 6 });
  const [specializations, setSpecializations] = useState<Record<string, string>>({
    "Play Instrument": "Electric Guitar",
    Science: "Biology",
    "Martial Arts": "Karate",
  });
  const [skillFilter, setSkillFilter] = useState("");
  const [skillGroupFilter, setSkillGroupFilter] = useState<string>("All");
  const [customNewSkill, setCustomNewSkill] = useState("");
  const [specBasePick, setSpecBasePick] = useState<"Language" | "Local Expert" | "Science" | "Play Instrument" | "Martial Arts">("Language");
  const [specFocusInput, setSpecFocusInput] = useState("");

  // Lifepath, Backstory & Established History
  const [culturalRegion, setCulturalRegion] = useState("North American");
  const [culturalLanguage, setCulturalLanguage] = useState("Spanish");
  const [personality, setPersonality] = useState("Stable and serious");
  const [clothingStyle, setClothingStyle] = useState("Urban Flash (Flashy, Technological, Streetwear)");
  const [hairstyle, setHairstyle] = useState("Short and spiked");
  const [affectation, setAffectation] = useState("Mirrorshades");
  const [valueMost, setValueMost] = useState("Your word");
  const [feelingsAboutPeople, setFeelingsAboutPeople] = useState("People are untrustworthy. Don't depend on anyone.");
  const [valuedPerson, setValuedPerson] = useState("A friend");
  const [valuedPossession, setValuedPossession] = useState("A weapon");
  const [familyBackground, setFamilyBackground] = useState("Edgerunners (Always moving based on parents' latest gig)");
  const [childhoodEnv, setChildhoodEnv] = useState("Ran on The Street, with no adult supervision");
  const [familyCrisis, setFamilyCrisis] = useState("Your family lost everything through betrayal.");
  const [lifeGoal, setLifeGoal] = useState("Get off The Street no matter what it takes.");
  const [roleLifepath, setRoleLifepath] = useState<Record<string, string>>({});
  const [friends, setFriends] = useState<FriendEntry[]>([]);
  const [enemies, setEnemies] = useState<EnemyEntry[]>([]);
  const [loveAffairs, setLoveAffairs] = useState<LoveEntry[]>([]);
  const [backstorySummary, setBackstorySummary] = useState("");
  const [establishedHistory, setEstablishedHistory] = useState("");
  const [appearanceNotes, setAppearanceNotes] = useState("");
  const [aiBioGuidance, setAiBioGuidance] = useState("");
  const [aiContactsGuidance, setAiContactsGuidance] = useState("");
  const [aiBusyKey, setAiBusyKey] = useState<string | null>(null);
  const [aiError, setAiError] = useState("");

  // Gear, Cyberware, Fashion
  const [weaponChoices, setWeaponChoices] = useState<Record<string, string>>({});
  const [outfitChoice, setOutfitChoice] = useState("");
  const [cyberwareChoice, setCyberwareChoice] = useState("");
  const [cyberwareChoice2, setCyberwareChoice2] = useState("");
  const [shopCategory, setShopCategory] = useState<
    "weapon" | "armor" | "cyberware" | "gear" | "program" | "hardware" | "vehicle" | "drug" | "fashion"
  >("weapon");
  const [weaponSubFilter, setWeaponSubFilter] = useState<
    "all" | "pistols" | "rifles" | "exotic" | "excellent" | "standard" | "poor" | "melee" | "attachment" | "ammo"
  >("all");
  const [armorSubFilter, setArmorSubFilter] = useState<"all" | "body" | "head" | "shield">("all");
  const [cyberwareSubFilter, setCyberwareSubFilter] = useState<
    "all" | "foundation" | "neural" | "cyberoptic" | "cyberaudio" | "cyberlimb" | "body" | "fashionware"
  >("all");
  const [programSubFilter, setProgramSubFilter] = useState<"all" | "booster" | "defender" | "attacker" | "black_ice">("all");
  const [shopSort, setShopSort] = useState<"cost_asc" | "cost_desc" | "name_asc" | "sp_desc" | "hl_asc">("cost_asc");
  const [affordableOnly, setAffordableOnly] = useState(false);
  const [loadoutOpen, setLoadoutOpen] = useState(false);
  const [inspectedItemId, setInspectedItemId] = useState<string | null>(null);
  const [shopSearch, setShopSearch] = useState("");
  const [cartItems, setCartItems] = useState<Array<{ name: string; category: string; cost_eb: number; hl?: number; sp?: number; location?: string; install?: string; notes?: string; qty: number }>>([]);
  const [selectedFashion, setSelectedFashion] = useState<Array<{ name: string; cost_eb: number; style: string }>>([]);
  const [freeformMoney, setFreeformMoney] = useState(1500);
  const [draftRestored, setDraftRestored] = useState(false);

  const draftKey = `character:${campaignId}`;
  const hydratedRef = useRef(false);
  const prevRoleRef = useRef<string | null>(null);
  const skipNextRoleResetRef = useRef(false);

  const resetCharacterDefaults = () => {
    setStep("identity");
    setName("");
    setPronouns("");
    setAge("");
    setConceptTagline("");
    setMethod(refData && !refData.rules_indexed ? "freeform" : "streetrat");
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
    setFixerLanguage("Spanish");
    setNomadVehicles(["Compact Groundcar", "Superbike", "Smuggling Compartment", "Armored Chassis"]);
    setExecTeamName("Kaito Reyes");
    setExecTeamRole("Covert Operative / Driver");
    setStreetratRoll(1);
    setEdgerunnerRolls([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
    setCustomStats({ ...FALLBACK_STATS });
    setEdgerunnerSkills(roleInfo && Object.keys(roleInfo.skills).length === 20 ? { ...roleInfo.skills } : {});
    setCustomSkills({ ...BASIC_SKILL_DEFAULTS, Handgun: 6, Perception: 6 });
    setSpecializations({
      "Play Instrument": "Electric Guitar",
      Science: "Biology",
      "Martial Arts": "Karate",
    });
    setCulturalRegion("North American");
    setCulturalLanguage("Spanish");
    setPersonality("Stable and serious");
    setClothingStyle("Urban Flash (Flashy, Technological, Streetwear)");
    setHairstyle("Short and spiked");
    setAffectation("Mirrorshades");
    setValueMost("Your word");
    setFeelingsAboutPeople("People are untrustworthy. Don't depend on anyone.");
    setValuedPerson("A friend");
    setValuedPossession("A weapon");
    setFamilyBackground("Edgerunners (Always moving based on parents' latest gig)");
    setChildhoodEnv("Ran on The Street, with no adult supervision");
    setFamilyCrisis("Your family lost everything through betrayal.");
    setLifeGoal("Get off The Street no matter what it takes.");
    setRoleLifepath({});
    setFriends([]);
    setEnemies([]);
    setLoveAffairs([]);
    setBackstorySummary("");
    setEstablishedHistory("");
    setAppearanceNotes("");
    setAiBioGuidance("");
    setAiContactsGuidance("");
    setWeaponChoices({});
    setOutfitChoice("");
    setCyberwareChoice("");
    setCyberwareChoice2("");
    setCartItems([]);
    setSelectedFashion([]);
    setFreeformMoney(1500);
    setDraftRestored(false);
    prevRoleRef.current = null;
  };

  useEffect(() => {
    if (!open) {
      hydratedRef.current = false;
      return;
    }
    const saved = loadDraft<Record<string, unknown>>(draftKey);
    if (saved) {
      skipNextRoleResetRef.current = true;
      if (typeof saved.step === "string") setStep(saved.step as CreatorStep);
      if (typeof saved.name === "string") setName(saved.name);
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
      if (typeof saved.aiBioGuidance === "string") setAiBioGuidance(saved.aiBioGuidance);
      if (typeof saved.aiContactsGuidance === "string") setAiContactsGuidance(saved.aiContactsGuidance);
      if (saved.weaponChoices && typeof saved.weaponChoices === "object") setWeaponChoices(saved.weaponChoices as Record<string, string>);
      if (typeof saved.outfitChoice === "string") setOutfitChoice(saved.outfitChoice);
      if (typeof saved.cyberwareChoice === "string") setCyberwareChoice(saved.cyberwareChoice);
      if (typeof saved.cyberwareChoice2 === "string") setCyberwareChoice2(saved.cyberwareChoice2);
      if (Array.isArray(saved.cartItems)) setCartItems(saved.cartItems as typeof cartItems);
      if (Array.isArray(saved.selectedFashion)) setSelectedFashion(saved.selectedFashion as typeof selectedFashion);
      if (typeof saved.freeformMoney === "number") setFreeformMoney(saved.freeformMoney);
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
      aiBioGuidance,
      aiContactsGuidance,
      weaponChoices,
      outfitChoice,
      cyberwareChoice,
      cyberwareChoice2,
      cartItems,
      selectedFashion,
      freeformMoney,
    });
  }, [
    open,
    draftKey,
    step,
    name,
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
    aiBioGuidance,
    aiContactsGuidance,
    weaponChoices,
    outfitChoice,
    cyberwareChoice,
    cyberwareChoice2,
    cartItems,
    selectedFashion,
    freeformMoney,
  ]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoadingRef(true);
    fetchCreationReference()
      .then((data) => {
        if (cancelled) return;
        setRefData(data);
        if (!data.rules_indexed) {
          setMethod("freeform");
        }
      })
      .catch(() => {
        // Fallback works cleanly even if backend reference endpoint is unavailable
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

  // Initialize Role-dependent defaults cleanly when Role changes (preserving restored drafts)
  useEffect(() => {
    if (!roleInfo) return;
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
        setCustomStats(buildSmart62Stats(roleInfo.key_stats));
        setCustomSkills(defaultCompleteSkills(roleInfo));
      }
    }
    if (roleChanged || Object.keys(weaponChoices).length === 0) {
      const nextWep: Record<string, string> = {};
      roleInfo.starting_weapons.forEach((w, idx) => {
        if (w.type === "choice" && w.options?.length) {
          nextWep[w.label || `choice-${idx}`] = w.options[0];
        }
      });
      setWeaponChoices(nextWep);
    }
    if (roleChanged || !outfitChoice) {
      setOutfitChoice(roleInfo.outfit_choice?.options[0] ?? "");
    }
    if (roleChanged || !cyberwareChoice) {
      setCyberwareChoice(roleInfo.cyberware_choice?.options[0]?.name ?? "");
    }
    if (roleChanged || !cyberwareChoice2) {
      setCyberwareChoice2(roleInfo.cyberware_choice_2?.options[0]?.name ?? "");
    }
    if (roleChanged || Object.keys(roleLifepath).length === 0) {
      const nextRoleLp: Record<string, string> = {};
      for (const f of roleInfo.role_lifepath) {
        nextRoleLp[f.key] = f.options[0] ?? "";
      }
      setRoleLifepath(nextRoleLp);
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
    if (selectedRole === "Medtech" && method !== "freeform") {
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
    for (const req of Object.keys(BASIC_SKILL_DEFAULTS)) {
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
  }, [method, customSkills]);

  // Starting Gear & Humanity preview
  const gearSummary = useMemo(() => {
    const inventory: Record<string, number> = {};
    const cyberware: Array<{ name: string; hl: number; install?: string; notes?: string; cost_eb?: number }> = [];
    let equippedWeapon: string | undefined;
    let equippedArmor: { name: string; sp: number } | undefined;
    let money = freeformMoney;
    let fashionSpent = 0;

    if ((method === "streetrat" || method === "edgerunner") && roleInfo) {
      money = 500;
      for (let i = 0; i < roleInfo.starting_weapons.length; i += 1) {
        const w = roleInfo.starting_weapons[i];
        const chosen = w.type === "choice" ? weaponChoices[w.label || `choice-${i}`] || w.options?.[0] : w.item;
        if (!chosen) continue;
        const qty = w.qty ?? 1;
        inventory[chosen] = (inventory[chosen] ?? 0) + qty;
        if (!equippedWeapon && !/ammunition|grenade|shield/i.test(chosen)) {
          equippedWeapon = chosen;
        }
      }
      for (const a of roleInfo.starting_armor) {
        inventory[a] = (inventory[a] ?? 0) + 1;
        if (!equippedArmor && /Body/i.test(a)) {
          equippedArmor = { name: a, sp: 11 };
        }
      }
      for (const o of roleInfo.starting_outfit) {
        inventory[o] = (inventory[o] ?? 0) + 1;
      }
      if (outfitChoice) {
        inventory[outfitChoice] = (inventory[outfitChoice] ?? 0) + 1;
      }
      for (const cw of roleInfo.starting_cyberware) {
        cyberware.push({ ...cw });
      }
      if (roleInfo.cyberware_choice && cyberwareChoice) {
        const found = roleInfo.cyberware_choice.options.find((c) => c.name === cyberwareChoice);
        if (found) cyberware.push({ ...found });
      }
      if (roleInfo.cyberware_choice_2 && cyberwareChoice2) {
        const found = roleInfo.cyberware_choice_2.options.find((c) => c.name === cyberwareChoice2);
        if (found) cyberware.push({ ...found });
      }
    } else {
      let spent = 0;
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
            const itemSp = typeof item.sp === "number" && item.sp > 0 ? item.sp : 11;
            if (!isShield && (loc !== "head" || !equippedArmor) && (!equippedArmor || itemSp > equippedArmor.sp)) {
              equippedArmor = { name: item.name, sp: itemSp };
            }
          }
        }
        spent += item.cost_eb * item.qty;
      }
      for (const f of selectedFashion) {
        inventory[f.name] = (inventory[f.name] ?? 0) + 1;
        fashionSpent += f.cost_eb;
      }
      money = method === "complete_package" ? Math.max(0, 2550 - spent) : freeformMoney;
    }

    const totalHl = cyberware.reduce((acc, c) => acc + (Number.isFinite(c.hl) ? c.hl : 0), 0);
    return {
      inventory,
      cyberware,
      equippedWeapon,
      equippedArmor,
      money,
      fashionSpent,
      spentEb: method === "complete_package" ? 2550 - money : 0,
      totalHl,
    };
  }, [method, roleInfo, weaponChoices, outfitChoice, cyberwareChoice, cyberwareChoice2, cartItems, selectedFashion, freeformMoney]);

  const maxHp = 10 + 5 * Math.ceil((activeStats.BODY + activeStats.WILL) / 2);
  const woundThreshold = Math.ceil(maxHp / 2);
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

  const cyberwarePrereqWarnings = useMemo(() => {
    const names = gearSummary.cyberware.map((c) => c.name.toLowerCase());
    const has = (needle: string) => names.some((n) => n.includes(needle));
    const warnings: Array<{ option: string; foundation: string; cost_eb: number; hl: number }> = [];
    const rules: Array<{ foundation: string; match: RegExp; cost_eb: number; hl: number }> = [
      {
        foundation: "Neural Link",
        match: /kerenzikov|sandevistan|pain editor|chipware socket|interface plugs|reflex co-?processor|tactile boost|olfactory boost|chemical analyzer/i,
        cost_eb: 500,
        hl: 7,
      },
      {
        foundation: "Cybereye",
        match: /anti-dazzle|chyron|color shift|dartgun|image enhance|low light|infrared|uv|microoptics|microvideo|radiation detector|targeting scope|teleoptics|virtuality/i,
        cost_eb: 100,
        hl: 7,
      },
      {
        foundation: "Cyberaudio Suite",
        match: /amplified hearing|audio recorder|bug detector|homing tracer|internal agent|level damper|radio communicator|radio scanner|radar detector|scrambler|voice stress analyzer/i,
        cost_eb: 500,
        hl: 7,
      },
    ];
    for (const cw of gearSummary.cyberware) {
      for (const r of rules) {
        if (r.match.test(cw.name) && !has(r.foundation.toLowerCase())) {
          if (!warnings.some((w) => w.foundation === r.foundation)) {
            warnings.push({ option: cw.name, foundation: r.foundation, cost_eb: r.cost_eb, hl: r.hl });
          }
        }
      }
    }
    return warnings;
  }, [gearSummary.cyberware]);

  // Cyberware Foundation Slot-Cap checks (Corebook pp. 111–116, 360–368)
  const cyberwareSlotWarnings = useMemo(() => {
    const rules: Array<{
      foundation: string;
      cap: number;
      matchFoundation: RegExp;
      matchOption: RegExp;
      slotStr: string;
    }> = [
      {
        foundation: "Cybereye",
        cap: 3,
        matchFoundation: /^cybereye/i,
        matchOption:
          /anti-dazzle|chyron|color shift|dartgun|image enhance|low light|infrared|uv|microoptics|microvideo|radiation detector|targeting scope|teleoptics|virtuality|flashbulb/i,
        slotStr: "cyberoptic",
      },
      {
        foundation: "Cyberaudio Suite",
        cap: 3,
        matchFoundation: /cyberaudio suite/i,
        matchOption:
          /amplified hearing|audio recorder|bug detector|homing tracer|internal agent|level damper|radio communicator|radio scanner|radar detector|scrambler|voice stress analyzer/i,
        slotStr: "cyberaudio option",
      },
      {
        foundation: "Neural Link",
        cap: 5,
        matchFoundation: /neural link/i,
        matchOption:
          /kerenzikov|sandevistan|pain editor|chipware socket|interface plugs|reflex co-?processor|tactile boost|olfactory boost|chemical analyzer|braindance recorder|skill chip|memory chip/i,
        slotStr: "neural",
      },
      {
        foundation: "Cyberarm",
        cap: 4,
        matchFoundation: /^cyberarm/i,
        matchOption:
          /big knucks|cyberdeck|grapple hand|medscanner|popup|quick change mount|rippers|scratchers|shoulder cam|slice [‘']n dice|standard hand|subdermal grip|techscanner|tool hand|wolvers|hardened shielding|plastic covering|realskinn|superchrome/i,
        slotStr: "cyberarm option",
      },
      {
        foundation: "Cyberleg",
        cap: 3,
        matchFoundation: /^cyberleg/i,
        matchOption:
          /standard foot|grip foot|jump booster|skate foot|talon foot|web foot|tread unit/i,
        slotStr: "cyberleg option",
      },
    ];

    const getOptionSlots = (itemName: string): number => {
      const shopItem = refData?.shop.cyberware?.find(
        (c) => c.name.toLowerCase() === itemName.toLowerCase()
      );
      if (typeof shopItem?.stats?.slots_required === "number" && shopItem.stats.slots_required > 0) {
        return shopItem.stats.slots_required;
      }
      if (/dartgun|cyberdeck|popup shield|tread unit/i.test(itemName)) return 3;
      if (
        /anti-dazzle|image enhance|low light|infrared|uv|microvideo|virtuality|medscanner|popup|shoulder cam|techscanner|grip foot|jump booster|skate foot|web foot/i.test(
          itemName
        )
      ) {
        return 2;
      }
      return 1;
    };

    const warnings: Array<{
      foundation: string;
      usedSlots: number;
      maxSlots: number;
      options: string[];
    }> = [];

    for (const r of rules) {
      const foundationCount = gearSummary.cyberware.filter((c) =>
        r.matchFoundation.test(c.name)
      ).length;
      const maxSlots = Math.max(1, foundationCount) * r.cap;

      const matchingOptions: Array<{ name: string; slots: number }> = [];
      for (const cw of gearSummary.cyberware) {
        if (r.matchFoundation.test(cw.name)) continue;
        const shopItem = refData?.shop.cyberware?.find(
          (c) => c.name.toLowerCase() === cw.name.toLowerCase()
        );
        const slot = String(shopItem?.stats?.slot ?? "").toLowerCase();
        const isMatch =
          r.matchOption.test(cw.name) ||
          (slot.includes(r.slotStr) && !slot.includes("foundational"));
        if (isMatch) {
          matchingOptions.push({ name: cw.name, slots: getOptionSlots(cw.name) });
        }
      }

      const totalSlotsUsed = matchingOptions.reduce((acc, o) => acc + o.slots, 0);
      if (totalSlotsUsed > maxSlots) {
        warnings.push({
          foundation: r.foundation,
          usedSlots: totalSlotsUsed,
          maxSlots,
          options: matchingOptions.map((o) => o.name),
        });
      }
    }

    return warnings;
  }, [gearSummary.cyberware, refData]);

  // Validation checks
  const validationIssues = useMemo(() => {
    const issues: string[] = [];
    if (!name.trim()) issues.push("Enter a Handle / Name on Step 1 (Identity & Role).");
    if (method === "complete_package") {
      if (!refData?.rules_indexed) {
        issues.push("Complete Package needs your Corebook PDF uploaded in Settings → Corebook PDF (or switch to Freeform).");
      }
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
    if (selectedRole === "Tech" && method !== "freeform") {
      const sum = Object.values(techMakerRanks).reduce((a, b) => a + b, 0);
      if (sum !== 8) issues.push(`Tech Maker specialty points must total 8 (currently ${sum}).`);
    }
    if (selectedRole === "Medtech" && method !== "freeform") {
      const sum = Object.values(medtechAlloc).reduce((a, b) => a + b, 0);
      if (sum !== 4) issues.push(`Medtech Medicine specialty points must total 4 (currently ${sum}).`);
    }
    return issues;
  }, [
    name,
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
      const p = pickRandom(tables.personality ?? [personality]);
      const cs = pickRandom(tables.clothing_style ?? [clothingStyle]);
      const hs = pickRandom(tables.hairstyle ?? [hairstyle]);
      const af = pickRandom(tables.affectation ?? [affectation]);
      const vm = pickRandom(tables.value_most ?? [valueMost]);
      const fp = pickRandom(tables.feelings_about_people ?? [feelingsAboutPeople]);
      const vp = pickRandom(tables.valued_person ?? [valuedPerson]);
      const vpos = pickRandom(tables.valued_possession ?? [valuedPossession]);
      const fb = pickRandom(tables.family_background ?? [familyBackground]);
      const ce = pickRandom(tables.childhood_environment ?? [childhoodEnv]);
      const fc = pickRandom(tables.family_crisis ?? [familyCrisis]);
      const lg = pickRandom(tables.life_goal ?? [lifeGoal]);
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

      const friendCount = Math.max(0, d(10) - 7);
      const nextFriends: FriendEntry[] = Array.from({ length: friendCount }, (_, idx) => ({
        name: `Contact #${idx + 1}`,
        relationship: pickRandom(tables.friend_relationship ?? ["Someone from The Street"]),
        note: "Reliable ally from before Session 1.",
      }));
      setFriends(nextFriends);

      const enemyCount = Math.max(0, d(10) - 7);
      const nextEnemies: EnemyEntry[] = Array.from({ length: enemyCount }, (_, idx) => ({
        who: pickRandom(tables.enemy_who ?? ["Ex-friend"]),
        name: `Rival #${idx + 1}`,
        wronged: d(2) === 1 ? "I wronged them" : "They wronged me",
        cause: pickRandom(tables.enemy_cause ?? ["Betrayal"]),
        backup: pickRandom(tables.enemy_backup ?? ["Just themselves"]),
        revenge: pickRandom(tables.sweet_revenge ?? ["Avoid the scum."]),
      }));
      setEnemies(nextEnemies);

      const loveCount = Math.max(0, d(10) - 7);
      const nextLove: LoveEntry[] = Array.from({ length: loveCount }, (_, idx) => ({
        name: `Former Flame #${idx + 1}`,
        outcome: pickRandom(tables.tragic_love ?? ["It just didn't work out."]),
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

  const handleAiAssist = async (target: "bio" | "contacts", assistMode: "scratch" | "expand", field?: string) => {
    if (aiBusy) return;
    setAiError("");
    setAiBusyKey(`${target}:${assistMode}:${field ?? "all"}`);
    try {
      const res = await assistCharacterCreation({
        target,
        mode: assistMode,
        ...(field ? { field } : {}),
        guidance: (target === "bio" ? aiBioGuidance : aiContactsGuidance).trim() || undefined,
        character: {
          name: name.trim() || "Unnamed Edgerunner",
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
        const label =
          field === "concept"
            ? "Concept"
            : field === "summary"
              ? "Backstory"
              : field === "established_history"
                ? "Established History"
                : field === "appearance"
                  ? "Signature Look"
                  : "backstory & history";
        onNotify(assistMode === "scratch" ? "AI generated backstory & established history from sheet + Corebook." : `AI improved your ${label}.`);
      } else {
        if ((!field || field === "friends") && res.friends?.length) setFriends(res.friends);
        if ((!field || field === "enemies") && res.enemies?.length) {
          setEnemies(
            res.enemies.map((e) => ({
              who: e.who,
              name: e.name,
              wronged: e.wronged === "I wronged them" ? "I wronged them" : "They wronged me",
              cause: e.cause,
              backup: e.backup,
              revenge: e.revenge,
            })),
          );
        }
        if ((!field || field === "tragic_love_affairs") && res.tragic_love_affairs?.length) {
          setLoveAffairs(res.tragic_love_affairs);
        }
        onNotify(
          assistMode === "scratch"
            ? "AI generated Friends, Enemies & Past Romances."
            : `AI improved your ${field ? field.replace(/_/g, " ") : "Contacts"}.`,
        );
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
      return { team_member: { name: execTeamName || "Kaito Reyes", role: execTeamRole || "Covert Operative" } };
    }
    return {};
  };

  const handleSubmit = async () => {
    if (!name.trim() || busy || validationIssues.length > 0) return;
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
      const backstoryPayload = {
        pronouns: pronouns.trim() || undefined,
        age: age.trim() || undefined,
        concept: conceptTagline.trim() || undefined,
        summary: backstorySummary.trim() || undefined,
        established_history: establishedHistory.trim() || undefined,
        appearance: appearanceNotes.trim() || undefined,
      };

      let createdId = "";
      if (method !== "freeform" && refData?.rules_indexed) {
        const res = await createRulesPlayerCharacter(campaignId, soloRevision, {
          name: name.trim(),
          role: selectedRole,
          method,
          ...(method === "streetrat" ? { template_rolls: [streetratRoll] } : {}),
          ...(method === "edgerunner" ? { template_rolls: edgerunnerRolls, skills: edgerunnerSkills } : {}),
          ...(method === "complete_package" ? { stats: customStats, skills: customSkills } : {}),
          specializations,
          role_choices: buildRoleChoicesPayload(),
          cultural_language: culturalLanguage.trim().toLowerCase() === "streetslang" ? undefined : culturalLanguage.trim() || undefined,
          lifepath: lifepathPayload,
          backstory: backstoryPayload,
          starting_gear: {
            inventory: gearSummary.inventory,
            cyberware: gearSummary.cyberware,
            humanity_loss: gearSummary.totalHl,
            equipped_weapon: gearSummary.equippedWeapon,
            equipped_armor: gearSummary.equippedArmor,
            fashion: selectedFashion,
            money_spent_eb: gearSummary.spentEb,
          },
        });
        createdId = res.character_id;
      } else {
        const created = await createAndAttachCharacter(campaignId, campaignRevision, {
          name: name.trim(),
          stats: activeStats,
          skills: effectiveSkills,
          money: gearSummary.money,
          inventory: gearSummary.inventory,
          humanity: startingHumanity,
          detail: {
            roles: [{ role: selectedRole, rank: 4, choices: buildRoleChoicesPayload() }],
            creation: { method: "freeform", initial_emp: activeStats.EMP },
            lifepath: lifepathPayload,
            backstory: backstoryPayload,
            cyberware: gearSummary.cyberware,
            ...(gearSummary.equippedWeapon ? { equipped_weapon: gearSummary.equippedWeapon } : {}),
            ...(gearSummary.equippedArmor ? { equipped_armor: gearSummary.equippedArmor } : {}),
            ...(selectedFashion.length ? { fashion: selectedFashion } : {}),
          },
        });
        createdId = created.id;
      }

      clearDraft(draftKey);
      await onCreated(createdId, name.trim());
      resetCharacterDefaults();
      onClose();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Failed to create character");
    } finally {
      setBusy(false);
    }
  };

  if (!open) return null;

  const statDescriptions = refData?.stats;
  const methodsList: CreationMethodInfo[] = refData?.methods ?? [
    {
      id: "streetrat",
      name: "Streetrat (Templates)",
      badge: "Best for Beginners",
      summary: "Pick a Role, roll/choose 1 template row, and start playing immediately.",
      rules: "Uses Corebook Role templates, 20 Role skills, and preset starter gear + 500 eb.",
    },
    {
      id: "edgerunner",
      name: "Edgerunner (Fast & Dirty)",
      badge: "Balanced Control",
      summary: "Keep your Role gear while rolling STAT columns and customizing 86 skill points.",
      rules: "Customize 86 weighted points across your Role's 20 skills + 500 eb.",
    },
    {
      id: "complete_package",
      name: "Complete Package (Calculated)",
      badge: "Full Point-Buy",
      summary: "Full custom 62 STAT points, 86 Skill points, and 2,550 eb + 800 eb fashion.",
      rules: "13 Basic skills >= 2; buy any weapons, armor, and cyberware directly.",
    },
    {
      id: "freeform",
      name: "Freeform / Custom Sheet",
      badge: "Unrestricted",
      summary: "Set any STATs, Skills, Backstory, and Gear with zero point-buy locks.",
      rules: "Full creative freedom for house rules or imports.",
    },
  ];

  const availableSkillsForEdit: CreationSkillInfo[] = (() => {
    if (method === "edgerunner" && roleInfo) {
      return Object.keys(edgerunnerSkills).map((skillName) => {
        const meta = skillIndex.get(skillName.split("(", 1)[0].trim().toLowerCase());
        return {
          name: skillName,
          stat: skillStat(skillName, skillIndex),
          cost: skillBaseCost(skillName, skillIndex),
          basic: isBasicSkillName(skillName),
          specializable: skillName.includes("(choose 1)"),
          group: meta?.group ?? "Role",
          printed_page: meta?.printed_page,
          summary: meta?.summary ?? `${skillName} (${skillStat(skillName, skillIndex)})`,
          description: meta?.description ?? `${skillName} skill.`,
        };
      });
    }
    const baseList = refData?.skills ?? [];
    if (method === "complete_package" || method === "freeform") {
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
    if (weaponSubFilter === "attachment") {
      const extra = refData?.shop?.attachment ?? [];
      const seen = new Set(baseWeapons.map((w) => w.name.toLowerCase()));
      return [...baseWeapons, ...extra.filter((a) => !seen.has(a.name.toLowerCase()))];
    }
    if (weaponSubFilter === "ammo") {
      const extra = refData?.shop?.ammo ?? [];
      const seen = new Set(baseWeapons.map((w) => w.name.toLowerCase()));
      return [...baseWeapons, ...extra.filter((a) => !seen.has(a.name.toLowerCase()))];
    }
    return baseWeapons;
  })();

  const classifyCyberwareSubcategory = (
    item: CreationShopItem,
  ): "foundation" | "neural" | "cyberoptic" | "cyberaudio" | "cyberlimb" | "body" | "fashionware" => {
    const slot = String(item.stats?.slot ?? "").toLowerCase();
    const n = item.name.toLowerCase();
    if (slot.includes("foundational") || /^(neural link|cybereye|cyberaudio suite|cyberarm|cyberleg)\b/i.test(n)) {
      return "foundation";
    }
    if (
      slot.includes("neural") ||
      /kerenzikov|sandevistan|pain editor|chipware|interface plugs|reflex|tactile|olfactory|chemical|braindance|skill chip|memory chip/i.test(n)
    ) {
      return "neural";
    }
    if (
      slot.includes("cyberoptic") ||
      /anti-dazzle|chyron|color shift|dartgun|image enhance|low light|infrared|uv|microoptics|microvideo|radiation detector|targeting scope|teleoptics|virtuality/i.test(n)
    ) {
      return "cyberoptic";
    }
    if (
      slot.includes("cyberaudio") ||
      /amplified hearing|audio recorder|bug detector|homing tracer|internal agent|level damper|radio|radar|scrambler|voice stress/i.test(n)
    ) {
      return "cyberaudio";
    }
    if (
      slot.includes("cyberarm") ||
      slot.includes("cyberleg") ||
      /hand|foot|knucks|rippers|scratchers|wolvers|slice|popup|grapple|medscanner|techscanner|shoulder cam|quick change|skate|jump|tread|hardened shielding|realskinn|superchrome|plastic covering/i.test(n)
    ) {
      return "cyberlimb";
    }
    if (
      slot.includes("fashionware") ||
      /biomonitor|chemskin|emp threading|light tattoo|shift tacts|skinwatch|techhair/i.test(n)
    ) {
      return "fashionware";
    }
    return "body";
  };

  const classifyProgramSubcategory = (item: CreationShopItem): "booster" | "defender" | "attacker" | "black_ice" => {
    const st = String(item.stats?.subtype ?? item.stats?.class ?? "").toLowerCase();
    const sum = `${item.name} ${item.summary}`.toLowerCase();
    if (st.includes("black ice") || st.includes("ice") || /hellhound|asp|giant|kraken|liche|raven|scorpion|skunk|wisp|killer|sabertooth|dragon/i.test(sum)) {
      return "black_ice";
    }
    if (st.includes("defender") || /armor|flak|shield/i.test(sum)) return "defender";
    if (st.includes("attacker") || /sword|banhammer|deckkrash|hellbolt|nervescrub|poison flatline|superglue|vrizzbolt/i.test(sum)) return "attacker";
    return "booster";
  };

  const remainingGearEb = method === "complete_package" ? 2550 - gearSummary.spentEb : freeformMoney;
  const remainingFashionEb = method === "complete_package" ? 800 - gearSummary.fashionSpent : freeformMoney;

  const shopItemsForCategory: CreationShopItem[] = (() => {
    if (shopCategory === "fashion") return [];
    const rawList = shopCategory === "weapon" ? weaponItemsForFilter : (refData?.shop[shopCategory] ?? []);
    const filtered = rawList.filter((item) => {
      const stats = item.stats ?? {};
      if (shopCategory === "weapon" && weaponSubFilter !== "all") {
        const st = String(stats.subtype ?? "").toLowerCase();
        const wc = String(stats.weapon_class ?? "").toLowerCase();
        const q = String(stats.quality ?? "").toLowerCase();
        const cat = String(item.category ?? "").toLowerCase();
        const n = item.name.toLowerCase();
        if (weaponSubFilter === "pistols" && !/pistol|smg/.test(`${st} ${wc} ${n}`)) return false;
        if (weaponSubFilter === "rifles" && !/rifle|shotgun|bow|crossbow/.test(`${st} ${wc} ${n}`)) return false;
        if (weaponSubFilter === "exotic" && !st.includes("exotic") && !q.includes("exotic")) return false;
        if (weaponSubFilter === "excellent" && !q.includes("excellent") && !st.includes("excellent")) return false;
        if (weaponSubFilter === "standard" && !q.includes("standard") && !st.includes("standard")) return false;
        if (weaponSubFilter === "poor" && !q.includes("poor") && !st.includes("poor")) return false;
        if (weaponSubFilter === "melee" && st !== "melee" && !n.includes("melee")) return false;
        if (weaponSubFilter === "attachment" && !st.includes("attachment") && cat !== "attachment") return false;
        if (weaponSubFilter === "ammo" && !st.includes("ammo") && !st.includes("ammunition") && cat !== "ammo") return false;
      }
      if (shopCategory === "armor" && armorSubFilter !== "all") {
        const loc = String(stats.location ?? "").toLowerCase();
        if (armorSubFilter === "body" && !loc.includes("body")) return false;
        if (armorSubFilter === "head" && !loc.includes("head")) return false;
        if (armorSubFilter === "shield" && !loc.includes("shield")) return false;
      }
      if (shopCategory === "cyberware" && cyberwareSubFilter !== "all") {
        if (classifyCyberwareSubcategory(item) !== cyberwareSubFilter) return false;
      }
      if (shopCategory === "program" && programSubFilter !== "all") {
        if (classifyProgramSubcategory(item) !== programSubFilter) return false;
      }
      if (affordableOnly && method === "complete_package" && item.cost_eb > remainingGearEb) {
        return false;
      }
      if (!shopSearch.trim()) return true;
      const q = shopSearch.trim().toLowerCase();
      return (
        item.name.toLowerCase().includes(q) ||
        item.summary.toLowerCase().includes(q) ||
        String(stats.brand ?? "").toLowerCase().includes(q) ||
        String(stats.weapon_class ?? "").toLowerCase().includes(q) ||
        String(stats.slot ?? "").toLowerCase().includes(q)
      );
    });
    return [...filtered].sort((a, b) => {
      if (shopSort === "cost_desc") return b.cost_eb - a.cost_eb || a.name.localeCompare(b.name);
      if (shopSort === "name_asc") return a.name.localeCompare(b.name);
      if (shopSort === "sp_desc") return parseSpVal(b.stats) - parseSpVal(a.stats) || a.cost_eb - b.cost_eb;
      if (shopSort === "hl_asc") return parseHlVal(a.stats) - parseHlVal(b.stats) || a.cost_eb - b.cost_eb;
      return a.cost_eb - b.cost_eb || a.name.localeCompare(b.name);
    });
  })();

  const fashionItemsForDisplay = (() => {
    const q = shopSearch.trim().toLowerCase();
    const list = (refData?.fashion ?? []).filter((f) => {
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

  const busyFor = (target: "bio" | "contacts", field: string): "improve" | "regen" | null =>
    aiBusyKey === `${target}:expand:${field}`
      ? "improve"
      : aiBusyKey === `${target}:scratch:${field}`
        ? "regen"
        : null;

  const modalNode = (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/85 p-2 sm:p-4 backdrop-blur-sm"
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Edgerunner Character Sheet Creator"
        className="cyber-hud-card flex h-[92vh] max-h-[95vh] w-full max-w-7xl flex-col overflow-hidden rounded-xl bg-[#0b101b] text-slate-100 shadow-2xl"
      >
        {/* Top Modal Header with Cyber Chrome Banner */}
        <div className="relative flex flex-wrap items-center justify-between gap-2 overflow-hidden border-b border-rose-500/30 bg-[#0f1625] px-4 py-3">
          <img
            src={edgerunnerChromeBanner}
            alt=""
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 h-full w-full object-cover opacity-20"
          />
          <div className="pointer-events-none absolute inset-0 bg-gradient-to-r from-[#0b101b]/95 via-[#0f1625]/85 to-[#0b101b]/92" />
          <div className="relative z-10 flex items-center gap-3 min-w-0">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-rose-500/40 bg-rose-500/15 text-rose-300">
              <UserPlus className="h-4 w-4" />
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="truncate font-cyber-display text-sm font-bold uppercase tracking-wider text-slate-100">
                  Edgerunner Character Sheet Creator
                </h2>
                {draftRestored && (
                  <span className="rounded border border-cyan-500/40 bg-cyan-500/15 px-1.5 py-0.5 font-mono text-[10px] text-cyan-200">
                    Draft Restored
                  </span>
                )}
              </div>
              <p className="truncate font-cyber-hud text-[11px] text-slate-400">
                {name.trim() || "Unnamed Punk"} · {selectedRole} (R4) · {methodsList.find((m) => m.id === method)?.name ?? method}
              </p>
            </div>
          </div>

          <div className="relative z-10 flex items-center gap-2">
            {loadingRef && <span className="text-[11px] text-cyan-400">Loading Corebook data…</span>}
            <button
              type="button"
              onClick={() => {
                clearDraft(draftKey);
                resetCharacterDefaults();
                onNotify("Character draft cleared.");
              }}
              title="Clear unsaved draft and reset form"
              className="inline-flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-900/90 px-2 py-1 text-[11px] text-slate-300 hover:border-rose-500/50 hover:text-rose-200"
            >
              <RotateCcw className="h-3 w-3" />
              <span className="hidden sm:inline">Reset</span>
            </button>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close character creator"
              className="rounded-lg border border-slate-700 bg-slate-900 p-1.5 text-slate-400 hover:border-slate-500 hover:text-slate-100"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Step Navigation Pills */}
        <div className="flex flex-wrap items-center gap-1 border-b border-slate-800 bg-[#0d1320] px-4 py-2">
          {STEPS.map((s) => {
            const activeStep = step === s.id;
            return (
              <button
                key={s.id}
                type="button"
                onClick={() => setStep(s.id)}
                className={`rounded-md px-2.5 py-1 text-xs font-medium transition ${
                  activeStep
                    ? "border border-cyan-500/60 bg-cyan-500/15 text-cyan-200"
                    : "border border-transparent text-slate-400 hover:bg-slate-800/70 hover:text-slate-200"
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
          <div className="min-h-0 overflow-y-auto p-4 sm:p-5 space-y-5 lg:col-span-8">
            {/* STEP 1: IDENTITY & ROLE */}
            {step === "identity" && (
              <div className="space-y-5">
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-12">
                  <div className="sm:col-span-6">
                    <label className="mb-1 flex items-center justify-between text-xs font-semibold text-slate-300">
                      <span>Street Handle / Name *</span>
                      <button
                        type="button"
                        onClick={() => setName(pickRandom(HANDLE_SUGGESTIONS))}
                        className="inline-flex items-center gap-1 text-[11px] text-cyan-300 hover:text-cyan-200"
                      >
                        <Dices className="h-3 w-3" /> Roll Handle
                      </button>
                    </label>
                    <input
                      type="text"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      placeholder="e.g. Vee Mercer"
                      className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-cyan-400 focus:outline-none"
                    />
                  </div>
                  <div className="sm:col-span-3">
                    <label className="mb-1 block text-xs font-semibold text-slate-300">Pronouns</label>
                    <input
                      type="text"
                      value={pronouns}
                      onChange={(e) => setPronouns(e.target.value)}
                      placeholder="they/them, she/her…"
                      className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-cyan-400 focus:outline-none"
                    />
                  </div>
                  <div className="sm:col-span-3">
                    <label className="mb-1 block text-xs font-semibold text-slate-300">Age</label>
                    <input
                      type="text"
                      value={age}
                      onChange={(e) => setAge(e.target.value)}
                      placeholder="e.g. 24"
                      className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-cyan-400 focus:outline-none"
                    />
                  </div>
                </div>

                <div>
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <label className="block text-xs font-semibold text-slate-300">
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
                    className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                  />
                </div>

                {/* Creation Method Picker */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold uppercase tracking-wider text-slate-300">
                      Build Method
                    </span>
                    <span className="text-[11px] text-slate-400">Hover any card for rules breakdown</span>
                  </div>
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                    {methodsList.map((m) => {
                      const active = method === m.id;
                      const disabled = m.id !== "freeform" && refData !== null && !refData.rules_indexed;
                      return (
                        <button
                          key={m.id}
                          type="button"
                          disabled={disabled}
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
                              setCustomStats(buildSmart62Stats(roleInfo.key_stats));
                              setCustomSkills(defaultCompleteSkills(roleInfo));
                            }
                          }}
                          className={`rounded-lg border p-3 text-left transition ${
                            active
                              ? "border-cyan-400 bg-cyan-500/10"
                              : "border-slate-800 bg-slate-900/60 hover:border-slate-600"
                          } disabled:opacity-40`}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-xs font-bold text-slate-100">{m.name}</span>
                            <span className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[10px] text-cyan-300">
                              {m.badge}
                            </span>
                          </div>
                          <p className="mt-1 text-[11px] leading-relaxed text-slate-400">{m.summary}</p>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* All 10 Roles Grid */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold uppercase tracking-wider text-slate-300">
                      Choose Your Role (Starts at Rank 4)
                    </span>
                    <span className="text-[11px] text-slate-400">Hover or select for Role Ability info</span>
                  </div>
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                    {(refData?.roles ?? []).map((role) => {
                      const active = selectedRole === role.name;
                      return (
                        <button
                          key={role.name}
                          type="button"
                          onMouseEnter={() =>
                            setInspector({
                              title: `${role.name} · Role Ability: ${role.ability}`,
                              subtitle: `Corebook p.${role.page} · Key STATs: ${role.key_stats.join(", ")}`,
                              body: role.ability_summary,
                              tip: role.best_for,
                            })
                          }
                          onFocus={() =>
                            setInspector({
                              title: `${role.name} · Role Ability: ${role.ability}`,
                              subtitle: `Corebook p.${role.page} · Key STATs: ${role.key_stats.join(", ")}`,
                              body: role.ability_summary,
                              tip: role.best_for,
                            })
                          }
                          onClick={() => setSelectedRole(role.name)}
                          className={`rounded-lg border p-2.5 text-left transition ${
                            active
                              ? "border-rose-500/80 bg-rose-500/10"
                              : "border-slate-800 bg-slate-900/50 hover:border-slate-600"
                          }`}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-xs font-bold text-slate-100">{role.name}</span>
                            <span className="rounded bg-cyan-500/15 px-1.5 py-0.5 font-mono text-[10px] text-cyan-300">
                              {role.ability}
                            </span>
                          </div>
                          <p className="mt-1 text-[11px] text-slate-400">{role.tagline}</p>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Role-Specific Ability Choices */}
                {selectedRole === "Tech" && (
                  <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold text-amber-200">Tech Maker Specialties (8 pts total, max 4 each)</span>
                      <span className="font-mono text-xs text-cyan-300">
                        {Object.values(techMakerRanks).reduce((a, b) => a + b, 0)} / 8
                      </span>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      {MAKER_SPECIALTIES.map((spec) => (
                        <div key={spec} className="flex items-center justify-between rounded border border-slate-800 bg-slate-950 px-2.5 py-1.5 text-xs">
                          <span className="text-slate-200">{spec}</span>
                          <div className="flex items-center gap-1.5 font-mono">
                            <button
                              type="button"
                              onClick={() => setTechMakerRanks((p) => ({ ...p, [spec]: Math.max(0, (p[spec] ?? 0) - 1) }))}
                              className="rounded border border-slate-700 px-1.5 hover:border-cyan-400"
                            >-</button>
                            <span>{techMakerRanks[spec] ?? 0}</span>
                            <button
                              type="button"
                              onClick={() => setTechMakerRanks((p) => ({ ...p, [spec]: Math.min(4, (p[spec] ?? 0) + 1) }))}
                              className="rounded border border-slate-700 px-1.5 hover:border-cyan-400"
                            >+</button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {selectedRole === "Medtech" && (
                  <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3 space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold text-emerald-200">Medtech Medicine Allocations (4 pts total)</span>
                      <span className="font-mono text-xs text-cyan-300">
                        {Object.values(medtechAlloc).reduce((a, b) => a + b, 0)} / 4
                      </span>
                    </div>
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                      {(["Surgery", "Pharmaceuticals", "Cryosystem Operation"] as const).map((field) => (
                        <div key={field} className="flex items-center justify-between rounded border border-slate-800 bg-slate-950 px-2.5 py-1.5 text-xs">
                          <span className="truncate text-slate-200">{field}</span>
                          <div className="flex items-center gap-1.5 font-mono">
                            <button
                              type="button"
                              onClick={() => setMedtechAlloc((p) => ({ ...p, [field]: Math.max(0, (p[field] ?? 0) - 1) }))}
                              className="rounded border border-slate-700 px-1.5"
                            >-</button>
                            <span>{medtechAlloc[field] ?? 0}</span>
                            <button
                              type="button"
                              onClick={() => setMedtechAlloc((p) => ({ ...p, [field]: Math.min(4, (p[field] ?? 0) + 1) }))}
                              className="rounded border border-slate-700 px-1.5"
                            >+</button>
                          </div>
                        </div>
                      ))}
                    </div>
                    {(medtechAlloc.Pharmaceuticals ?? 0) > 0 && (
                      <div className="space-y-1 pt-1">
                        <span className="text-[11px] text-slate-300">Starting Pharmaceutical Recipes ({medtechAlloc.Pharmaceuticals}):</span>
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
                              className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                            >
                              {PHARMA_RECIPES.map((r) => (
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
                  <div className="grid grid-cols-1 gap-2 rounded-lg border border-cyan-500/30 bg-cyan-500/5 p-3 sm:grid-cols-2">
                    <div>
                      <label className="mb-1 block text-[11px] font-semibold text-cyan-200">Fixer Street Culture</label>
                      <input
                        type="text"
                        value={fixerCulture}
                        onChange={(e) => setFixerCulture(e.target.value)}
                        className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100"
                      />
                    </div>
                    <div>
                      <label className="mb-1 block text-[11px] font-semibold text-cyan-200">Operator Reach Language</label>
                      <input
                        type="text"
                        value={fixerLanguage}
                        onChange={(e) => setFixerLanguage(e.target.value)}
                        className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100"
                      />
                    </div>
                  </div>
                )}

                {selectedRole === "Nomad" && (
                  <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 space-y-2">
                    <span className="text-xs font-bold text-amber-200">Nomad Moto Picks (4 Starting Vehicles / Upgrades)</span>
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                      {Array.from({ length: 4 }).map((_, idx) => (
                        <select
                          key={idx}
                          value={nomadVehicles[idx] ?? NOMAD_MOTO_PRESETS[0]}
                          onChange={(e) => {
                            const next = [...nomadVehicles];
                            next[idx] = e.target.value;
                            setNomadVehicles(next);
                          }}
                          className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-100"
                        >
                          {NOMAD_MOTO_PRESETS.map((v) => (
                            <option key={v} value={v}>{v}</option>
                          ))}
                        </select>
                      ))}
                    </div>
                  </div>
                )}

                {selectedRole === "Exec" && (
                  <div className="grid grid-cols-1 gap-2 rounded-lg border border-violet-500/30 bg-violet-500/5 p-3 sm:grid-cols-2">
                    <div>
                      <label className="mb-1 block text-[11px] font-semibold text-violet-200">Exec Team Member Name</label>
                      <input
                        type="text"
                        value={execTeamName}
                        onChange={(e) => setExecTeamName(e.target.value)}
                        className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100"
                      />
                    </div>
                    <div>
                      <label className="mb-1 block text-[11px] font-semibold text-violet-200">Team Member Specialty</label>
                      <input
                        type="text"
                        value={execTeamRole}
                        onChange={(e) => setExecTeamRole(e.target.value)}
                        className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100"
                      />
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* STEP 2: STATS & VITALS */}
            {step === "stats" && (
              <div className="space-y-4">
                <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-800 bg-slate-900/60 p-3">
                  <div>
                    <div className="text-xs font-bold text-slate-100">
                      {method === "streetrat" && `${selectedRole} Template Row #${streetratRoll}`}
                      {method === "edgerunner" && `${selectedRole} Per-STAT Template Rolls`}
                      {method === "complete_package" && `Complete Package Point-Buy: ${statSum} / 62 pts`}
                      {method === "freeform" && `Freeform STATs (Total: ${statSum})`}
                    </div>
                    <div className="text-[11px] text-slate-400">
                      Hover or click any STAT below for Corebook rules, formulas, and beginner advice.
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {method === "streetrat" && (
                      <button
                        type="button"
                        onClick={() => setStreetratRoll(d(10))}
                        className="inline-flex items-center gap-1.5 rounded-md bg-cyan-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-cyan-500"
                      >
                        <Dices className="h-3.5 w-3.5" /> Roll 1d10 Template
                      </button>
                    )}
                    {method === "edgerunner" && (
                      <button
                        type="button"
                        onClick={() => setEdgerunnerRolls(Array.from({ length: 10 }, () => d(10)))}
                        className="inline-flex items-center gap-1.5 rounded-md bg-cyan-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-cyan-500"
                      >
                        <Dices className="h-3.5 w-3.5" /> Roll 1d10 × 10 STATs
                      </button>
                    )}
                    {(method === "complete_package" || method === "freeform") && roleInfo && (
                      <button
                        type="button"
                        onClick={() => setCustomStats(buildSmart62Stats(roleInfo.key_stats))}
                        className="inline-flex items-center gap-1.5 rounded-md border border-cyan-500/50 bg-cyan-500/10 px-3 py-1.5 text-xs font-semibold text-cyan-200 hover:bg-cyan-500/20"
                      >
                        <Wand2 className="h-3.5 w-3.5" /> Role Smart Fill (62 pts)
                      </button>
                    )}
                  </div>
                </div>

                {/* 10 STAT Cards */}
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
                  {STAT_NAMES.map((stat, idx) => {
                    const info = statDescriptions?.[stat];
                    const isKey = roleInfo?.key_stats.includes(stat);
                    const val = activeStats[stat];
                    const hoverPayload: InspectorCard = {
                      title: `${stat} — ${info?.name ?? stat} (${val})`,
                      subtitle: isKey ? `Key STAT for ${selectedRole}` : "Core Attribute (2–8 typical)",
                      body: info?.short ?? "",
                      mechanics: info?.mechanics,
                      tip: info?.tip,
                    };
                    return (
                      <div
                        key={stat}
                        onMouseEnter={() => setInspector(hoverPayload)}
                        onClick={() => setInspector(hoverPayload)}
                        className={`rounded-lg border p-2.5 transition ${
                          isKey ? "border-cyan-500/50 bg-cyan-950/20" : "border-slate-800 bg-slate-900/70"
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-mono text-xs font-bold text-slate-200">{stat}</span>
                          <button
                            type="button"
                            aria-label={`${stat} info`}
                            onFocus={() => setInspector(hoverPayload)}
                            className="text-slate-500 hover:text-cyan-300"
                          >
                            <HelpCircle className="h-3.5 w-3.5" />
                          </button>
                        </div>
                        <div className="mt-1 truncate text-[10px] text-slate-400">
                          {info?.name ?? stat}
                        </div>

                        {method === "streetrat" ? (
                          <div className="mt-2 text-center font-mono text-xl font-bold text-cyan-300">{val}</div>
                        ) : method === "edgerunner" ? (
                          <div className="mt-2 flex items-center justify-between gap-1">
                            <span className="font-mono text-lg font-bold text-cyan-300">{val}</span>
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
                              className="rounded border border-slate-700 bg-slate-950 px-1.5 py-0.5 font-mono text-[10px] text-slate-300 hover:border-cyan-400"
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
                                  [stat]: Math.max(method === "complete_package" ? 2 : 1, prev[stat] - 1),
                                }))
                              }
                              className="rounded border border-slate-700 bg-slate-950 px-2 py-0.5 font-mono text-xs hover:border-cyan-400"
                            >-</button>
                            <span className="font-mono text-base font-bold text-slate-100">{val}</span>
                            <button
                              type="button"
                              onClick={() =>
                                setCustomStats((prev) => ({
                                  ...prev,
                                  [stat]: Math.min(method === "complete_package" ? 8 : 10, prev[stat] + 1),
                                }))
                              }
                              className="rounded border border-slate-700 bg-slate-950 px-2 py-0.5 font-mono text-xs hover:border-cyan-400"
                            >+</button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>

                {/* Streetrat Clickable 10-Row Corebook Template Table */}
                {method === "streetrat" && roleInfo && roleInfo.templates.length === 10 && (
                  <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3 space-y-2">
                    <div className="text-xs font-semibold text-slate-300">
                      Corebook {selectedRole} Templates (Click any row 1–10 or Roll 1d10)
                    </div>
                    <div className="overflow-x-auto">
                      <table className="w-full text-center font-mono text-[11px]">
                        <thead>
                          <tr className="border-b border-slate-800 text-slate-400">
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
                                className={`cursor-pointer border-b border-slate-800/50 transition ${
                                  chosen ? "bg-cyan-500/20 text-cyan-200 font-bold" : "text-slate-300 hover:bg-slate-800/60"
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
                <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-800 bg-slate-900/60 p-3">
                  <div>
                    <div className="text-xs font-bold text-slate-100">
                      {method === "streetrat" && `Preset ${selectedRole} Skills (20 Role Skills + Native Language)`}
                      {method === "edgerunner" && `Role Skill Allocation: ${skillPointsSpent} / 86 pts`}
                      {method === "complete_package" && `Full Skill Allocation: ${skillPointsSpent} / 86 pts (x2 costs double)`}
                      {method === "freeform" && `Freeform Skills (${Object.keys(effectiveSkills).length} trained)`}
                    </div>
                    <p className="text-[11px] text-slate-400">
                      Skill Check = STAT + Skill Rank + 1d10. Hover any skill to see what it does &amp; what DVs you beat.
                    </p>
                  </div>

                  <div className="flex items-center gap-2">
                    {method === "complete_package" && roleInfo && (
                      <button
                        type="button"
                        onClick={() => setCustomSkills(defaultCompleteSkills(roleInfo))}
                        className="inline-flex items-center gap-1 rounded border border-cyan-500/40 bg-cyan-500/10 px-2.5 py-1 text-xs text-cyan-200 hover:bg-cyan-500/20"
                      >
                        <Wand2 className="h-3 w-3" /> Role Starter Build (86 pts)
                      </button>
                    )}
                    {method === "edgerunner" && roleInfo && (
                      <button
                        type="button"
                        onClick={() => setEdgerunnerSkills({ ...roleInfo.skills })}
                        className="rounded border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs text-slate-300 hover:border-cyan-400"
                      >
                        Reset to Template
                      </button>
                    )}
                  </div>
                </div>

                {/* Native Cultural Language (+4 FREE!) & Choice Specializations */}
                <div className="grid grid-cols-1 gap-2 rounded-lg border border-cyan-500/30 bg-cyan-950/15 p-3 sm:grid-cols-3">
                  <div>
                    <label className="mb-1 block text-[11px] font-semibold text-cyan-200">
                      Free +4 Cultural Native Language
                    </label>
                    <select
                      value={culturalLanguage}
                      onChange={(e) => setCulturalLanguage(e.target.value)}
                      className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-100"
                    >
                      {Array.from(
                        new Set(
                          (refData?.cultural_regions ?? []).flatMap((r) => r.languages).concat(["English", "Spanish", "Japanese", "Arabic"]),
                        ),
                      ).map((lang) => (
                        <option key={lang} value={lang}>Language ({lang}) +4</option>
                      ))}
                    </select>
                    {culturalLanguageOverlap && (
                      <p className="mt-1 text-[10px] text-amber-300">
                        Overlaps a paid skill above—pick another tongue (e.g. Spanish/Japanese) to avoid a stacking ruling.
                      </p>
                    )}
                  </div>
                  {(["Play Instrument", "Science"] as const).map((specBase) => (
                    <div key={specBase}>
                      <label className="mb-1 block text-[11px] font-semibold text-slate-300">
                        {specBase} Specialization
                      </label>
                      <select
                        value={specializations[specBase] ?? ""}
                        onChange={(e) => setSpecializations((p) => ({ ...p, [specBase]: e.target.value }))}
                        className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-100"
                      >
                        {(SPECIALIZATION_SUGGESTIONS[specBase] ?? []).map((opt) => (
                          <option key={opt} value={opt}>{opt}</option>
                        ))}
                      </select>
                    </div>
                  ))}
                </div>

                {/* Search & Group Filter */}
                <div className="flex flex-wrap items-center gap-2">
                  <div className="relative flex-1 min-w-[180px]">
                    <Search className="pointer-events-none absolute left-2.5 top-2 h-3.5 w-3.5 text-slate-500" />
                    <input
                      type="text"
                      value={skillFilter}
                      onChange={(e) => setSkillFilter(e.target.value)}
                      placeholder="Filter skills (e.g. Handgun, Stealth, REF)…"
                      className="w-full rounded-md border border-slate-700 bg-slate-950 py-1.5 pl-8 pr-3 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                    />
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {["All", "Basic", "Role", "Ranged", "Fighting", "Social", "Awareness", "Technique", "Education"].map((grp) => (
                      <button
                        key={grp}
                        type="button"
                        onClick={() => setSkillGroupFilter(grp)}
                        className={`rounded px-2 py-1 text-[11px] ${
                          skillGroupFilter === grp
                            ? "bg-cyan-500/20 text-cyan-200 border border-cyan-500/50"
                            : "bg-slate-900 text-slate-400 border border-slate-800 hover:text-slate-200"
                        }`}
                      >
                        {grp}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Specialization & Custom Skill Builder (Complete Package & Freeform) */}
                {(method === "complete_package" || method === "freeform") && (
                  <div className="space-y-2 rounded-lg border border-slate-800 bg-slate-900/50 p-2.5">
                    <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-300">
                      Add Skill Specialization (Language, Local Expert, Science, Instrument, Martial Arts)
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <select
                        aria-label="Specialization Category"
                        value={specBasePick}
                        onChange={(e) => setSpecBasePick(e.target.value as typeof specBasePick)}
                        className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-100"
                      >
                        {(["Language", "Local Expert", "Science", "Play Instrument", "Martial Arts"] as const).map((b) => (
                          <option key={b} value={b}>{b}</option>
                        ))}
                      </select>
                      <input
                        type="text"
                        value={specFocusInput}
                        onChange={(e) => setSpecFocusInput(e.target.value)}
                        placeholder={
                          specBasePick === "Martial Arts"
                            ? "e.g. Karate, Judo, Taekwondo…"
                            : specBasePick === "Language"
                              ? "e.g. Japanese, Arabic, Cantonese…"
                              : specBasePick === "Local Expert"
                                ? "e.g. Watson, Heywood, Badlands…"
                                : "Specialization focus…"
                        }
                        className="flex-1 min-w-[160px] rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100"
                      />
                      <button
                        type="button"
                        onClick={() => {
                          const focus = specFocusInput.trim();
                          if (!focus) return;
                          const fullName = `${specBasePick} (${focus})`;
                          setCustomSkills((p) => ({ ...p, [fullName]: p[fullName] ?? 2 }));
                          setSpecFocusInput("");
                        }}
                        className="rounded border border-cyan-500/40 bg-cyan-500/15 px-3 py-1.5 text-xs font-medium text-cyan-200 hover:bg-cyan-500/25"
                      >
                        + Add Specialization
                      </button>
                    </div>
                    {method === "freeform" && (
                      <div className="flex gap-2">
                        <input
                          type="text"
                          value={customNewSkill}
                          onChange={(e) => setCustomNewSkill(e.target.value)}
                          placeholder="Or add any custom skill name…"
                          className="flex-1 rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100"
                        />
                        <button
                          type="button"
                          onClick={() => {
                            const s = customNewSkill.trim();
                            if (!s) return;
                            setCustomSkills((p) => ({ ...p, [s]: p[s] ?? 4 }));
                            setCustomNewSkill("");
                          }}
                          className="rounded bg-slate-800 px-3 py-1.5 text-xs font-medium text-cyan-300 hover:bg-slate-700"
                        >
                          + Add Skill
                        </button>
                      </div>
                    )}
                  </div>
                )}

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
                    const maxRank = method === "freeform" ? 10 : 6;
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
                        className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-800/90 bg-slate-900/50 px-3 py-2 text-xs hover:border-slate-700"
                      >
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className="font-semibold text-slate-100">{storageKey}</span>
                            <span className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[10px] text-slate-300">
                              {sk.stat}
                            </span>
                            {sk.basic && (
                              <span className="rounded bg-cyan-500/15 px-1.5 py-0.5 font-mono text-[10px] text-cyan-300">
                                BASIC
                              </span>
                            )}
                            {sk.cost === 2 && (
                              <span className="rounded bg-amber-500/20 px-1.5 py-0.5 font-mono text-[10px] text-amber-300">
                                x2 pts
                              </span>
                            )}
                          </div>
                          <p className="mt-0.5 truncate text-[11px] text-slate-400">{sk.summary}</p>
                        </div>

                        <div className="flex items-center gap-3 shrink-0">
                          <span className="font-mono text-[11px] text-slate-400">
                            Base <strong className="text-cyan-300">{baseTotal}</strong>
                          </span>
                          {method === "streetrat" ? (
                            <span className="w-8 text-center font-mono text-sm font-bold text-slate-100">+{rank}</span>
                          ) : (
                            <div className="flex items-center gap-1 font-mono">
                              <button
                                type="button"
                                disabled={lockedMedtechSkill || rank <= minRank}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  updateRank(rank - 1);
                                }}
                                className="rounded border border-slate-700 bg-slate-950 px-2 py-0.5 text-slate-200 hover:border-cyan-400 disabled:opacity-30"
                              >-</button>
                              <span className="w-6 text-center font-bold text-slate-100">{rank}</span>
                              <button
                                type="button"
                                disabled={lockedMedtechSkill || rank >= maxRank}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  updateRank(rank + 1);
                                }}
                                className="rounded border border-slate-700 bg-slate-950 px-2 py-0.5 text-slate-200 hover:border-cyan-400 disabled:opacity-30"
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
                <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-rose-500/30 bg-rose-500/10 p-3">
                  <div>
                    <div className="text-xs font-bold text-rose-100">Lifepath, Backstory &amp; Established History</div>
                    <p className="text-[11px] text-rose-200/80">
                      Roll Corebook tables or customize freely—the AI GM reads every ally, grudge, and backstory line from Turn 1.
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    <button
                      type="button"
                      onClick={rollFullLifepath}
                      className="inline-flex items-center gap-1.5 rounded-md bg-rose-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-rose-500"
                    >
                      <Dices className="h-3.5 w-3.5" /> Roll Full Lifepath
                    </button>
                    <button
                      type="button"
                      onClick={() => weaveStarterBackstory()}
                      className="inline-flex items-center gap-1 rounded-md border border-cyan-500/50 bg-cyan-500/15 px-2.5 py-1.5 text-xs font-semibold text-cyan-200 hover:bg-cyan-500/25"
                    >
                      <Wand2 className="h-3.5 w-3.5" /> Weave Starter Bio
                    </button>
                  </div>
                </div>

                {/* A. Written Backstory & Established History */}
                <div className="space-y-3 rounded-lg border border-slate-800 bg-slate-900/50 p-3.5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="text-xs font-bold uppercase tracking-wider text-cyan-300">
                      Written Backstory &amp; Already-Established History
                    </div>
                    <button
                      type="button"
                      disabled={aiBusy}
                      onClick={() => void handleAiAssist("bio", "scratch")}
                      className="inline-flex items-center gap-1 rounded border border-cyan-500/50 bg-cyan-500/15 px-2.5 py-1 text-[11px] font-semibold text-cyan-200 hover:bg-cyan-500/25 disabled:opacity-50"
                    >
                      <Sparkles className="h-3 w-3" />
                      {aiBusyKey === "bio:scratch:all" ? "Generating…" : "Generate from Scratch"}
                    </button>
                  </div>
                  {aiError && (
                    <div className="rounded border border-rose-500/40 bg-rose-500/10 px-2.5 py-1.5 text-[11px] text-rose-200">
                      {aiError}
                    </div>
                  )}
                  <div>
                    <label className="mb-1 block text-[11px] font-medium text-slate-400">
                      Optional Prompt / Direction (stays faithful to your Role, STATs, Skills, Gear &amp; Corebook)
                    </label>
                    <input
                      type="text"
                      value={aiBioGuidance}
                      onChange={(e) => setAiBioGuidance(e.target.value)}
                      placeholder="e.g. Smuggler running spare parts out of Rancho Coronado, owes a local ripperdoc…"
                      className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                    />
                  </div>
                  <div>
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <label className="block text-xs font-medium text-slate-300">
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
                      className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                    />
                  </div>
                  <div>
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <label className="block text-xs font-medium text-slate-300">
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
                      className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                    />
                  </div>
                  <div>
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <label className="block text-xs font-medium text-slate-300">
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
                      className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                    />
                  </div>
                  <div>
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <label className="block text-xs font-medium text-slate-300">
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
                      className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                    />
                  </div>
                </div>

                {/* B. General Lifepath Tables */}
                <div className="space-y-3 rounded-lg border border-slate-800 bg-slate-900/50 p-3.5">
                  <div className="text-xs font-bold uppercase tracking-wider text-slate-300">
                    Corebook Lifepath Tables (Roll d10, Pick, or Type Custom)
                  </div>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <div>
                      <label className="mb-1 flex items-center justify-between text-[11px] text-slate-300">
                        <span>Cultural Region</span>
                        <button
                          type="button"
                          onClick={() => {
                            const reg = pickRandom(refData?.cultural_regions ?? []);
                            if (reg) {
                              setCulturalRegion(reg.region);
                              setCulturalLanguage(pickRandom(reg.languages));
                            }
                          }}
                          className="text-cyan-400 hover:text-cyan-300"
                        >d10 ↻</button>
                      </label>
                      <select
                        value={culturalRegion}
                        onChange={(e) => {
                          setCulturalRegion(e.target.value);
                          const match = refData?.cultural_regions.find((r) => r.region === e.target.value);
                          if (match?.languages.length) setCulturalLanguage(match.languages[0]);
                        }}
                        className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100"
                      >
                        {(refData?.cultural_regions ?? []).map((r) => (
                          <option key={r.region} value={r.region}>{r.region}</option>
                        ))}
                      </select>
                    </div>

                    <div>
                      <label className="mb-1 block text-[11px] text-slate-300">
                        Native Language (+4 Free Skill!)
                      </label>
                      <input
                        type="text"
                        value={culturalLanguage}
                        onChange={(e) => setCulturalLanguage(e.target.value)}
                        list="cultural-lang-options"
                        className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100"
                      />
                      <datalist id="cultural-lang-options">
                        {(refData?.cultural_regions.find((r) => r.region === culturalRegion)?.languages ?? []).map((l) => (
                          <option key={l} value={l} />
                        ))}
                      </datalist>
                      {culturalLanguageOverlap && (
                        <p className="mt-1 text-[10px] text-amber-300">
                          Overlaps paid Language ({culturalLanguage}) in Step 3 — pick another native language for +4 free cleanly.
                        </p>
                      )}
                    </div>

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
                      return (
                        <div key={field.key}>
                          <label className="mb-1 flex items-center justify-between text-[11px] text-slate-300">
                            <span>{field.label}</span>
                            {opts.length > 0 && (
                              <button
                                type="button"
                                onClick={() => field.set(pickRandom(opts))}
                                className="text-cyan-400 hover:text-cyan-300"
                              >
                                d{opts.length} ↻
                              </button>
                            )}
                          </label>
                          <select
                            value={opts.includes(field.val) ? field.val : "__custom__"}
                            onChange={(e) => {
                              if (e.target.value !== "__custom__") field.set(e.target.value);
                            }}
                            className="mb-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                          >
                            {opts.map((o) => (
                              <option key={o} value={o}>{o}</option>
                            ))}
                            {!opts.includes(field.val) && <option value="__custom__">Custom: {field.val}</option>}
                          </select>
                          <input
                            type="text"
                            value={field.val}
                            onChange={(e) => field.set(e.target.value)}
                            className="w-full rounded border border-slate-800 bg-slate-950/70 px-2 py-1 text-[11px] text-slate-300 focus:border-cyan-400 focus:outline-none"
                          />
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* C. Role-Specific Lifepath */}
                {roleInfo && roleInfo.role_lifepath.length > 0 && (
                  <div className="space-y-2.5 rounded-lg border border-slate-800 bg-slate-900/50 p-3.5">
                    <div className="text-xs font-bold uppercase tracking-wider text-amber-300">
                      {selectedRole} Role Lifepath
                    </div>
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                      {roleInfo.role_lifepath.map((f) => (
                        <div key={f.key}>
                          <label className="mb-1 flex items-center justify-between text-[11px] text-slate-300">
                            <span>{f.label}</span>
                            <button
                              type="button"
                              onClick={() => setRoleLifepath((p) => ({ ...p, [f.key]: pickRandom(f.options) }))}
                              className="text-cyan-400 hover:text-cyan-300"
                            >Roll ↻</button>
                          </label>
                          <select
                            value={f.options.includes(roleLifepath[f.key] ?? "") ? roleLifepath[f.key] : "__custom__"}
                            onChange={(e) => {
                              if (e.target.value !== "__custom__") {
                                setRoleLifepath((p) => ({ ...p, [f.key]: e.target.value }));
                              }
                            }}
                            className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-100"
                          >
                            {f.options.map((o) => (
                              <option key={o} value={o}>{o}</option>
                            ))}
                            {roleLifepath[f.key] && !f.options.includes(roleLifepath[f.key]) && (
                              <option value="__custom__">{roleLifepath[f.key]}</option>
                            )}
                          </select>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* D. Established Contacts: Friends, Enemies, Tragic Loves */}
                <div className="space-y-3 rounded-lg border border-slate-800 bg-slate-900/50 p-3.5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="inline-flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-slate-200">
                      <Users className="h-3.5 w-3.5 text-cyan-400" />
                      Friends, Enemies &amp; Past Romances
                    </span>
                    <div className="flex flex-wrap gap-1.5">
                      <button
                        type="button"
                        disabled={aiBusy}
                        onClick={() => void handleAiAssist("contacts", "scratch")}
                        className="inline-flex items-center gap-1 rounded border border-cyan-500/50 bg-cyan-500/15 px-2 py-1 text-[11px] font-semibold text-cyan-200 hover:bg-cyan-500/25 disabled:opacity-50"
                      >
                        <Sparkles className="h-3 w-3" />
                        {aiBusyKey === "contacts:scratch:all" ? "Writing…" : "Generate Contacts"}
                      </button>
                      <button
                        type="button"
                        onClick={() =>
                          setFriends((p) => [
                            ...p,
                            {
                              name: `Ally #${p.length + 1}`,
                              relationship: pickRandom(refData?.lifepath_tables.friend_relationship ?? ["Someone from The Street"]),
                              note: "Has your back when things go sideways.",
                            },
                          ])
                        }
                        className="inline-flex items-center gap-1 rounded border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 text-[11px] text-emerald-200 hover:bg-emerald-500/20"
                      >
                        <Plus className="h-3 w-3" /> Friend
                      </button>
                      <button
                        type="button"
                        onClick={() =>
                          setEnemies((p) => [
                            ...p,
                            {
                              who: pickRandom(refData?.lifepath_tables.enemy_who ?? ["Ex-friend"]),
                              name: `Rival #${p.length + 1}`,
                              wronged: "They wronged me",
                              cause: pickRandom(refData?.lifepath_tables.enemy_cause ?? ["Betrayal"]),
                              backup: pickRandom(refData?.lifepath_tables.enemy_backup ?? ["Just themselves"]),
                              revenge: pickRandom(refData?.lifepath_tables.sweet_revenge ?? ["Avoid the scum."]),
                            },
                          ])
                        }
                        className="inline-flex items-center gap-1 rounded border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-[11px] text-rose-200 hover:bg-rose-500/20"
                      >
                        <Plus className="h-3 w-3" /> Enemy
                      </button>
                      <button
                        type="button"
                        onClick={() =>
                          setLoveAffairs((p) => [
                            ...p,
                            {
                              name: `Ex #${p.length + 1}`,
                              outcome: pickRandom(refData?.lifepath_tables.tragic_love ?? ["It just didn't work out."]),
                            },
                          ])
                        }
                        className="inline-flex items-center gap-1 rounded border border-violet-500/40 bg-violet-500/10 px-2 py-1 text-[11px] text-violet-200 hover:bg-violet-500/20"
                      >
                        <Plus className="h-3 w-3" /> Tragic Love
                      </button>
                    </div>
                  </div>
                  <input
                    type="text"
                    value={aiContactsGuidance}
                    onChange={(e) => setAiContactsGuidance(e.target.value)}
                    placeholder="Optional AI direction for Friends, Enemies & Romances (e.g. a Chromatic Rock fixer friend, Maelstrom rival)…"
                    className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                  />

                  {friends.length === 0 && enemies.length === 0 && loveAffairs.length === 0 && (
                    <p className="text-xs text-slate-500">
                      No friends, enemies, or tragic romances added yet. Add your own NPCs or click Roll Full Lifepath!
                    </p>
                  )}

                  {friends.length > 0 && (
                    <div className="space-y-1.5">
                      <div className="flex items-center justify-between">
                        <span className="text-[11px] font-semibold text-emerald-300">Friends ({friends.length})</span>
                        <FieldAiActions
                          label="Friends"
                          disabled={aiBusy}
                          busyAction={busyFor("contacts", "friends")}
                          onImprove={() => void handleAiAssist("contacts", "expand", "friends")}
                          onRegen={() => void handleAiAssist("contacts", "scratch", "friends")}
                        />
                      </div>
                      {friends.map((fr, idx) => (
                        <div key={idx} className="grid grid-cols-1 gap-2 rounded border border-emerald-500/30 bg-emerald-950/15 p-2.5 sm:grid-cols-12">
                          <input
                            type="text"
                            value={fr.name}
                            onChange={(e) => setFriends((p) => p.map((x, i) => (i === idx ? { ...x, name: e.target.value } : x)))}
                            placeholder="Friend name"
                            className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100 sm:col-span-3"
                          />
                          <input
                            type="text"
                            value={fr.relationship}
                            onChange={(e) => setFriends((p) => p.map((x, i) => (i === idx ? { ...x, relationship: e.target.value } : x)))}
                            placeholder="Relationship"
                            className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100 sm:col-span-4"
                          />
                          <input
                            type="text"
                            value={fr.note}
                            onChange={(e) => setFriends((p) => p.map((x, i) => (i === idx ? { ...x, note: e.target.value } : x)))}
                            placeholder="Shared history / favor"
                            className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100 sm:col-span-4"
                          />
                          <button
                            type="button"
                            onClick={() => setFriends((p) => p.filter((_, i) => i !== idx))}
                            className="justify-self-end text-slate-400 hover:text-rose-400 sm:col-span-1"
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
                        <span className="text-[11px] font-semibold text-rose-300">Enemies ({enemies.length})</span>
                        <FieldAiActions
                          label="Enemies"
                          disabled={aiBusy}
                          busyAction={busyFor("contacts", "enemies")}
                          onImprove={() => void handleAiAssist("contacts", "expand", "enemies")}
                          onRegen={() => void handleAiAssist("contacts", "scratch", "enemies")}
                        />
                      </div>
                      {enemies.map((en, idx) => (
                        <div key={idx} className="space-y-1.5 rounded border border-rose-500/30 bg-rose-950/15 p-2.5 text-xs">
                          <div className="flex flex-wrap items-center gap-2">
                            <input
                              type="text"
                              value={en.name}
                              onChange={(e) => setEnemies((p) => p.map((x, i) => (i === idx ? { ...x, name: e.target.value } : x)))}
                              placeholder="Enemy name"
                              className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                            />
                            <input
                              type="text"
                              value={en.who}
                              onChange={(e) => setEnemies((p) => p.map((x, i) => (i === idx ? { ...x, who: e.target.value } : x)))}
                              placeholder="Who they are"
                              className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                            />
                            <select
                              value={en.wronged}
                              onChange={(e) =>
                                setEnemies((p) =>
                                  p.map((x, i) => (i === idx ? { ...x, wronged: e.target.value as EnemyEntry["wronged"] } : x)),
                                )
                              }
                              className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                            >
                              <option value="They wronged me">They wronged me</option>
                              <option value="I wronged them">I wronged them</option>
                            </select>
                            <button
                              type="button"
                              onClick={() => setEnemies((p) => p.filter((_, i) => i !== idx))}
                              className="ml-auto text-slate-400 hover:text-rose-400"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                          <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-3">
                            <input
                              type="text"
                              value={en.cause}
                              onChange={(e) => setEnemies((p) => p.map((x, i) => (i === idx ? { ...x, cause: e.target.value } : x)))}
                              placeholder="What caused it"
                              className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-[11px] text-slate-200"
                            />
                            <input
                              type="text"
                              value={en.backup}
                              onChange={(e) => setEnemies((p) => p.map((x, i) => (i === idx ? { ...x, backup: e.target.value } : x)))}
                              placeholder="What they can throw at you"
                              className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-[11px] text-slate-200"
                            />
                            <input
                              type="text"
                              value={en.revenge}
                              onChange={(e) => setEnemies((p) => p.map((x, i) => (i === idx ? { ...x, revenge: e.target.value } : x)))}
                              placeholder="Sweet revenge"
                              className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-[11px] text-slate-200"
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {loveAffairs.length > 0 && (
                    <div className="space-y-1.5">
                      <div className="flex items-center justify-between">
                        <span className="text-[11px] font-semibold text-violet-300">Past Romances ({loveAffairs.length})</span>
                        <FieldAiActions
                          label="Romances"
                          disabled={aiBusy}
                          busyAction={busyFor("contacts", "tragic_love_affairs")}
                          onImprove={() => void handleAiAssist("contacts", "expand", "tragic_love_affairs")}
                          onRegen={() => void handleAiAssist("contacts", "scratch", "tragic_love_affairs")}
                        />
                      </div>
                      {loveAffairs.map((lv, idx) => (
                        <div key={idx} className="flex flex-wrap items-center gap-2 rounded border border-violet-500/30 bg-violet-950/15 p-2.5 text-xs">
                          <input
                            type="text"
                            value={lv.name}
                            onChange={(e) => setLoveAffairs((p) => p.map((x, i) => (i === idx ? { ...x, name: e.target.value } : x)))}
                            placeholder="Lover's name"
                            className="w-40 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                          />
                          <input
                            type="text"
                            value={lv.outcome}
                            onChange={(e) => setLoveAffairs((p) => p.map((x, i) => (i === idx ? { ...x, outcome: e.target.value } : x)))}
                            placeholder="What happened?"
                            className="flex-1 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                          />
                          <button
                            type="button"
                            onClick={() => setLoveAffairs((p) => p.filter((_, i) => i !== idx))}
                            className="text-slate-400 hover:text-rose-400"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* STEP 5: GEAR, ARMOR & CYBERWARE */}
            {step === "gear" && (
              <div className="space-y-4">
                {(method === "streetrat" || method === "edgerunner") && roleInfo ? (
                  <div className="space-y-4">
                    <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3 flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <div className="text-xs font-bold text-slate-100">
                          {selectedRole} Starter Package (+500 eb pocket money)
                        </div>
                        <p className="text-[11px] text-slate-400">
                          Corebook gives you preset weapons, SP 11 Light Armorjack, Outfit, and Cyberware—just pick between any A/B options below.
                        </p>
                      </div>
                      <span className="font-mono text-xs text-amber-300">
                        Cyberware HL: -{gearSummary.totalHl} Humanity
                      </span>
                    </div>

                    {/* Weapons & Choices */}
                    <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3 space-y-2">
                      <div className="text-xs font-bold uppercase tracking-wider text-rose-300">
                        Weapons &amp; Armor
                      </div>
                      <div className="space-y-2">
                        {roleInfo.starting_weapons.map((w, idx) =>
                          w.type === "choice" && w.options ? (
                            <div key={idx} className="flex flex-wrap items-center justify-between gap-2 rounded border border-cyan-500/30 bg-cyan-950/15 p-2 text-xs">
                              <span className="font-medium text-cyan-200">{w.label ?? "Weapon Option"}:</span>
                              <div className="flex flex-wrap gap-1.5">
                                {w.options.map((opt) => (
                                  <button
                                    key={opt}
                                    type="button"
                                    onClick={() => setWeaponChoices((p) => ({ ...p, [w.label || `choice-${idx}`]: opt }))}
                                    className={`rounded border px-2.5 py-1 text-xs ${
                                      weaponChoices[w.label || `choice-${idx}`] === opt
                                        ? "border-cyan-400 bg-cyan-500/20 text-cyan-100 font-semibold"
                                        : "border-slate-700 bg-slate-950 text-slate-300"
                                    }`}
                                  >
                                    {opt}
                                  </button>
                                ))}
                              </div>
                            </div>
                          ) : (
                            <div key={idx} className="text-xs text-slate-300">
                              • {w.item} {w.qty ? `×${w.qty}` : ""}
                            </div>
                          ),
                        )}
                        {roleInfo.starting_armor.map((a) => (
                          <div key={a} className="text-xs text-cyan-200">• {a}</div>
                        ))}
                      </div>
                    </div>

                    {/* Cyberware & Choices */}
                    <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3 space-y-2">
                      <div className="text-xs font-bold uppercase tracking-wider text-violet-300">
                        Installed Cyberware (Total Humanity Loss: {gearSummary.totalHl})
                      </div>
                      {roleInfo.starting_cyberware.map((cw) => (
                        <div
                          key={cw.name}
                          onMouseEnter={() =>
                            setInspector({
                              title: cw.name,
                              subtitle: `Install: ${cw.install} · Humanity Loss: ${cw.hl}`,
                              body: cw.notes,
                            })
                          }
                          className="flex items-center justify-between rounded border border-slate-800 bg-slate-950/60 px-2.5 py-1.5 text-xs"
                        >
                          <span className="font-medium text-slate-200">{cw.name}</span>
                          <span className="font-mono text-[11px] text-amber-300">
                            {cw.install} · HL {cw.hl}
                          </span>
                        </div>
                      ))}

                      {[roleInfo.cyberware_choice, roleInfo.cyberware_choice_2].map((choice, cIdx) =>
                        choice ? (
                          <div key={cIdx} className="rounded border border-violet-500/30 bg-violet-950/15 p-2 space-y-1.5">
                            <div className="text-[11px] font-semibold text-violet-200">{choice.label} (Pick 1):</div>
                            <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                              {choice.options.map((opt) => {
                                const cur = cIdx === 0 ? cyberwareChoice : cyberwareChoice2;
                                const active = cur === opt.name;
                                return (
                                  <button
                                    key={opt.name}
                                    type="button"
                                    onMouseEnter={() =>
                                      setInspector({
                                        title: opt.name,
                                        subtitle: `${opt.install} · HL ${opt.hl}`,
                                        body: opt.notes,
                                      })
                                    }
                                    onClick={() => (cIdx === 0 ? setCyberwareChoice(opt.name) : setCyberwareChoice2(opt.name))}
                                    className={`rounded border p-2 text-left text-xs ${
                                      active
                                        ? "border-violet-400 bg-violet-500/20 text-violet-100"
                                        : "border-slate-700 bg-slate-950 text-slate-300"
                                    }`}
                                  >
                                    <div className="font-semibold">{opt.name}</div>
                                    <div className="text-[10px] text-slate-400">{opt.notes}</div>
                                  </button>
                                );
                              })}
                            </div>
                          </div>
                        ) : null,
                      )}
                    </div>

                    {/* Outfit */}
                    <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3 space-y-2">
                      <div className="text-xs font-bold uppercase tracking-wider text-slate-300">Starting Outfit</div>
                      {roleInfo.outfit_choice && (
                        <div className="flex flex-wrap items-center gap-2 text-xs">
                          <span className="text-cyan-200">{roleInfo.outfit_choice.label}:</span>
                          {roleInfo.outfit_choice.options.map((opt) => (
                            <button
                              key={opt}
                              type="button"
                              onClick={() => setOutfitChoice(opt)}
                              className={`rounded border px-2 py-0.5 ${
                                outfitChoice === opt
                                  ? "border-cyan-400 bg-cyan-500/20 text-cyan-100"
                                  : "border-slate-700 bg-slate-950 text-slate-300"
                              }`}
                            >
                              {opt}
                            </button>
                          ))}
                        </div>
                      )}
                      <div className="flex flex-wrap gap-1.5">
                        {roleInfo.starting_outfit.map((o) => (
                          <span key={o} className="rounded border border-slate-800 bg-slate-950 px-2 py-0.5 text-[11px] text-slate-300">
                            {o}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>
                ) : (
                  /* Complete Package & Freeform Night Market Outfitter */
                  <div className="space-y-3">
                    {/* Sticky Outfitter Toolbar (keeps budget, search, sort & filters pinned without jumping) */}
                    <div className="sticky -top-4 sm:-top-5 z-10 -mx-4 sm:-mx-5 border-b border-slate-800 bg-[#0b101b]/95 px-4 sm:px-5 pt-3 pb-2.5 backdrop-blur space-y-2.5">
                      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2">
                        <div className="text-xs">
                          {method === "complete_package" ? (
                            <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
                              <span>
                                Gear: <strong className={`font-mono ${remainingGearEb < 0 ? "text-rose-400" : "text-emerald-300"}`}>{remainingGearEb} / 2,550 eb</strong>
                              </span>
                              <span>
                                Fashion: <strong className={`font-mono ${remainingFashionEb < 0 ? "text-rose-400" : "text-cyan-300"}`}>{remainingFashionEb} / 800 eb</strong>
                              </span>
                              <span>
                                HL: <strong className="font-mono text-amber-300">-{gearSummary.totalHl}</strong>
                              </span>
                            </span>
                          ) : (
                            <label className="inline-flex items-center gap-2">
                              <span>Starting Eurobucks:</span>
                              <input
                                type="number"
                                min={0}
                                value={freeformMoney}
                                onChange={(e) => setFreeformMoney(Math.max(0, parseInt(e.target.value, 10) || 0))}
                                className="w-24 rounded border border-slate-700 bg-slate-950 px-2 py-1 font-mono text-xs text-emerald-300"
                              />
                            </label>
                          )}
                        </div>
                        <div className="flex flex-wrap items-center gap-1.5">
                          <button
                            type="button"
                            onClick={() => setLoadoutOpen((v) => !v)}
                            className={`inline-flex items-center gap-1 rounded border px-2.5 py-1 text-xs font-medium ${
                              cyberwarePrereqWarnings.length > 0 || cyberwareSlotWarnings.length > 0
                                ? "border-amber-500/60 bg-amber-500/15 text-amber-200"
                                : "border-slate-700 bg-slate-950 text-slate-200 hover:border-cyan-400"
                            }`}
                          >
                            <Backpack className="h-3 w-3 text-cyan-400" />
                            Bag ({cartItems.reduce((a, b) => a + b.qty, 0) + selectedFashion.length})
                            {loadoutOpen ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              setCartItems([
                                { name: "Very Heavy Pistol", category: "weapon", cost_eb: 100, qty: 1 },
                                { name: "Light Armorjack", category: "armor", cost_eb: 100, qty: 2 },
                                { name: "Agent", category: "gear", cost_eb: 100, qty: 1 },
                                { name: "Neural Link", category: "cyberware", cost_eb: 500, hl: 7, install: "Clinic", qty: 1 },
                              ]);
                              setSelectedFashion([{ name: "Urban Flash Outfit", cost_eb: 320, style: "Urban Flash" }]);
                            }}
                            className="inline-flex items-center gap-1 rounded border border-cyan-500/40 bg-cyan-500/10 px-2.5 py-1 text-xs text-cyan-200 hover:bg-cyan-500/20"
                          >
                            <Wand2 className="h-3 w-3" /> Starter Loadout
                          </button>
                        </div>
                      </div>

                      {/* Collapsible Loadout Bag & Cyberware Warnings */}
                      {loadoutOpen && (
                        <div className="max-h-44 overflow-y-auto space-y-2 rounded-lg border border-slate-800 bg-slate-950/90 p-2.5 text-xs">
                          {cartItems.length === 0 && selectedFashion.length === 0 ? (
                            <p className="text-[11px] text-slate-400">Your bag is empty. Add weapons, armor, cyberware, or fashion below.</p>
                          ) : (
                            <div className="flex flex-wrap gap-1.5">
                              {cartItems.map((it) => (
                                <span key={`${it.category}-${it.name}`} className="inline-flex items-center gap-1.5 rounded border border-slate-700 bg-slate-900 px-2 py-0.5 text-xs">
                                  <span>{it.name} {it.qty > 1 ? `×${it.qty}` : ""}</span>
                                  <span className="font-mono text-[10px] text-emerald-300">{it.cost_eb * it.qty}eb</span>
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
                                    className="text-slate-400 hover:text-rose-400"
                                  >×</button>
                                </span>
                              ))}
                              {selectedFashion.map((f, idx) => (
                                <span key={idx} className="inline-flex items-center gap-1.5 rounded border border-cyan-500/30 bg-cyan-950/20 px-2 py-0.5 text-xs">
                                  <span>{f.name}</span>
                                  <span className="font-mono text-[10px] text-cyan-300">{f.cost_eb}eb</span>
                                  <button
                                    type="button"
                                    aria-label={`Remove ${f.name}`}
                                    onClick={() => setSelectedFashion((p) => p.filter((_, i) => i !== idx))}
                                    className="text-slate-400 hover:text-rose-400"
                                  >×</button>
                                </span>
                              ))}
                            </div>
                          )}

                          {cyberwarePrereqWarnings.length > 0 && (
                            <div className="space-y-1 rounded border border-amber-500/40 bg-amber-500/10 p-2">
                              <div className="font-semibold text-amber-200">Cyberware Foundation Needed (p. 358):</div>
                              {cyberwarePrereqWarnings.map((w) => (
                                <div key={w.foundation} className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-amber-100/90">
                                  <span>
                                    <strong>{w.option}</strong> requires <strong>{w.foundation}</strong>.
                                  </span>
                                  <button
                                    type="button"
                                    onClick={() =>
                                      setCartItems((p) => [
                                        ...p,
                                        { name: w.foundation, category: "cyberware", cost_eb: w.cost_eb, hl: w.hl, install: "Clinic", qty: 1 },
                                      ])
                                    }
                                    className="rounded border border-amber-400/50 bg-amber-500/20 px-2 py-0.5 font-mono text-[10px] text-amber-100 hover:bg-amber-500/30"
                                  >
                                    + Add {w.foundation} ({w.cost_eb}eb)
                                  </button>
                                </div>
                              ))}
                            </div>
                          )}

                          {cyberwareSlotWarnings.length > 0 && (
                            <div className="space-y-1 rounded border border-amber-500/40 bg-amber-500/10 p-2">
                              <div className="font-semibold text-amber-200">Cyberware Slot Cap Exceeded:</div>
                              {cyberwareSlotWarnings.map((w) => (
                                <div key={w.foundation} className="text-[11px] text-amber-100/90">
                                  <strong>{w.foundation}</strong>: {w.usedSlots}/{w.maxSlots} slots ({w.options.join(", ")}).
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}

                      {/* Category Tabs */}
                      <div className="flex flex-wrap items-center gap-1">
                        {(["weapon", "armor", "cyberware", "gear", "program", "hardware", "vehicle", "drug", "fashion"] as const).map((cat) => (
                          <button
                            key={cat}
                            type="button"
                            aria-label={cat}
                            onClick={() => setShopCategory(cat)}
                            className={`rounded px-2.5 py-1 text-xs capitalize transition ${
                              shopCategory === cat
                                ? "border border-cyan-500/60 bg-cyan-500/15 font-semibold text-cyan-200"
                                : "border border-slate-800 bg-slate-900 text-slate-400 hover:text-slate-200"
                            }`}
                          >
                            {cat === "vehicle" ? "Vehicles" : cat === "drug" ? "Drugs & Pharma" : cat}
                          </button>
                        ))}
                      </div>

                      {/* Search, Sort & Affordable Controls */}
                      <div className="flex flex-wrap items-center gap-2">
                        <div className="relative flex-1 min-w-[160px]">
                          <Search className="pointer-events-none absolute left-2.5 top-2 h-3.5 w-3.5 text-slate-500" />
                          <input
                            type="text"
                            value={shopSearch}
                            onChange={(e) => setShopSearch(e.target.value)}
                            placeholder={`Search ${shopCategory === "fashion" ? "fashion" : shopCategory}…`}
                            className="w-full rounded border border-slate-700 bg-slate-950 py-1 pl-8 pr-7 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                          />
                          {shopSearch && (
                            <button
                              type="button"
                              aria-label="Clear catalog search"
                              onClick={() => setShopSearch("")}
                              className="absolute right-2 top-1.5 text-slate-500 hover:text-slate-200"
                            >
                              <X className="h-3.5 w-3.5" />
                            </button>
                          )}
                        </div>

                        <div className="inline-flex items-center gap-1 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs">
                          <ArrowUpDown className="h-3 w-3 text-slate-400" />
                          <select
                            aria-label="Sort catalog"
                            value={shopSort}
                            onChange={(e) => setShopSort(e.target.value as typeof shopSort)}
                            className="bg-transparent text-xs text-slate-200 focus:outline-none"
                          >
                            <option value="cost_asc" className="bg-slate-950">Price: Low → High</option>
                            <option value="cost_desc" className="bg-slate-950">Price: High → Low</option>
                            <option value="name_asc" className="bg-slate-950">Name: A → Z</option>
                            {shopCategory === "armor" && <option value="sp_desc" className="bg-slate-950">Armor SP: High → Low</option>}
                            {shopCategory === "cyberware" && <option value="hl_asc" className="bg-slate-950">Humanity Loss: Low → High</option>}
                          </select>
                        </div>

                        {method === "complete_package" && (
                          <button
                            type="button"
                            onClick={() => setAffordableOnly((v) => !v)}
                            className={`rounded border px-2 py-1 text-[11px] font-medium transition ${
                              affordableOnly
                                ? "border-emerald-500/60 bg-emerald-500/15 text-emerald-200"
                                : "border-slate-700 bg-slate-900 text-slate-400 hover:text-slate-200"
                            }`}
                          >
                            Affordable Only
                          </button>
                        )}
                      </div>

                      {/* Sub-filters */}
                      {shopCategory === "weapon" && (
                        <div className="flex flex-wrap gap-1">
                          {(
                            [
                              ["all", "All Weapons"],
                              ["pistols", "Pistols & SMGs"],
                              ["rifles", "Rifles & Shotguns"],
                              ["melee", "Melee"],
                              ["exotic", "Exotic & Heavy"],
                              ["excellent", "Excellent (+1 Hit)"],
                              ["standard", "Standard"],
                              ["poor", "Poor"],
                              ["attachment", "Attachments"],
                              ["ammo", "Ammo"],
                            ] as const
                          ).map(([id, label]) => (
                            <button
                              key={id}
                              type="button"
                              onClick={() => setWeaponSubFilter(id)}
                              className={`rounded px-2 py-0.5 text-[11px] ${
                                weaponSubFilter === id
                                  ? "border border-rose-500/50 bg-rose-500/15 text-rose-200"
                                  : "border border-slate-800 bg-slate-900 text-slate-400 hover:text-slate-200"
                              }`}
                            >
                              {label}
                            </button>
                          ))}
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
                              className={`rounded px-2 py-0.5 text-[11px] ${
                                armorSubFilter === id
                                  ? "border border-cyan-500/50 bg-cyan-500/15 text-cyan-200"
                                  : "border border-slate-800 bg-slate-900 text-slate-400 hover:text-slate-200"
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
                              className={`rounded px-2 py-0.5 text-[11px] ${
                                cyberwareSubFilter === id
                                  ? "border border-violet-500/50 bg-violet-500/15 text-violet-200"
                                  : "border border-slate-800 bg-slate-900 text-slate-400 hover:text-slate-200"
                              }`}
                            >
                              {label}
                            </button>
                          ))}
                        </div>
                      )}

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
                              className={`rounded px-2 py-0.5 text-[11px] ${
                                programSubFilter === id
                                  ? "border border-cyan-500/50 bg-cyan-500/15 text-cyan-200"
                                  : "border border-slate-800 bg-slate-900 text-slate-400 hover:text-slate-200"
                              }`}
                            >
                              {label}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>

                    {/* Catalog Items (single smooth scroll flow, no nested scrollboxes or hover-thrash) */}
                    <div className="space-y-1.5 pt-1">
                      {shopCategory === "fashion" ? (
                        fashionItemsForDisplay.length === 0 ? (
                          <p className="py-6 text-center text-xs text-slate-500">No fashion items match your filter.</p>
                        ) : (
                          fashionItemsForDisplay.map((f) => {
                            const qty = selectedFashion.filter((x) => x.name === f.name).length;
                            const overBudget = method === "complete_package" && f.cost_eb > remainingFashionEb;
                            return (
                              <div
                                key={f.name}
                                className="flex items-center justify-between gap-3 rounded-lg border border-slate-800 bg-slate-900/50 px-3 py-2 text-xs hover:border-slate-700"
                              >
                                <div className="min-w-0 flex-1">
                                  <div className="flex flex-wrap items-center gap-1.5">
                                    <span className="font-semibold text-slate-100">{f.name}</span>
                                    <span className="rounded bg-cyan-500/15 px-1.5 py-0.5 font-mono text-[10px] text-cyan-300">
                                      {f.style}
                                    </span>
                                  </div>
                                  <p className="mt-0.5 text-[11px] text-slate-400">{f.summary}</p>
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
                                      className="rounded border border-slate-700 bg-slate-950 px-1.5 py-1 text-slate-300 hover:border-rose-400"
                                    >
                                      <Minus className="h-3 w-3" />
                                    </button>
                                  )}
                                  <button
                                    type="button"
                                    onClick={() => setSelectedFashion((p) => [...p, { name: f.name, cost_eb: f.cost_eb, style: f.style }])}
                                    className={`rounded border px-2.5 py-1 font-mono text-[11px] ${
                                      overBudget
                                        ? "border-slate-700 bg-slate-950 text-slate-400 hover:border-amber-500/50"
                                        : "border-cyan-500/40 bg-cyan-500/10 text-cyan-200 hover:bg-cyan-500/20"
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
                        <p className="py-6 text-center text-xs text-slate-500">
                          No {shopCategory} items match your current filter or search.
                        </p>
                      ) : (
                        shopItemsForCategory.map((item) => {
                          const hlVal = parseHlVal(item.stats);
                          const spVal = parseSpVal(item.stats);
                          const locVal = typeof item.stats.location === "string" ? item.stats.location : undefined;
                          const installVal = typeof item.stats.install === "string" ? item.stats.install : undefined;
                          const qualityVal = typeof item.stats.quality === "string" ? item.stats.quality : undefined;
                          const subtypeVal = typeof item.stats.subtype === "string" ? item.stats.subtype : undefined;
                          const dmgVal = typeof item.stats.damage === "string" ? item.stats.damage : undefined;
                          const inCart = cartItems.find((x) => x.name === item.name && x.category === item.category);
                          const overBudget = method === "complete_package" && item.cost_eb > remainingGearEb;
                          const inspectPayload: InspectorCard = {
                            title: `${item.name} (${item.cost_eb} eb)`,
                            subtitle: `${item.category.toUpperCase()}${subtypeVal ? ` · ${subtypeVal.toUpperCase()}` : ""}${qualityVal ? ` · ${qualityVal}` : ""}${item.printed_page ? ` · Corebook p.${item.printed_page}` : ""}${hlVal ? ` · HL ${hlVal}` : ""}${spVal ? ` · SP ${spVal}` : ""}`,
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
                              className={`flex items-center justify-between gap-3 rounded-lg border px-3 py-2 text-xs transition ${
                                inspectedItemId === item.id
                                  ? "border-cyan-500/60 bg-cyan-950/20"
                                  : inCart
                                    ? "border-emerald-500/40 bg-emerald-950/10"
                                    : "border-slate-800 bg-slate-900/50 hover:border-slate-600"
                              }`}
                            >
                              <div className="min-w-0 flex-1">
                                <div className="flex flex-wrap items-center gap-1.5">
                                  <span className="font-semibold text-slate-100">{item.name}</span>
                                  {dmgVal && (
                                    <span className="rounded bg-rose-500/15 px-1.5 py-0.5 font-mono text-[10px] text-rose-200">
                                      {dmgVal}
                                    </span>
                                  )}
                                  {subtypeVal?.toLowerCase().includes("exotic") && (
                                    <span className="rounded bg-rose-500/20 px-1 py-0.5 font-mono text-[9px] text-rose-300">
                                      EXOTIC
                                    </span>
                                  )}
                                  {qualityVal?.toLowerCase().includes("excellent") && (
                                    <span className="rounded bg-emerald-500/20 px-1 py-0.5 font-mono text-[9px] text-emerald-300">
                                      +1 HIT
                                    </span>
                                  )}
                                  {spVal > 0 && (
                                    <span className="rounded bg-cyan-500/20 px-1.5 py-0.5 font-mono text-[10px] text-cyan-300">
                                      SP {spVal}{locVal ? ` · ${locVal}` : ""}
                                    </span>
                                  )}
                                  {hlVal > 0 && (
                                    <span className="rounded bg-violet-500/20 px-1.5 py-0.5 font-mono text-[10px] text-violet-200">
                                      HL {hlVal}{installVal ? ` · ${installVal}` : ""}
                                    </span>
                                  )}
                                  {item.printed_page && (
                                    <span className="font-mono text-[10px] text-slate-500">p.{item.printed_page}</span>
                                  )}
                                </div>
                                <p className="mt-0.5 text-[11px] leading-snug text-slate-400">{item.summary}</p>
                              </div>

                              <div className="flex shrink-0 items-center gap-1.5">
                                {inCart ? (
                                  <div className="inline-flex items-center gap-1 rounded border border-emerald-500/40 bg-emerald-950/30 px-1.5 py-0.5 font-mono text-[11px]">
                                    <button
                                      type="button"
                                      aria-label={`Decrease ${item.name}`}
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        setCartItems((p) =>
                                          p.flatMap((x) =>
                                            x.name === item.name && x.category === item.category
                                              ? x.qty > 1
                                                ? [{ ...x, qty: x.qty - 1 }]
                                                : []
                                              : [x],
                                          ),
                                        );
                                      }}
                                      className="rounded p-0.5 text-slate-300 hover:text-rose-300"
                                    >
                                      <Minus className="h-3 w-3" />
                                    </button>
                                    <span className="min-w-[1.2rem] text-center font-bold text-emerald-200">{inCart.qty}</span>
                                    <button
                                      type="button"
                                      aria-label={`Increase ${item.name}`}
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        setCartItems((p) =>
                                          p.map((x) =>
                                            x.name === item.name && x.category === item.category ? { ...x, qty: x.qty + 1 } : x,
                                          ),
                                        );
                                      }}
                                      className="rounded p-0.5 text-emerald-200 hover:text-white"
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
                                          name: item.name,
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
                                    className={`rounded border px-2.5 py-1 font-mono text-[11px] ${
                                      overBudget
                                        ? "border-slate-700 bg-slate-950 text-slate-400 hover:border-amber-500/50"
                                        : "border-emerald-500/40 bg-emerald-500/10 text-emerald-200 hover:bg-emerald-500/20"
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
                  <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 space-y-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="inline-flex items-center gap-1.5 text-xs font-bold text-amber-200">
                        <AlertTriangle className="h-4 w-4" /> Check Before Launching
                      </span>
                      {method !== "freeform" && (
                        <button
                          type="button"
                          onClick={() => setMethod("freeform")}
                          className="rounded border border-amber-400/50 bg-amber-500/20 px-2 py-0.5 text-[11px] text-amber-100 hover:bg-amber-500/30"
                        >
                          Switch to Freeform Instead
                        </button>
                      )}
                    </div>
                    <ul className="list-disc pl-5 text-xs text-amber-100/90 space-y-0.5">
                      {validationIssues.map((msg) => (
                        <li key={msg}>{msg}</li>
                      ))}
                    </ul>
                  </div>
                )}

                <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4 space-y-4">
                  <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-3">
                    <div>
                      <h3 className="text-base font-bold text-slate-100">
                        {name.trim() || "Unnamed Edgerunner"}
                      </h3>
                      <p className="text-xs text-cyan-300">
                        {selectedRole} (Rank 4 · {roleInfo?.ability}) · {culturalRegion} ({culturalLanguage})
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-3 font-mono text-xs">
                      <span className="text-rose-300">HP {maxHp}</span>
                      <span className="text-cyan-300">HUM {startingHumanity}/{maxHumanity}</span>
                      <span className="text-emerald-300">{gearSummary.money} eb</span>
                    </div>
                  </div>

                  {/* STAT Grid */}
                  <div className="grid grid-cols-5 gap-1.5 font-mono text-center text-xs sm:grid-cols-10">
                    {STAT_NAMES.map((s) => (
                      <div key={s} className="rounded border border-slate-800 bg-slate-950 p-1.5">
                        <div className="text-[10px] text-slate-400">{s}</div>
                        <div className="font-bold text-slate-100">{activeStats[s]}</div>
                      </div>
                    ))}
                  </div>

                  {/* Backstory & Established Ties */}
                  <div className="space-y-1.5 text-xs">
                    <div className="font-bold uppercase tracking-wider text-slate-400">Backstory &amp; History</div>
                    <p className="text-slate-200">
                      {backstorySummary.trim() || `${personality}; ${familyBackground.split("(", 1)[0].trim()} upbringing. Goal: ${lifeGoal}`}
                    </p>
                    {establishedHistory.trim() && (
                      <p className="text-slate-300"><strong>Established Ties:</strong> {establishedHistory}</p>
                    )}
                    {(friends.length > 0 || enemies.length > 0) && (
                      <p className="text-slate-400">
                        Connections: {friends.length} friend{friends.length === 1 ? "" : "s"}, {enemies.length} enem{enemies.length === 1 ? "y" : "ies"}, {loveAffairs.length} past romance{loveAffairs.length === 1 ? "" : "s"}.
                      </p>
                    )}
                  </div>

                  {/* Trained Skills Summary */}
                  <div className="space-y-1.5">
                    <div className="text-xs font-bold uppercase tracking-wider text-slate-400">
                      Skills ({Object.keys(effectiveSkills).length})
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {Object.entries(effectiveSkills)
                        .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
                        .map(([skName, lvl]) => (
                          <span key={skName} className="rounded border border-slate-800 bg-slate-950 px-2 py-0.5 text-[11px] text-slate-200">
                            {skName} <strong className="font-mono text-cyan-300">+{lvl}</strong>
                          </span>
                        ))}
                    </div>
                  </div>

                  {/* Gear & Cyberware Summary */}
                  <div className="space-y-1.5">
                    <div className="text-xs font-bold uppercase tracking-wider text-slate-400">
                      Starting Loadout &amp; Cyberware ({Object.keys(gearSummary.inventory).length} items, {gearSummary.cyberware.length} cyberware)
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {gearSummary.cyberware.map((cw, i) => (
                        <span key={i} className="rounded border border-violet-500/40 bg-violet-500/10 px-2 py-0.5 text-[11px] text-violet-200">
                          {cw.name} {cw.hl ? `(-${cw.hl} HL)` : ""}
                        </span>
                      ))}
                      {Object.entries(gearSummary.inventory).map(([itemName, qty]) => (
                        <span key={itemName} className="rounded border border-slate-800 bg-slate-950 px-2 py-0.5 text-[11px] text-slate-300">
                          {itemName}{qty > 1 ? ` ×${qty}` : ""}
                        </span>
                      ))}
                    </div>
                    {cyberwarePrereqWarnings.length > 0 && (
                      <p className="text-[11px] text-amber-300">
                        Cyberware Note: {cyberwarePrereqWarnings.map((w) => `${w.option} needs ${w.foundation}`).join("; ")}.
                      </p>
                    )}
                    {cyberwareSlotWarnings.length > 0 && (
                      <p className="text-[11px] text-amber-300">
                        Cyberware Slot Cap Warning: {cyberwareSlotWarnings.map((w) => `${w.foundation} exceeds slot cap (${w.usedSlots}/${w.maxSlots} slots)`).join("; ")}.
                      </p>
                    )}
                    <div className="rounded border border-slate-800 bg-slate-950/70 px-2.5 py-1.5 text-[11px] text-slate-400">
                      <strong className="text-slate-300">Starting Housing &amp; Lifestyle (pp. 377–378):</strong>{" "}
                      Cargo Container + Kibble Lifestyle (Month 1 Rent Paid; 1,000 eb + 100 eb/mo starting Month 2 unless upgraded).
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Right 4 cols: Sticky Live Sheet Preview + Hover Rulebook Inspector */}
          <aside className="hidden min-h-0 lg:flex lg:col-span-4 flex-col overflow-hidden border-l border-slate-800 bg-[#0d1322] p-4 space-y-4">
            {/* Live Vitals Card */}
            <div className="shrink-0 space-y-3 rounded-lg border border-slate-800 bg-[#11192c] p-3.5">
              <div className="flex items-center justify-between">
                <span className="truncate text-sm font-bold text-slate-100">
                  {name.trim() || "New Edgerunner"}
                </span>
                <span className="rounded border border-cyan-500/30 bg-cyan-500/10 px-1.5 py-0.5 font-mono text-[10px] text-cyan-300">
                  {selectedRole} R4
                </span>
              </div>

              <div className="grid grid-cols-2 gap-2 font-mono text-xs">
                <div className="rounded border border-slate-800 bg-slate-950/70 p-2">
                  <div className="flex items-center gap-1 text-[10px] text-slate-400">
                    <Heart className="h-3 w-3 text-rose-400" /> HP / Wound
                  </div>
                  <div className="mt-0.5 font-bold text-slate-100">{maxHp} HP <span className="text-[10px] text-slate-400" title={`Seriously Wounded: < ${woundThreshold} HP`}>(SW &lt;{woundThreshold})</span></div>
                </div>
                <div className="rounded border border-slate-800 bg-slate-950/70 p-2">
                  <div className="flex items-center gap-1 text-[10px] text-slate-400">
                    <Cpu className="h-3 w-3 text-cyan-400" /> Humanity
                  </div>
                  <div className="mt-0.5 font-bold text-cyan-300">
                    {startingHumanity}/{maxHumanity} <span className="text-[10px] text-slate-400">(EMP {effectiveEmp})</span>
                  </div>
                </div>
                <div className="rounded border border-slate-800 bg-slate-950/70 p-2">
                  <div className="flex items-center gap-1 text-[10px] text-slate-400">
                    <Shield className="h-3 w-3 text-amber-400" /> Death / Dodge
                  </div>
                  <div className="mt-0.5 font-bold text-slate-100">
                    Death Save: {activeStats.BODY} · {activeStats.REF >= 8 ? "Bullet Dodge" : "Melee Dodge"}
                  </div>
                </div>
                <div className="rounded border border-slate-800 bg-slate-950/70 p-2">
                  <div className="flex items-center gap-1 text-[10px] text-slate-400">
                    <Backpack className="h-3 w-3 text-emerald-400" /> Eddies / Gear
                  </div>
                  <div className="mt-0.5 font-bold text-emerald-300">
                    {gearSummary.money} eb · {Object.keys(gearSummary.inventory).length} items
                  </div>
                </div>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-1 border-t border-slate-800/80 pt-2 font-mono text-[10px] text-slate-400">
                <span>Seriously Wounded: &lt; {woundThreshold} HP</span>
                <span>Death Save: {activeStats.BODY}</span>
              </div>

              <div className="grid grid-cols-5 gap-1 font-mono text-center text-[11px]">
                {STAT_NAMES.map((s) => (
                  <div key={s} className="rounded border border-slate-800/80 bg-slate-950 py-1">
                    <div className="text-[9px] text-slate-500">{s}</div>
                    <div className="font-bold text-slate-200">{activeStats[s]}</div>
                  </div>
                ))}
              </div>
            </div>

            {/* Contextual Hover / Click Inspector */}
            <div className="min-h-0 flex-1 overflow-y-auto rounded-lg border border-cyan-500/30 bg-cyan-950/15 p-3.5 space-y-2">
              <div className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-cyan-300">
                <BookOpen className="h-3.5 w-3.5" />
                Live Rulebook Inspector
              </div>
              <div>
                <h4 className="text-sm font-bold text-slate-100">{inspector.title}</h4>
                {inspector.subtitle && (
                  <div className="font-mono text-[10px] text-cyan-300/90">{inspector.subtitle}</div>
                )}
              </div>
              <p className="text-xs leading-relaxed text-slate-200">{inspector.body}</p>
              {inspector.mechanics && (
                <div className="rounded border border-slate-800 bg-slate-950/60 p-2 text-[11px] leading-relaxed text-slate-300">
                  <strong className="text-cyan-300">Mechanics: </strong>
                  {inspector.mechanics}
                </div>
              )}
              {inspector.tip && (
                <div className="rounded border border-amber-500/30 bg-amber-500/10 p-2 text-[11px] leading-relaxed text-amber-200">
                  <Sparkles className="mr-1 inline h-3 w-3" />
                  <strong>Beginner Tip: </strong>
                  {inspector.tip}
                </div>
              )}
            </div>
          </aside>
        </div>

        {/* Bottom Footer Controls */}
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-800 bg-[#0f1625] px-4 py-3">
          <button
            type="button"
            disabled={currentStepIdx === 0}
            onClick={() => setStep(STEPS[Math.max(0, currentStepIdx - 1)].id)}
            className="inline-flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-slate-200 hover:border-slate-500 disabled:opacity-40"
          >
            <ChevronLeft className="h-3.5 w-3.5" /> Previous
          </button>

          <div className="flex items-center gap-2">
            {step !== "review" ? (
              <button
                type="button"
                onClick={() => setStep(STEPS[Math.min(STEPS.length - 1, currentStepIdx + 1)].id)}
                className="inline-flex items-center gap-1 rounded-lg bg-cyan-600 px-4 py-1.5 text-xs font-semibold text-white hover:bg-cyan-500"
              >
                Next: {STEPS[Math.min(STEPS.length - 1, currentStepIdx + 1)].short}
                <ChevronRight className="h-3.5 w-3.5" />
              </button>
            ) : null}

            <button
              type="button"
              disabled={busy || validationIssues.length > 0}
              onClick={handleSubmit}
              className="inline-flex items-center gap-1.5 rounded-lg bg-rose-600 px-4 py-1.5 text-xs font-semibold text-white hover:bg-rose-500 disabled:opacity-40"
            >
              <Check className="h-3.5 w-3.5" />
              {busy ? "Creating…" : "Create & Attach to Campaign"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );

  return typeof document !== "undefined" ? createPortal(modalNode, document.body) : modalNode;
}
