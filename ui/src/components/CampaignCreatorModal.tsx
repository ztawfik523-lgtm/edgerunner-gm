import { useEffect, useRef, useState } from "react";
import {
  Clock,
  Compass,
  Dices,
  Eye,
  EyeOff,
  Lock,
  MapPin,
  Plus,
  RotateCcw,
  ShieldAlert,
  Sparkles,
  Target,
  Trash2,
  Unlock,
  Users,
  X,
} from "lucide-react";
import nightMarketHero from "../assets/night-market-hero.jpg";
import {
  assistCharacterCreation,
  bootstrapCampaign,
  createCampaign,
  fetchCampaignContext,
  fetchCreationReference,
  listCampaigns,
  listCharacters,
  type CampaignBootstrapPayload,
} from "../api";
import { clearDraft, loadDraft, saveDraft } from "../draftStorage";
import type { CampaignPresets, CampaignRecord, CharacterRecord } from "../types";
import { FieldAiActions } from "./FieldAiActions";

interface CampaignCreatorModalProps {
  open: boolean;
  editCampaign?: CampaignRecord | null;
  onClose: () => void;
  onCreated: (campaignId: string, name: string, options?: { launchIntro?: boolean }) => Promise<void>;
  onUpdated?: (campaignId: string, name: string) => Promise<void>;
  onNotify: (msg: string) => void;
}

const FALLBACK_PRESETS: CampaignPresets = {
  districts: [
    {
      name: "The Hot Zone",
      zone_type: "Hot Zone",
      threat_rating: "Combat",
      printed_page: 298,
      summary: "Irradiated nuclear ground zero in central Night City, filled with twisted skyscrapers, radioactive ruins, and deadly scavvers.",
    },
    {
      name: "Rebuilding Urban Center (Upper Marina & Little Europe)",
      zone_type: "Rebuilding Urban Center",
      threat_rating: "Corporate",
      printed_page: 298,
      summary: "Densely packed city sectors escaping the worst destruction where new Corporate towers, marinas, and megabuildings rise.",
    },
    {
      name: "Watson Development",
      zone_type: "Rebuilding Urban Center",
      threat_rating: "Moderate",
      printed_page: 298,
      summary: "Sprawling high-density reconstruction sector housing thousands of war refugees in rising megabuildings and Kabuki.",
    },
    {
      name: "Old Combat Zone",
      zone_type: "Combat Zones",
      threat_rating: "Combat",
      printed_page: 300,
      summary: "Lawless urban warzone south of the Hot Zone ruled by violent boostergangs where NCPD never patrols.",
    },
    {
      name: "Heywood",
      zone_type: "Moderate Zone",
      threat_rating: "Moderate",
      printed_page: 301,
      summary: "Sprawling working-class residential sprawl south of Downtown, packed with cargo container blocks and street markets.",
    },
    {
      name: "New Westbrook",
      zone_type: "Moderate Zone",
      threat_rating: "Moderate",
      printed_page: 302,
      summary: "Entertainment and residential sector encompassing Japantown nightlife, capsule hotels, and luxury executive hill estates.",
    },
    {
      name: "Pacifica Playground",
      zone_type: "Combat Zones",
      threat_rating: "Combat",
      printed_page: 299,
      summary: "Bankrupt half-finished vacation paradise turned combat playground for combat gangers, private mercs, and scavvers.",
    },
    {
      name: "Executive Zone (Beaverville)",
      zone_type: "Executive Zone",
      threat_rating: "Executive",
      printed_page: 295,
      summary: "Walled, gated suburban enclave reserved exclusively for corporate executives, guarded by private military forces.",
    },
    {
      name: "The Open Road / Badlands",
      zone_type: "The Open Road",
      threat_rating: "Outskirts",
      printed_page: 295,
      summary: "Vast red-dust desert highways and ruins outside Night City traveled by Nomad convoys and hunted by gogangs.",
    },
  ],
  factions: [
    { name: "Arasaka", type: "Megacorporation", printed_page: 267, summary: "Weakened security & banking titan exiled from the US, operating covertly through cutouts." },
    { name: "Militech", type: "Megacorporation", printed_page: 272, summary: "Colossal arms manufacturer and private military contractor commanding NorCal Military Base." },
    { name: "Danger Gal", type: "Private Security", printed_page: 270, summary: "Elite private investigation & bodyguarding agency masking lethal ops under cute J-pop aesthetics." },
    { name: "Trauma Team International", type: "Emergency Corp", printed_page: 279, summary: "Rapid-response armored AV-4 air ambulance squads extracting paid subscribers under live fire." },
    { name: "Biotechnica", type: "Megacorporation", printed_page: 268, summary: "Biotechnology pioneer holding global patents on CHOOH2 fuel and cloned replacement species." },
    { name: "Continental Brands", type: "Megacorporation", printed_page: 269, summary: "Food and drink giant manufacturing bulk Kibble and operating citywide Oasis Megamarts." },
    { name: "NetWatch", type: "Cyberspace Police", printed_page: 301, summary: "Cyberspace law enforcement agency guarding local CitiNets and quarantining deadly Black ICE." },
    { name: "Maelstrom", type: "Combat Gang", printed_page: 308, summary: "Extreme cyber-modified boostergang obsessed with eradicating human flesh and hunting Inquisitors." },
    { name: "Tyger Claws", type: "Combat Gang", printed_page: 309, summary: "Deadly motorcycle combat gang protecting Asian communities with reflex chrome and katanas." },
    { name: "6th Street", type: "Vigilante Gang", printed_page: 308, summary: "Patriotic 4th Corporate War veteran vigilantes turned neighborhood extortionists." },
    { name: "Voodoo Boys", type: "Terrorist Gang", printed_page: 309, summary: "Occult-themed drug syndicate dealing non-synthetics along Pacifica and university fringes." },
    { name: "Red Chrome Legion", type: "Hate Boostergang", printed_page: 309, summary: "Militaristic neo-fascist hate boostergang violently attacking outcasts, minorities, and Reclaimers." },
    { name: "Inquisitors", type: "Cult Gang", printed_page: 308, summary: "Anti-cyberware religious zealots who ambush victims to tear out implants without anesthesia." },
    { name: "Bozos", type: "Prankster Gang", printed_page: 308, summary: "Terrifying killer clown boostergang biosculpted with bulbous red noses and oversized flat feet." },
    { name: "Aldecaldos", type: "Nomad Nation", printed_page: 68, summary: "Foundational Nomad Nation leading post-war city rebuilding, container housing, and road convoys." },
  ],
  caper_styles: [
    {
      id: "heist",
      name: "Corporate Data / Cargo Heist",
      printed_page: 395,
      summary: "Tight-window infiltration, NET Extraction, and clean getaway against Corp security or rival syndicates.",
      default_beats: {
        hook: "A Fixer offers blueprints and half up-front for a tight 48-hour convoy or lab snatch.",
        developments: "Security shifts rotate early; an inside contact demands double or tips off a rival crew.",
        cliffhanger: "Lockdown traps the crew inside while Trauma Team or armored guards close in.",
        climax: "Running firefight across loading docks or NET vault extraction under live fire.",
        resolution: "Clean fence payout at a Night Market, Reputation gain, and lingering Corp heat.",
      },
    },
    {
      id: "street-turf",
      name: "Street Turf & Night Market Hustle",
      printed_page: 398,
      summary: "Neighborhood survival, gang protection rackets, missing friends, and local Fixer politics.",
      default_beats: {
        hook: "A neighborhood ripperdoc or Fixer begs for help after boostergangers seize their block's node.",
        developments: "Local Lawmen refuse to cross the line; a rival crew offers dirty hardware for a cut.",
        cliffhanger: "Someone on the block sold out the stash house to a Scav crew.",
        climax: "Showdown at an abandoned warehouse or rooftop club over the turf boss.",
        resolution: "The block owes the crew favors and safer Night Market discounts.",
      },
    },
    {
      id: "nomad-road",
      name: "Badlands Convoy & Smuggling Run",
      printed_page: 316,
      summary: "High-speed highway runs across the Red Badlands, border checkpoints, and Raffen Shiv ambushes.",
      default_beats: {
        hook: "Critical cargo must cross 80 miles of Red-dust highway before a Corp embargo locks the gates.",
        developments: "Acid dust storm scrambles comms; Raffen Shiv technicals shadow the convoy.",
        cliffhanger: "Bridge barricade holds an armored patrol demanding manifest inspection.",
        climax: "Full vehicular pursuit and boarding fight along a broken overpass.",
        resolution: "Delivery to Nomad Pack camp, vehicle repairs, and family Standing reward.",
      },
    },
    {
      id: "corp-intrigue",
      name: "Megacorp Extraction & Black Ops",
      printed_page: 402,
      summary: "Espionage, defector extractions, dirty Media leaks, and double-crosses in Westbrook & Corporate Center.",
      default_beats: {
        hook: "A nervous junior Exec wants extraction plus wiping their lab's prototype backups before midnight.",
        developments: "Extraction window shifts to a crowded Masquerade club; Black ICE guards the lab subnet.",
        cliffhanger: "The defector isn't fleeing—they are bait for a Militech wetwork squad.",
        climax: "Negotiate, betray, or fight through elite mercenaries to a waiting Gyrocopter.",
        resolution: "Huge eddie payout or explosive Media Screamsheet fallout across Night City.",
      },
    },
  ],
  screamsheet_hooks: [
    "BLACKOUT AT KABUKI PIER: A neighborhood clinic loses backup generator fuel during a rolling grid brownout and hires runners for 2,000 eb to recover a hijacked tanker.",
    "DEAD DROP ON LINE 4: A nervous courier vanishes inside an abandoned maglev maintenance tunnel carrying an encrypted biometric case worth 3,000 eb.",
    "WATER MAIN SQUEEZE: Rival street crews lock down a Rancho Coronado desalination valve; a local Night Market co-op pools 2,500 eb to break the blockade.",
    "GHOST BROADCAST: An unlicensed rooftop transmitter hijacks district Data Pool feeds with corporate shipping manifests, drawing a rapid strike team response.",
    "CHROME RECALL: A back-alley ripperdoc asks for discreet armed escort after discovering a batch of salvaged implants carries active tracking beacons.",
  ],
};

function pickOne<T>(items: T[]): T {
  return items[Math.floor(Math.random() * items.length)];
}

interface NpcDraftEntry {
  key: string;
  val: string;
  realName?: string;
  realNameHidden?: boolean;
  personality?: string;
  speechStyle?: string;
  showIdentity?: boolean;
}

interface ExtraClockDraft {
  name: string;
  segments: number;
  filled: number;
  category: "heat" | "obligation" | "deadline" | "faction" | "recovery";
  visibility: "public" | "secret";
  note: string;
}

interface LocationDraft {
  name: string;
  district: string;
  security: string;
  notes: string;
}

interface GigDraft {
  title: string;
  client: string;
  target: string;
  payoutEb: string;
  deadline: string;
  notes: string;
}

interface CampaignDraftData {
  name: string;
  district: string;
  caperStyle: string;
  selectedFactions: string[];
  factionMeta?: Record<string, { disposition: string; turf: string }>;
  screamsheetHook: string;
  summary: string;
  openingScene: string;
  beatHook: string;
  beatDev: string;
  beatCliff: string;
  beatClimax: string;
  beatRes: string;
  npcPairs: NpcDraftEntry[];
  objectivePairs: Array<{ key: string; val: string }>;
  discoveryPairs?: Array<{ key: string; val: string }>;
  locations?: LocationDraft[];
  gig?: GigDraft;
  gmSecrets: string;
  secretPairs?: Array<{ key: string; val: string }>;
  clockName: string;
  clockSegments: number;
  clockFilled?: number;
  clockCategory?: "heat" | "obligation" | "deadline" | "faction" | "recovery";
  clockVisibility?: "public" | "secret";
  clockNote: string;
  extraClocks?: ExtraClockDraft[];
  sessionZero?: {
    gmStyle: string;
    narratorLength: string;
    narratorPacing: string;
    lethalityDial: string;
    economyDial: string;
    campaignScope: string;
    startingClockMinutes: number;
    crewConcept: string;
    linesAndVeils: string;
  };
  aiGuidance: string;
  lockChoices: boolean;
  targetNpcCount: number;
  targetObjectiveCount: number;
}

export function CampaignCreatorModal({
  open,
  editCampaign,
  onClose,
  onCreated,
  onUpdated,
  onNotify,
}: CampaignCreatorModalProps) {
  const draftKey = editCampaign ? `campaign:edit:${editCampaign.id}` : "campaign:new";
  const hydratedRef = useRef(false);
  const hadSavedDraftRef = useRef(false);
  const [presets, setPresets] = useState<CampaignPresets>(FALLBACK_PRESETS);
  const [name, setName] = useState("");
  const [district, setDistrict] = useState("Watson Development");
  const [caperStyle, setCaperStyle] = useState("Corporate Data / Cargo Heist");
  const [selectedFactions, setSelectedFactions] = useState<string[]>(["Arasaka", "Tyger Claws"]);
  const [factionMeta, setFactionMeta] = useState<Record<string, { disposition: string; turf: string }>>({});
  const [screamsheetHook, setScreamsheetHook] = useState("");
  const [summary, setSummary] = useState("");
  const [openingScene, setOpeningScene] = useState("");
  const [beatHook, setBeatHook] = useState("");
  const [beatDev, setBeatDev] = useState("");
  const [beatCliff, setBeatCliff] = useState("");
  const [beatClimax, setBeatClimax] = useState("");
  const [beatRes, setBeatRes] = useState("");
  const [npcPairs, setNpcPairs] = useState<NpcDraftEntry[]>([]);
  const [objectivePairs, setObjectivePairs] = useState<Array<{ key: string; val: string }>>([]);
  const [discoveryPairs, setDiscoveryPairs] = useState<Array<{ key: string; val: string }>>([]);
  const [locations, setLocations] = useState<LocationDraft[]>([]);
  const [gig, setGig] = useState<GigDraft>({ title: "", client: "", target: "", payoutEb: "", deadline: "", notes: "" });
  const [gmSecrets, setGmSecrets] = useState("");
  const [secretPairs, setSecretPairs] = useState<Array<{ key: string; val: string }>>([]);
  const [revealGmSecrets, setRevealGmSecrets] = useState(false);
  const [clockName, setClockName] = useState("");
  const [clockSegments, setClockSegments] = useState(4);
  const [clockFilled, setClockFilled] = useState(0);
  const [clockCategory, setClockCategory] = useState<"heat" | "obligation" | "deadline" | "faction" | "recovery">("heat");
  const [clockVisibility, setClockVisibility] = useState<"public" | "secret">("public");
  const [clockNote, setClockNote] = useState("");
  const [extraClocks, setExtraClocks] = useState<ExtraClockDraft[]>([]);
  const [showSettingStyle, setShowSettingStyle] = useState(true);
  const [showPremiseOpening, setShowPremiseOpening] = useState(true);
  const [showBeatChart, setShowBeatChart] = useState(true);
  const [showNpcsObjectives, setShowNpcsObjectives] = useState(true);
  const [showWorldEntities, setShowWorldEntities] = useState(true);
  const [showSecretsClocks, setShowSecretsClocks] = useState(true);
  const [showSessionZero, setShowSessionZero] = useState(true);
  const [szGmStyle, setSzGmStyle] = useState("inherit");
  const [szNarratorLength, setSzNarratorLength] = useState("inherit");
  const [szNarratorPacing, setSzNarratorPacing] = useState("inherit");
  const [szLethality, setSzLethality] = useState("Standard RED");
  const [szEconomy, setSzEconomy] = useState("Standard RED");
  const [szScope, setSzScope] = useState("Mini-Arc");
  const [szStartMinutes, setSzStartMinutes] = useState(1320);
  const [szCrewConcept, setSzCrewConcept] = useState("");
  const [szLinesVeils, setSzLinesVeils] = useState("");
  const [unattachedChars, setUnattachedChars] = useState<CharacterRecord[]>([]);
  const [attachCharIds, setAttachCharIds] = useState<string[]>([]);
  const [launchIntroOnCreate, setLaunchIntroOnCreate] = useState(false);
  const [aiGuidance, setAiGuidance] = useState("");
  const [lockChoices, setLockChoices] = useState(false);
  const [targetNpcCount, setTargetNpcCount] = useState(3);
  const [targetObjectiveCount, setTargetObjectiveCount] = useState(2);
  const [draftRestored, setDraftRestored] = useState(false);
  const [aiBusyField, setAiBusyField] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const applyEditDefaults = (camp: CampaignRecord | null | undefined) => {
    if (camp) {
      setName(camp.name);
      const distUnres = camp.state.unresolved?.["District & Threat"] || "";
      const parsedDist = distUnres ? distUnres.split("[")[0].split("(")[0].trim() : "";
      setDistrict(parsedDist || "Watson Development");
      setCaperStyle("Corporate Data / Cargo Heist");
      setSelectedFactions(["Arasaka", "Tyger Claws"]);
      setScreamsheetHook("");
      setSummary(camp.state.summary || "");
      setOpeningScene(camp.state.scene || "");
      setNpcPairs(Object.entries(camp.state.npcs ?? {}).map(([key, val]) => ({ key, val })));
      setObjectivePairs(Object.entries(camp.state.objectives ?? {}).map(([key, val]) => ({ key, val })));
      setDiscoveryPairs(
        Object.entries(camp.state.discoveries ?? {})
          .filter(([k]) => !k.startsWith("__"))
          .map(([key, val]) => ({ key, val })),
      );
      setFactionMeta({});
      setLocations([]);
      setGig({ title: "", client: "", target: "", payoutEb: "", deadline: "", notes: "" });
      const beatStr = camp.state.unresolved?.["Beat Chart"] || "";
      const extractBeat = (label: string) => {
        const re = new RegExp(`(?:^|\\|\\s*)${label}:\\s*([^|]+)`, "i");
        const m = beatStr.match(re);
        return m ? m[1].trim() : "";
      };
      setBeatHook(extractBeat("Hook"));
      setBeatDev(extractBeat("Developments"));
      setBeatCliff(extractBeat("Cliffhanger"));
      setBeatClimax(extractBeat("Climax"));
      setBeatRes(extractBeat("Resolution"));
      setGmSecrets("");
      setSecretPairs([]);
      setClockName("");
      setClockSegments(4);
      setClockFilled(0);
      setClockCategory("heat");
      setClockVisibility("public");
      setClockNote("");
      setExtraClocks([]);
      setSzGmStyle("inherit");
      setSzNarratorLength("inherit");
      setSzNarratorPacing("inherit");
      setSzLethality("Standard RED");
      setSzEconomy("Standard RED");
      setSzScope("Mini-Arc");
      setSzStartMinutes(1320);
      setSzCrewConcept("");
      setSzLinesVeils("");
      setAttachCharIds([]);
      setLaunchIntroOnCreate(false);
      setAiGuidance("");
      setLockChoices(false);
      setTargetNpcCount(3);
      setTargetObjectiveCount(2);
    } else {
      setName("");
      setDistrict("Watson Development");
      setCaperStyle("Corporate Data / Cargo Heist");
      setSelectedFactions(["Arasaka", "Tyger Claws"]);
      setFactionMeta({});
      setScreamsheetHook("");
      setSummary("");
      setOpeningScene("");
      setBeatHook("");
      setBeatDev("");
      setBeatCliff("");
      setBeatClimax("");
      setBeatRes("");
      setNpcPairs([]);
      setObjectivePairs([]);
      setDiscoveryPairs([]);
      setLocations([]);
      setGig({ title: "", client: "", target: "", payoutEb: "", deadline: "", notes: "" });
      setGmSecrets("");
      setSecretPairs([]);
      setClockName("");
      setClockSegments(4);
      setClockFilled(0);
      setClockCategory("heat");
      setClockVisibility("public");
      setClockNote("");
      setExtraClocks([]);
      setSzGmStyle("inherit");
      setSzNarratorLength("inherit");
      setSzNarratorPacing("inherit");
      setSzLethality("Standard RED");
      setSzEconomy("Standard RED");
      setSzScope("Mini-Arc");
      setSzStartMinutes(1320);
      setSzCrewConcept("");
      setSzLinesVeils("");
      setAttachCharIds([]);
      setLaunchIntroOnCreate(false);
      setAiGuidance("");
      setLockChoices(false);
      setTargetNpcCount(3);
      setTargetObjectiveCount(2);
    }
  };

  useEffect(() => {
    if (!open) {
      hydratedRef.current = false;
      hadSavedDraftRef.current = false;
      return;
    }
    const existing = loadDraft<CampaignDraftData>(draftKey);
    hadSavedDraftRef.current = Boolean(existing);
    if (existing) {
      setName(existing.name ?? "");
      setDistrict(existing.district ?? "Watson Development");
      setCaperStyle(existing.caperStyle ?? "Corporate Data / Cargo Heist");
      setSelectedFactions(Array.isArray(existing.selectedFactions) ? existing.selectedFactions : ["Arasaka", "Tyger Claws"]);
      setFactionMeta(existing.factionMeta && typeof existing.factionMeta === "object" ? existing.factionMeta : {});
      setScreamsheetHook(existing.screamsheetHook ?? "");
      setSummary(existing.summary ?? "");
      setOpeningScene(existing.openingScene ?? "");
      setBeatHook(existing.beatHook ?? "");
      setBeatDev(existing.beatDev ?? "");
      setBeatCliff(existing.beatCliff ?? "");
      setBeatClimax(existing.beatClimax ?? "");
      setBeatRes(existing.beatRes ?? "");
      setNpcPairs(Array.isArray(existing.npcPairs) ? existing.npcPairs : []);
      setObjectivePairs(Array.isArray(existing.objectivePairs) ? existing.objectivePairs : []);
      setDiscoveryPairs(Array.isArray(existing.discoveryPairs) ? existing.discoveryPairs : []);
      setLocations(Array.isArray(existing.locations) ? existing.locations : []);
      setGig(existing.gig ?? { title: "", client: "", target: "", payoutEb: "", deadline: "", notes: "" });
      setGmSecrets(existing.gmSecrets ?? "");
      setSecretPairs(Array.isArray(existing.secretPairs) ? existing.secretPairs : []);
      setClockName(existing.clockName ?? "");
      setClockSegments(typeof existing.clockSegments === "number" ? existing.clockSegments : 4);
      setClockFilled(typeof existing.clockFilled === "number" ? existing.clockFilled : 0);
      setClockCategory(existing.clockCategory ?? "heat");
      setClockVisibility(existing.clockVisibility ?? "public");
      setClockNote(existing.clockNote ?? "");
      setExtraClocks(Array.isArray(existing.extraClocks) ? existing.extraClocks : []);
      if (existing.sessionZero) {
        setSzGmStyle(existing.sessionZero.gmStyle || "inherit");
        setSzNarratorLength(existing.sessionZero.narratorLength || "inherit");
        setSzNarratorPacing(existing.sessionZero.narratorPacing || "inherit");
        setSzLethality(existing.sessionZero.lethalityDial || "Standard RED");
        setSzEconomy(existing.sessionZero.economyDial || "Standard RED");
        setSzScope(existing.sessionZero.campaignScope || "Mini-Arc");
        setSzStartMinutes(
          typeof existing.sessionZero.startingClockMinutes === "number"
            ? existing.sessionZero.startingClockMinutes
            : 1320,
        );
        setSzCrewConcept(existing.sessionZero.crewConcept || "");
        setSzLinesVeils(existing.sessionZero.linesAndVeils || "");
      }
      setAiGuidance(existing.aiGuidance ?? "");
      setLockChoices(Boolean(existing.lockChoices));
      setTargetNpcCount(typeof existing.targetNpcCount === "number" ? existing.targetNpcCount : 3);
      setTargetObjectiveCount(typeof existing.targetObjectiveCount === "number" ? existing.targetObjectiveCount : 2);
      setDraftRestored(true);
    } else {
      applyEditDefaults(editCampaign);
      setDraftRestored(false);
    }
    setShowSettingStyle(true);
    setShowPremiseOpening(true);
    setShowBeatChart(true);
    setShowNpcsObjectives(true);
    setShowWorldEntities(true);
    setShowSecretsClocks(true);
    setShowSessionZero(true);
    setAttachCharIds([]);
    setLaunchIntroOnCreate(false);
    setRevealGmSecrets(false);
    setError("");
    hydratedRef.current = true;
  }, [open, editCampaign?.id, draftKey]);

  useEffect(() => {
    if (!open || !hydratedRef.current) return;
    const hasContent = Boolean(
      name.trim() ||
        summary.trim() ||
        openingScene.trim() ||
        screamsheetHook.trim() ||
        beatHook.trim() ||
        beatDev.trim() ||
        beatCliff.trim() ||
        beatClimax.trim() ||
        beatRes.trim() ||
        npcPairs.length > 0 ||
        objectivePairs.length > 0 ||
        discoveryPairs.length > 0 ||
        locations.length > 0 ||
        Boolean(gig.title.trim() || gig.client.trim() || gig.target.trim()) ||
        gmSecrets.trim() ||
        secretPairs.length > 0 ||
        clockName.trim() ||
        extraClocks.length > 0 ||
        szGmStyle !== "inherit" ||
        szNarratorLength !== "inherit" ||
        szNarratorPacing !== "inherit" ||
        szCrewConcept.trim() ||
        szLinesVeils.trim() ||
        aiGuidance.trim() ||
        lockChoices,
    );
    if (!hasContent && !editCampaign) return;
    saveDraft<CampaignDraftData>(draftKey, {
      name,
      district,
      caperStyle,
      selectedFactions,
      factionMeta,
      screamsheetHook,
      summary,
      openingScene,
      beatHook,
      beatDev,
      beatCliff,
      beatClimax,
      beatRes,
      npcPairs,
      objectivePairs,
      discoveryPairs,
      locations,
      gig,
      gmSecrets,
      secretPairs,
      clockName,
      clockSegments,
      clockFilled,
      clockCategory,
      clockVisibility,
      clockNote,
      extraClocks,
      sessionZero: {
        gmStyle: szGmStyle,
        narratorLength: szNarratorLength,
        narratorPacing: szNarratorPacing,
        lethalityDial: szLethality,
        economyDial: szEconomy,
        campaignScope: szScope,
        startingClockMinutes: szStartMinutes,
        crewConcept: szCrewConcept,
        linesAndVeils: szLinesVeils,
      },
      aiGuidance,
      lockChoices,
      targetNpcCount,
      targetObjectiveCount,
    });
  }, [
    open,
    draftKey,
    editCampaign,
    name,
    district,
    caperStyle,
    selectedFactions,
    factionMeta,
    screamsheetHook,
    summary,
    openingScene,
    beatHook,
    beatDev,
    beatCliff,
    beatClimax,
    beatRes,
    npcPairs,
    objectivePairs,
    discoveryPairs,
    locations,
    gig,
    gmSecrets,
    secretPairs,
    clockName,
    clockSegments,
    clockFilled,
    clockCategory,
    clockVisibility,
    clockNote,
    extraClocks,
    szGmStyle,
    szNarratorLength,
    szNarratorPacing,
    szLethality,
    szEconomy,
    szScope,
    szStartMinutes,
    szCrewConcept,
    szLinesVeils,
    aiGuidance,
    lockChoices,
    targetNpcCount,
    targetObjectiveCount,
  ]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    fetchCreationReference()
      .then((ref) => {
        if (!cancelled && ref.campaign_presets) {
          setPresets(ref.campaign_presets);
        }
      })
      .catch(() => {
        // Keep current presets state if reference fetch fails
      });
    if (editCampaign && !hadSavedDraftRef.current) {
      fetchCampaignContext(editCampaign.id)
        .then((ctx) => {
          if (cancelled || !ctx) return;
          const meta = ctx.campaign_meta;
          if (meta?.district) setDistrict(meta.district);
          if (meta?.caper_style) setCaperStyle(meta.caper_style);
          if (Array.isArray(meta?.factions)) setSelectedFactions(meta.factions.slice(0, 4));
          if (Array.isArray(meta?.faction_details)) {
            const fdMap: Record<string, { disposition: string; turf: string }> = {};
            for (const item of meta.faction_details) {
              if (item?.name) fdMap[item.name] = { disposition: item.disposition || "Neutral", turf: item.turf || "" };
            }
            setFactionMeta(fdMap);
          }
          if (Array.isArray(meta?.locations)) {
            setLocations(
              meta.locations.map((l) => ({
                name: l.name || "",
                district: l.district || "",
                security: l.security || "",
                notes: l.notes || "",
              })),
            );
          }
          if (meta?.gig) {
            setGig({
              title: meta.gig.title || "",
              client: meta.gig.client || "",
              target: meta.gig.target || "",
              payoutEb: typeof meta.gig.payout_eb === "number" ? String(meta.gig.payout_eb) : "",
              deadline: meta.gig.deadline || "",
              notes: meta.gig.notes || "",
            });
          }
          if (meta?.screamsheet_hook !== undefined) setScreamsheetHook(meta.screamsheet_hook);
          if (ctx.npc_profiles) {
            setNpcPairs(
              Object.entries(editCampaign.state.npcs ?? {}).map(([key, val]) => {
                const prof = ctx.npc_profiles?.[key];
                return {
                  key,
                  val,
                  realName: prof?.real_name || "",
                  realNameHidden: Boolean(prof?.real_name_hidden ?? false),
                  personality: prof?.personality || "",
                  speechStyle: prof?.speech_style || "",
                };
              }),
            );
          }
          if (ctx.gm_secrets && Object.keys(ctx.gm_secrets).length > 0) {
            const premise = ctx.gm_secrets["Premise Secret"] ?? "";
            setGmSecrets(premise);
            const extras = Object.entries(ctx.gm_secrets)
              .filter(([k]) => k !== "Premise Secret")
              .map(([key, val]) => ({ key, val }));
            setSecretPairs(extras);
          }
          if (Array.isArray(ctx.clocks) && ctx.clocks.length > 0) {
            const first = ctx.clocks[0];
            setClockName(first.name ?? "");
            setClockSegments(typeof first.segments === "number" ? first.segments : 4);
            setClockFilled(typeof first.filled === "number" ? first.filled : 0);
            setClockCategory((first.category as ExtraClockDraft["category"]) || "heat");
            setClockVisibility(first.visibility === "secret" ? "secret" : "public");
            setClockNote(first.note ?? "");
            setExtraClocks(
              ctx.clocks.slice(1).map((c) => ({
                name: c.name ?? "",
                segments: typeof c.segments === "number" ? c.segments : 4,
                filled: typeof c.filled === "number" ? c.filled : 0,
                category: (c.category as ExtraClockDraft["category"]) || "heat",
                visibility: c.visibility === "secret" ? "secret" : "public",
                note: c.note ?? "",
              })),
            );
          }
          const sz = ctx.session_zero;
          if (sz) {
            if (sz.gm_style) setSzGmStyle(sz.gm_style);
            if (sz.narrator_length) setSzNarratorLength(sz.narrator_length);
            if (sz.narrator_pacing) setSzNarratorPacing(sz.narrator_pacing);
            if (sz.lethality_dial) setSzLethality(sz.lethality_dial);
            if (sz.economy_dial) setSzEconomy(sz.economy_dial);
            if (sz.campaign_scope) setSzScope(sz.campaign_scope);
            if (sz.crew_concept !== undefined) setSzCrewConcept(sz.crew_concept);
            if (sz.lines_and_veils !== undefined) setSzLinesVeils(sz.lines_and_veils);
          }
          if (typeof ctx.solo?.runtime?.clock_minutes === "number") {
            setSzStartMinutes(ctx.solo.runtime.clock_minutes);
          }
        })
        .catch(() => {
          // Ignore hydration failure when running in minimal mocked contexts
        });
    }
    if (!editCampaign) {
      Promise.all([listCharacters(), listCampaigns()])
        .then(([chars, camps]) => {
          if (cancelled) return;
          const allChars = Array.isArray(chars) ? chars : [];
          const allCamps = Array.isArray(camps) ? camps : [];
          const claimedIds = new Set(allCamps.flatMap((c) => c.character_ids ?? []));
          setUnattachedChars(allChars.filter((ch) => ch?.id && !claimedIds.has(ch.id)));
        })
        .catch(() => {
          setUnattachedChars([]);
        });
    } else {
      setUnattachedChars([]);
    }
    return () => {
      cancelled = true;
    };
  }, [open, editCampaign?.id, draftKey]);

  if (!open) return null;

  const activeDistrict = presets.districts.find((d) => d.name === district) ?? presets.districts[0];
  const activeStyle = presets.caper_styles.find((s) => s.name === caperStyle) ?? presets.caper_styles[0];

  const toggleFaction = (fname: string) => {
    setSelectedFactions((prev) =>
      prev.includes(fname) ? prev.filter((x) => x !== fname) : prev.length < 4 ? [...prev, fname] : prev,
    );
  };

  const applyPresetScaffold = () => {
    const dist = activeDistrict ?? presets.districts[0];
    const style = activeStyle ?? presets.caper_styles[0];
    if (!dist || !style) return;
    const hookLine = screamsheetHook || pickOne(presets.screamsheet_hooks) || "";
    if (!screamsheetHook) setScreamsheetHook(hookLine);
    if (!name.trim()) {
      setName(`${dist.name.split(" ")[0]}: ${style.name.split(" ")[0]} Run`);
    }
    setSummary(
      `Set in ${dist.name}${dist.zone_type ? ` [${dist.zone_type}]` : ""} (Threat: ${dist.threat_rating}, p. ${dist.printed_page}). ${style.summary} Active powers: ${selectedFactions.length ? selectedFactions.join(", ") : "Night City fixers and boostergangs"}.`,
    );
    setOpeningScene(
      `Rain streaks neon crimson across ${dist.name}. Your crew huddles in a smoky booth as a Fixer slides an encrypted agent across the scarred table: "${hookLine}"`,
    );
    setBeatHook(style.default_beats.hook);
    setBeatDev(style.default_beats.developments);
    setBeatCliff(style.default_beats.cliffhanger);
    setBeatClimax(style.default_beats.climax);
    setBeatRes(style.default_beats.resolution);
    setNpcPairs([
      {
        key: "Fixer Mara Chen",
        val: `Local ${dist.name.split(" ")[0]} Fixer brokering the contract (500 eb upfront promised).`,
      },
      {
        key: `${selectedFactions[0] || "Corporate"} Enforcer`,
        val: `Opposing point-person defending the target in ${dist.name}.`,
      },
    ]);
    setObjectivePairs([
      {
        key: "Meet & Recon",
        val: `Confirm the target site in ${dist.name} and lock down approach routes.`,
      },
    ]);
    setClockName(`${selectedFactions[0] || "District"} Heat`);
    setClockSegments(4);
    setClockNote("Armed response teams sweep the block and prices lock up.");
  };

  const aiBusy = aiBusyField !== null;

  const handleAiCampaign = async (
    mode: "scratch" | "expand",
    field?: string,
    entryIndex?: number,
    subField?: string,
  ) => {
    if (aiBusy) return;
    setError("");
    const busyKey =
      entryIndex !== undefined && subField
        ? `${mode}:${field}:${entryIndex}:${subField}`
        : field
          ? `${mode}:${field}`
          : mode;
    setAiBusyField(busyKey);
    try {
      const npcsOrdered = npcPairs.map((p) => ({ key: p.key.trim(), val: p.val.trim() }));
      const objOrdered = objectivePairs.map((p) => ({ key: p.key.trim(), val: p.val.trim() }));
      const discOrdered = discoveryPairs.map((p) => ({ key: p.key.trim(), val: p.val.trim() }));
      const res = await assistCharacterCreation({
        target: "campaign",
        mode,
        ...(field ? { field } : {}),
        ...(entryIndex !== undefined ? { entry_index: entryIndex } : {}),
        ...(subField ? { sub_field: subField } : {}),
        guidance: aiGuidance.trim() || undefined,
        campaign: {
          name: name.trim() || undefined,
          district,
          threat_rating: activeDistrict?.threat_rating,
          caper_style: caperStyle,
          factions: selectedFactions,
          screamsheet_hook: screamsheetHook || undefined,
          lock_choices: lockChoices,
          ...(lockChoices
            ? { npc_count: targetNpcCount, objective_count: targetObjectiveCount }
            : {}),
        },
        current: {
          name: name.trim() || undefined,
          summary: summary.trim() || undefined,
          opening_scene: openingScene.trim() || undefined,
          gm_secrets: gmSecrets.trim() || undefined,
          secret_entries: secretPairs,
          beats: {
            hook: beatHook,
            developments: beatDev,
            cliffhanger: beatCliff,
            climax: beatClimax,
            resolution: beatRes,
          },
          npcs: npcsOrdered as unknown as Record<string, string>,
          objectives: objOrdered as unknown as Record<string, string>,
          discoveries: discOrdered as unknown as Record<string, string>,
          locations,
          gig: {
            title: gig.title,
            client: gig.client,
            target: gig.target,
            payout_eb: parseInt(gig.payoutEb, 10) || undefined,
            deadline: gig.deadline,
            notes: gig.notes,
          },
          opening_clock: clockName.trim() || clockNote.trim()
            ? { name: clockName.trim(), segments: clockSegments, note: clockNote.trim() }
            : undefined,
        },
      });
      if (entryIndex !== undefined && subField && res.value !== undefined) {
        const val = res.value;
        if (val) {
          if (field === "npcs") {
            setNpcPairs((p) => p.map((x, i) => (i === entryIndex ? { ...x, [subField]: val } : x)));
          } else if (field === "objectives") {
            setObjectivePairs((p) => p.map((x, i) => (i === entryIndex ? { ...x, [subField]: val } : x)));
          } else if (field === "discoveries") {
            setDiscoveryPairs((p) => p.map((x, i) => (i === entryIndex ? { ...x, [subField]: val } : x)));
          } else if (field === "locations") {
            setLocations((p) => p.map((x, i) => (i === entryIndex ? { ...x, [subField]: val } : x)));
          } else if (field === "gm_secrets") {
            setSecretPairs((p) => p.map((x, i) => (i === entryIndex ? { ...x, [subField]: val } : x)));
          }
        }
        onNotify(`${mode === "scratch" ? "Regenerated" : "Improved"} ${field?.replace(/_/g, " ") ?? "entry"}.`);
        return;
      }
      if (!field && mode === "scratch" && !lockChoices) {
        if (res.district) {
          const matchedDist = presets.districts.find(
            (d) => d.name.toLowerCase() === res.district!.toLowerCase(),
          );
          if (matchedDist) setDistrict(matchedDist.name);
        }
        if (res.caper_style) {
          const matchedStyle = presets.caper_styles.find(
            (s) => s.name.toLowerCase() === res.caper_style!.toLowerCase(),
          );
          if (matchedStyle) setCaperStyle(matchedStyle.name);
        }
        if (Array.isArray(res.factions) && res.factions.length > 0) {
          const nextFactions = res.factions.slice(0, 4).map((f) => {
            const matched = presets.factions.find((pf) => pf.name.toLowerCase() === f.toLowerCase());
            return matched ? matched.name : f;
          });
          setSelectedFactions(nextFactions);
        }
      }
      if (!field || field === "name") {
        if (res.name && (mode === "scratch" || field === "name" || !name.trim())) setName(res.name);
      }
      if ((!field || field === "summary") && res.summary) setSummary(res.summary);
      if ((!field || field === "opening_scene") && res.opening_scene) setOpeningScene(res.opening_scene);
      if (res.beat_chart && (!field || field === "beat_chart" || field.startsWith("beat_"))) {
        if (res.beat_chart.hook) setBeatHook(res.beat_chart.hook);
        if (res.beat_chart.developments) setBeatDev(res.beat_chart.developments);
        if (res.beat_chart.cliffhanger) setBeatCliff(res.beat_chart.cliffhanger);
        if (res.beat_chart.climax) setBeatClimax(res.beat_chart.climax);
        if (res.beat_chart.resolution) setBeatRes(res.beat_chart.resolution);
      }
      if ((!field || field === "npcs") && res.npcs && Object.keys(res.npcs).length > 0) {
        setNpcPairs(Object.entries(res.npcs).map(([key, val]) => ({ key, val })));
      }
      if ((!field || field === "objectives") && res.objectives && Object.keys(res.objectives).length > 0) {
        setObjectivePairs(Object.entries(res.objectives).map(([key, val]) => ({ key, val })));
      }
      if ((!field || field === "discoveries") && res.discoveries && Object.keys(res.discoveries).length > 0) {
        setDiscoveryPairs(Object.entries(res.discoveries).map(([key, val]) => ({ key, val })));
      }
      if ((!field || field === "locations") && Array.isArray(res.locations) && res.locations.length > 0) {
        setLocations(
          res.locations.map((l) => ({
            name: l.name || "",
            district: l.district || district,
            security: "",
            notes: l.notes || "",
          })),
        );
      }
      if ((!field || field === "gig") && res.gig) {
        setGig({
          title: res.gig.title || "",
          client: res.gig.client || "",
          target: res.gig.target || "",
          payoutEb: typeof res.gig.payout_eb === "number" ? String(res.gig.payout_eb) : "",
          deadline: res.gig.deadline || "",
          notes: res.gig.notes || "",
        });
      }
      if (field === "gig_title" && res.gig_title) setGig((g) => ({ ...g, title: res.gig_title! }));
      if (field === "gig_client" && res.gig_client) setGig((g) => ({ ...g, client: res.gig_client! }));
      if (field === "gig_target" && res.gig_target) setGig((g) => ({ ...g, target: res.gig_target! }));
      if (field === "gig_deadline" && res.gig_deadline) setGig((g) => ({ ...g, deadline: res.gig_deadline! }));
      if (field === "gig_notes" && res.gig_notes) setGig((g) => ({ ...g, notes: res.gig_notes! }));
      if ((!field || field === "gm_secrets") && res.gm_secrets) setGmSecrets(res.gm_secrets);
      if ((!field || field === "opening_clock") && res.opening_clock?.name) {
        setClockName(res.opening_clock.name);
        setClockSegments(res.opening_clock.segments || 4);
        setClockNote(res.opening_clock.note || "");
      }
      if (field === "clock_name" && res.clock_name) setClockName(res.clock_name);
      if (field === "clock_note" && res.clock_note) setClockNote(res.clock_note);
      onNotify(
        !field && mode === "scratch"
          ? "Generated full Night City campaign premise, Beat Chart & GM secrets."
          : `${mode === "scratch" ? "Regenerated" : "Improved"} ${field ? field.replace(/^beat_/, "").replace(/_/g, " ") : "campaign notes"}.`,
      );
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Campaign assist failed";
      setError(msg);
      onNotify(msg);
    } finally {
      setAiBusyField(null);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const title = name.trim();
    if (!title || busy) {
      setError("Enter a Campaign Title first.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const targetCampaign = editCampaign ?? (await createCampaign(title));
      const npcs = Object.fromEntries(
        npcPairs.filter((p) => p.key.trim() && p.val.trim()).map((p) => [p.key.trim(), p.val.trim()]),
      );
      const objectives = Object.fromEntries(
        objectivePairs.filter((p) => p.key.trim() && p.val.trim()).map((p) => [p.key.trim(), p.val.trim()]),
      );
      const discoveries = Object.fromEntries(
        discoveryPairs.filter((p) => p.key.trim() && p.val.trim()).map((p) => [p.key.trim(), p.val.trim()]),
      );
      const npcIdentities = Object.fromEntries(
        npcPairs
          .filter(
            (p) =>
              p.key.trim() &&
              (p.realName?.trim() || p.personality?.trim() || p.speechStyle?.trim()),
          )
          .map((p) => [
            p.key.trim(),
            {
              handle: p.key.trim(),
              ...(p.realName?.trim() ? { real_name: p.realName.trim() } : {}),
              real_name_hidden: Boolean(p.realNameHidden ?? false),
              ...(p.personality?.trim() ? { personality: p.personality.trim() } : {}),
              ...(p.speechStyle?.trim() ? { speech_style: p.speechStyle.trim() } : {}),
            },
          ]),
      );
      const secretsMap: Record<string, string> = {};
      if (gmSecrets.trim()) secretsMap["Premise Secret"] = gmSecrets.trim();
      for (const sp of secretPairs) {
        if (sp.key.trim() && sp.val.trim()) secretsMap[sp.key.trim()] = sp.val.trim();
      }
      const allClocks = [
        ...(clockName.trim()
          ? [
              {
                name: clockName.trim(),
                segments: clockSegments,
                filled: clockFilled,
                category: clockCategory,
                visibility: clockVisibility,
                note: clockNote.trim(),
              },
            ]
          : []),
        ...extraClocks
          .filter((c) => c.name.trim())
          .map((c) => ({
            name: c.name.trim(),
            segments: c.segments,
            filled: c.filled,
            category: c.category,
            visibility: c.visibility,
            note: c.note.trim(),
          })),
      ];
      const cleanLocations = locations
        .filter((l) => l.name.trim())
        .map((l) => ({
          name: l.name.trim(),
          district: l.district.trim() || district,
          security: l.security.trim(),
          notes: l.notes.trim(),
        }));
      const hasGig = Boolean(gig.title.trim() || gig.client.trim() || gig.target.trim() || gig.notes.trim());
      const factionDetails = selectedFactions.map((fname) => ({
        name: fname,
        disposition: factionMeta[fname]?.disposition || "Neutral",
        turf: factionMeta[fname]?.turf?.trim() || "",
      }));
      const beatLines = [
        beatHook.trim() ? `Hook: ${beatHook.trim()}` : "",
        beatDev.trim() ? `Developments: ${beatDev.trim()}` : "",
        beatCliff.trim() ? `Cliffhanger: ${beatCliff.trim()}` : "",
        beatClimax.trim() ? `Climax: ${beatClimax.trim()}` : "",
        beatRes.trim() ? `Resolution: ${beatRes.trim()}` : "",
      ].filter(Boolean);
      const hasWorldData =
        Boolean(editCampaign) ||
        Boolean(district) ||
        Boolean(caperStyle) ||
        selectedFactions.length > 0 ||
        Boolean(screamsheetHook.trim()) ||
        Boolean(summary.trim()) ||
        Boolean(openingScene.trim()) ||
        Object.keys(npcs).length > 0 ||
        Object.keys(objectives).length > 0 ||
        Object.keys(discoveries).length > 0 ||
        cleanLocations.length > 0 ||
        hasGig ||
        beatLines.length > 0 ||
        Object.keys(secretsMap).length > 0 ||
        allClocks.length > 0;

      if (hasWorldData) {
        const unresolvedPayload: Record<string, string> = {};
        if (beatLines.length > 0) {
          unresolvedPayload["Beat Chart"] = beatLines.join(" | ");
        }
        if (district) {
          unresolvedPayload["District & Threat"] = `${district}${activeDistrict?.zone_type ? ` [${activeDistrict.zone_type}]` : ""} (${activeDistrict?.threat_rating ?? "Moderate"})`;
        }
        const worldEntitiesPayload: NonNullable<CampaignBootstrapPayload["world_entities"]> = {
          ...(factionDetails.length > 0 || editCampaign ? { factions: factionDetails } : {}),
          ...(cleanLocations.length > 0 || editCampaign ? { locations: cleanLocations } : {}),
          ...(hasGig
            ? {
                gig: {
                  title: gig.title.trim() || "Opening Contract",
                  client: gig.client.trim(),
                  target: gig.target.trim(),
                  payout_eb: Number.parseInt(gig.payoutEb, 10) || 0,
                  deadline: gig.deadline.trim(),
                  notes: gig.notes.trim(),
                },
              }
            : editCampaign
              ? { gig: null as unknown as undefined }
              : {}),
          ...(screamsheetHook.trim()
            ? {
                screamsheet: {
                  headline: screamsheetHook.split(":")[0].trim().slice(0, 90) || "N54 Screamsheet Lead",
                  body: screamsheetHook.trim(),
                },
              }
            : {}),
        };
        const payload: CampaignBootstrapPayload = {
          ...(editCampaign ? { name: title, clear_missing: true } : {}),
          ...(district ? { district } : {}),
          ...(activeDistrict?.zone_type ? { zone_type: activeDistrict.zone_type } : {}),
          ...(activeDistrict?.threat_rating ? { threat_rating: activeDistrict.threat_rating } : {}),
          ...(caperStyle ? { caper_style: caperStyle } : {}),
          factions: selectedFactions,
          screamsheet_hook: screamsheetHook.trim(),
          ...(summary.trim() || editCampaign ? { summary: summary.trim() } : {}),
          ...(openingScene.trim() || editCampaign ? { scene: openingScene.trim() } : {}),
          ...(Object.keys(npcs).length > 0 || editCampaign ? { npcs } : {}),
          ...(Object.keys(objectives).length > 0 || editCampaign ? { objectives } : {}),
          ...(Object.keys(discoveries).length > 0 || editCampaign ? { discoveries } : {}),
          ...(Object.keys(npcIdentities).length > 0 || editCampaign ? { npc_identities: npcIdentities } : {}),
          ...(Object.keys(worldEntitiesPayload).length > 0 ? { world_entities: worldEntitiesPayload } : {}),
          ...(Object.keys(unresolvedPayload).length > 0 || editCampaign ? { unresolved: unresolvedPayload } : {}),
          ...(Object.keys(secretsMap).length > 0 || editCampaign ? { gm_secrets: secretsMap } : {}),
          ...(allClocks.length > 0 || editCampaign ? { clocks: allClocks } : {}),
          ...(clockName.trim()
            ? { opening_clock: { name: clockName.trim(), segments: clockSegments, note: clockNote.trim() } }
            : {}),
          session_zero: {
            gm_style: szGmStyle,
            narrator_length: szNarratorLength,
            narrator_pacing: szNarratorPacing,
            lethality_dial: szLethality,
            economy_dial: szEconomy,
            campaign_scope: szScope,
            crew_concept: szCrewConcept.trim(),
            lines_and_veils: szLinesVeils.trim(),
          },
          ...(!editCampaign ? { starting_clock_minutes: szStartMinutes } : {}),
          ...(!editCampaign && attachCharIds.length > 0 ? { attach_character_ids: attachCharIds } : {}),
        };
        await bootstrapCampaign(targetCampaign.id, payload);
      }

      clearDraft(draftKey);
      if (editCampaign && onUpdated) {
        await onUpdated(targetCampaign.id, title);
      } else {
        await onCreated(targetCampaign.id, title, { launchIntro: launchIntroOnCreate });
      }
      onClose();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to create campaign";
      setError(msg);
      onNotify(msg);
    } finally {
      setBusy(false);
    }
  };

  const handleResetDraft = () => {
    clearDraft(draftKey);
    applyEditDefaults(editCampaign);
    setDraftRestored(false);
    setRevealGmSecrets(false);
    setError("");
    onNotify("Campaign draft cleared.");
  };

  const busyFor = (fieldKey: string, entryIndex?: number, subField?: string): "improve" | "regen" | null => {
    const suffix = entryIndex !== undefined && subField ? `${fieldKey}:${entryIndex}:${subField}` : fieldKey;
    return aiBusyField === `expand:${suffix}`
      ? "improve"
      : aiBusyField === `scratch:${suffix}`
        ? "regen"
        : null;
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/85 p-3 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="Campaign Creator"
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
      }}
    >
      <form
        onSubmit={handleSubmit}
        className="cyber-hud-card flex max-h-[92vh] w-full max-w-5xl flex-col overflow-hidden rounded-xl bg-[#0b0f19] shadow-2xl"
      >
        {/* Header with Night Market Hero Strip */}
        <div className="relative flex items-center justify-between overflow-hidden border-b border-cyan-500/30 bg-[#0e1424] px-5 py-3.5">
          <img
            src={nightMarketHero}
            alt=""
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 h-full w-full object-cover opacity-25"
          />
          <div className="pointer-events-none absolute inset-0 bg-gradient-to-r from-[#0b0f19]/95 via-[#0e1424]/85 to-[#0b0f19]/90" />
          <div className="relative z-10 flex items-center gap-2.5">
            <Compass className="h-5 w-5 text-cyan-400" />
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="font-cyber-display text-sm font-bold tracking-wide text-slate-100 uppercase">
                  Corebook Campaign Architect (Night City 2045)
                </h2>
                {draftRestored && (
                  <span className="rounded border border-cyan-500/40 bg-cyan-500/15 px-1.5 py-0.5 font-mono text-[10px] text-cyan-200">
                    Draft Restored
                  </span>
                )}
              </div>
              <p className="font-cyber-hud text-[11px] text-slate-400">
                District threat, active gangs &amp; factions, Beat Chart, and spoiler-shielded GM truths.
              </p>
            </div>
          </div>
          <div className="relative z-10 flex items-center gap-1.5">
            <button
              type="button"
              onClick={handleResetDraft}
              title="Clear unsaved draft and reset form"
              className="inline-flex items-center gap-1 rounded border border-slate-700 bg-slate-900/90 px-2 py-1 text-[11px] text-slate-300 hover:border-rose-500/50 hover:text-rose-200"
            >
              <RotateCcw className="h-3 w-3" />
              <span className="hidden sm:inline">Reset</span>
            </button>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close Campaign Creator"
              className="rounded-md p-1.5 text-slate-400 hover:bg-slate-800 hover:text-slate-100"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {/* Quick AI / Scaffold Bar */}
          <div className="space-y-2.5 rounded-lg border border-cyan-500/30 bg-cyan-950/15 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className="font-cyber-hud text-xs font-bold tracking-wide text-cyan-200 uppercase">
                  World Builder &amp; Co-Architect
                </div>
                <p className="text-[11px] text-slate-300">
                  {lockChoices
                    ? "Locked mode: Generate from Scratch builds around your chosen District, Style, Gangs, and counts."
                    : "Auto mode: Generate from Scratch picks the District, Style, Gangs, and starting NPC/Objective counts."}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                <button
                  type="button"
                  aria-pressed={lockChoices}
                  onClick={() => setLockChoices((v) => !v)}
                  title="Lock District, Caper Style, Gangs, and starting NPC/Objective counts so AI generates around them"
                  className={`inline-flex items-center gap-1 rounded border px-2.5 py-1 text-[11px] font-semibold transition ${
                    lockChoices
                      ? "border-amber-500/70 bg-amber-500/20 text-amber-200 shadow-[0_0_12px_rgba(245,158,11,0.2)]"
                      : "border-slate-700 bg-slate-900 text-slate-300 hover:border-amber-500/50 hover:text-amber-200"
                  }`}
                >
                  {lockChoices ? <Lock className="h-3 w-3" /> : <Unlock className="h-3 w-3" />}
                  {lockChoices ? "Choices Locked" : "Lock Choices"}
                </button>
                <button
                  type="button"
                  onClick={applyPresetScaffold}
                  className="inline-flex items-center gap-1 rounded border border-slate-600 bg-slate-900 px-2.5 py-1 text-[11px] font-medium text-slate-200 hover:border-cyan-400"
                >
                  <Dices className="h-3.5 w-3.5 text-cyan-400" /> Apply Preset Scaffold
                </button>
                <button
                  type="button"
                  disabled={aiBusy}
                  onClick={() => void handleAiCampaign("scratch")}
                  className="inline-flex items-center gap-1 rounded border border-cyan-500/50 bg-cyan-500/15 px-2.5 py-1 text-[11px] font-semibold text-cyan-200 hover:bg-cyan-500/25 disabled:opacity-50"
                >
                  <Sparkles className="h-3 w-3" /> {aiBusyField === "scratch" ? "Architecting…" : "Generate from Scratch"}
                </button>
              </div>
            </div>

            {lockChoices && (
              <div className="flex flex-wrap items-center gap-3 border-t border-cyan-500/20 pt-2 text-[11px] text-amber-200">
                <span className="font-mono text-[10px] uppercase tracking-wider text-amber-300">
                  Locked Counts:
                </span>
                <label className="inline-flex items-center gap-1.5">
                  <span>Starting NPCs</span>
                  <input
                    type="number"
                    min={1}
                    max={8}
                    aria-label="Locked starting NPCs count"
                    value={targetNpcCount}
                    onChange={(e) => setTargetNpcCount(Math.max(1, Math.min(8, parseInt(e.target.value, 10) || 1)))}
                    className="w-14 rounded border border-amber-500/40 bg-slate-950 px-2 py-0.5 text-center font-mono text-xs text-slate-100"
                  />
                </label>
                <label className="inline-flex items-center gap-1.5">
                  <span>Starting Objectives</span>
                  <input
                    type="number"
                    min={1}
                    max={8}
                    aria-label="Locked starting Objectives count"
                    value={targetObjectiveCount}
                    onChange={(e) => setTargetObjectiveCount(Math.max(1, Math.min(8, parseInt(e.target.value, 10) || 1)))}
                    className="w-14 rounded border border-amber-500/40 bg-slate-950 px-2 py-0.5 text-center font-mono text-xs text-slate-100"
                  />
                </label>
              </div>
            )}
          </div>

          {error && (
            <div className="rounded border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {error}
            </div>
          )}

          {/* Setting & Style (Collapsible) */}
          <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-3 space-y-3">
            <button
              type="button"
              onClick={() => setShowSettingStyle((v) => !v)}
              className="flex w-full items-center justify-between text-xs font-semibold text-slate-200 hover:text-cyan-200"
            >
              <span className="inline-flex items-center gap-1.5">
                <MapPin className="h-3.5 w-3.5 text-rose-400" />
                Setting &amp; Style
              </span>
              <span className="font-mono text-[10px] text-cyan-400">{showSettingStyle ? "▲ Hide" : "▼ Expand"}</span>
            </button>
            {showSettingStyle && (
              <div className="space-y-3 border-t border-slate-800/80 pt-2.5">
                {/* Row 1: Title + Guidance */}
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div>
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <label className="block text-xs font-semibold text-slate-200">
                        Campaign Title *
                      </label>
                      <FieldAiActions
                        label="Campaign Title"
                        compact
                        disabled={aiBusy}
                        busyAction={busyFor("name")}
                        onImprove={() => void handleAiCampaign("expand", "name")}
                        onRegen={() => void handleAiCampaign("scratch", "name")}
                      />
                    </div>
                    <input
                      autoFocus
                      type="text"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      placeholder="e.g. Chrome over Kabuki"
                      className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-semibold text-slate-200">
                      Direction / Theme Prompt
                    </label>
                    <input
                      type="text"
                      value={aiGuidance}
                      onChange={(e) => setAiGuidance(e.target.value)}
                      placeholder="e.g. Noir smuggling crew caught between Maelstrom & Trauma Team"
                      className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                    />
                  </div>
                </div>

                {/* Row 2: District & Caper Style */}
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div className={`rounded-lg border p-3 space-y-2 ${lockChoices ? "border-amber-500/40 bg-amber-950/10" : "border-slate-800 bg-slate-900/50"}`}>
                    <label className="flex items-center justify-between text-xs font-semibold text-slate-200">
                      <span className="inline-flex items-center gap-1.5">
                        <MapPin className="h-3.5 w-3.5 text-rose-400" /> Starting District
                      </span>
                      {activeDistrict && (
                        <div className="flex items-center gap-1.5">
                          {activeDistrict.zone_type && (
                            <span className="rounded border border-cyan-500/40 bg-cyan-500/15 px-1.5 py-0.5 font-mono text-[10px] text-cyan-200">
                              {activeDistrict.zone_type}
                            </span>
                          )}
                          <span className="rounded border border-rose-500/40 bg-rose-500/15 px-1.5 py-0.5 font-mono text-[10px] text-rose-200">
                            {activeDistrict.threat_rating}
                          </span>
                        </div>
                      )}
                    </label>
                    <select
                      value={district}
                      onChange={(e) => setDistrict(e.target.value)}
                      className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100"
                    >
                      {presets.districts.map((d) => (
                        <option key={d.name} value={d.name}>
                          {d.name} ({d.zone_type ? `${d.zone_type} · ` : ""}{d.threat_rating})
                        </option>
                      ))}
                    </select>
                    {activeDistrict && (
                      <p className="text-[11px] text-slate-400">{activeDistrict.summary}</p>
                    )}
                  </div>

                  <div className={`rounded-lg border p-3 space-y-2 ${lockChoices ? "border-amber-500/40 bg-amber-950/10" : "border-slate-800 bg-slate-900/50"}`}>
                    <label className="flex items-center justify-between gap-1.5 text-xs font-semibold text-slate-200">
                      <span className="inline-flex items-center gap-1.5">
                        <Target className="h-3.5 w-3.5 text-cyan-400" /> Campaign / Caper Style
                      </span>
                      <span className="font-mono text-[10px] text-slate-400">
                        {lockChoices ? "Locked" : "Auto on Scratch"}
                      </span>
                    </label>
                    <select
                      value={caperStyle}
                      onChange={(e) => setCaperStyle(e.target.value)}
                      className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100"
                    >
                      {presets.caper_styles.map((s) => (
                        <option key={s.id} value={s.name}>
                          {s.name}
                        </option>
                      ))}
                    </select>
                    {activeStyle && <p className="text-[11px] text-slate-400">{activeStyle.summary}</p>}
                  </div>
                </div>

                {/* Factions & Screamsheet Hook */}
                <div className={`rounded-lg border p-3 space-y-3 ${lockChoices ? "border-amber-500/40 bg-amber-950/10" : "border-slate-800 bg-slate-900/50"}`}>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-xs font-semibold text-slate-200">
                      Active Gangs &amp; Factions (up to 4)
                    </span>
                    <button
                      type="button"
                      onClick={() => setScreamsheetHook(pickOne(presets.screamsheet_hooks))}
                      className="inline-flex items-center gap-1 text-[11px] text-cyan-300 hover:text-cyan-200"
                    >
                      <Dices className="h-3 w-3" /> Roll Screamsheet Hook
                    </button>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {presets.factions.map((fac) => {
                      const picked = selectedFactions.includes(fac.name);
                      return (
                        <button
                          key={fac.name}
                          type="button"
                          title={`${fac.type}: ${fac.summary}`}
                          onClick={() => toggleFaction(fac.name)}
                          className={`rounded-full border px-2.5 py-0.5 text-[11px] transition ${
                            picked
                              ? "border-cyan-500/60 bg-cyan-500/20 text-cyan-100"
                              : "border-slate-700 bg-slate-950 text-slate-400 hover:text-slate-200"
                          }`}
                        >
                          {fac.name}
                        </button>
                      );
                    })}
                  </div>
                  <input
                    type="text"
                    value={screamsheetHook}
                    onChange={(e) => setScreamsheetHook(e.target.value)}
                    placeholder="Screamsheet broadcast headline or rumor hitting Night City Nets today…"
                    className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100"
                  />
                  {selectedFactions.length > 0 && (
                    <div className="space-y-1.5 border-t border-slate-800/80 pt-2">
                      <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                        Faction Dispositions &amp; Turf (Seeded to Campaign Library)
                      </div>
                      <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                        {selectedFactions.map((fname) => {
                          const meta = factionMeta[fname] ?? { disposition: "Neutral", turf: "" };
                          return (
                            <div key={fname} className="flex items-center gap-1.5 rounded border border-slate-800 bg-slate-950/70 px-2 py-1">
                              <span className="min-w-[90px] truncate text-[11px] font-medium text-slate-200">{fname}</span>
                              <select
                                aria-label={`${fname} disposition`}
                                value={meta.disposition}
                                onChange={(e) =>
                                  setFactionMeta((prev) => ({
                                    ...prev,
                                    [fname]: { disposition: e.target.value, turf: meta.turf },
                                  }))
                                }
                                className="rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-[10px] text-slate-100"
                              >
                                {["Hostile", "Wary", "Neutral", "Allied"].map((d) => (
                                  <option key={d} value={d}>{d}</option>
                                ))}
                              </select>
                              <input
                                type="text"
                                value={meta.turf}
                                onChange={(e) =>
                                  setFactionMeta((prev) => ({
                                    ...prev,
                                    [fname]: { disposition: meta.disposition, turf: e.target.value },
                                  }))
                                }
                                placeholder="Turf / agenda…"
                                className="min-w-0 flex-1 rounded border border-slate-800 bg-slate-950 px-1.5 py-0.5 text-[10px] text-slate-200"
                              />
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Premise & Opening Scene (Collapsible) */}
          <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-3 space-y-2.5">
            <button
              type="button"
              onClick={() => setShowPremiseOpening((v) => !v)}
              className="flex w-full items-center justify-between text-xs font-semibold text-slate-200 hover:text-cyan-200"
            >
              <span className="inline-flex items-center gap-1.5">
                <Sparkles className="h-3.5 w-3.5 text-cyan-400" />
                Premise &amp; Opening Scene
              </span>
              <span className="font-mono text-[10px] text-cyan-400">{showPremiseOpening ? "▲ Hide" : "▼ Expand"}</span>
            </button>
            {showPremiseOpening && (
              <div className="grid grid-cols-1 gap-3 border-t border-slate-800/80 pt-2.5 sm:grid-cols-2">
                <div>
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <label className="block text-xs font-semibold text-slate-200">
                      Campaign Premise &amp; Central Conflict
                    </label>
                    <FieldAiActions
                      label="Campaign Premise"
                      compact
                      disabled={aiBusy}
                      busyAction={busyFor("summary")}
                      onImprove={() => void handleAiCampaign("expand", "summary")}
                      onRegen={() => void handleAiCampaign("scratch", "summary")}
                    />
                  </div>
                  <textarea
                    rows={3}
                    value={summary}
                    onChange={(e) => setSummary(e.target.value)}
                    placeholder="Core stakes, Fixer/Corp friction, and campaign tone…"
                    className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100"
                  />
                </div>
                <div>
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <label className="block text-xs font-semibold text-slate-200">
                      Opening Scene (Where Session 1 Drops In)
                    </label>
                    <FieldAiActions
                      label="Opening Scene"
                      compact
                      disabled={aiBusy}
                      busyAction={busyFor("opening_scene")}
                      onImprove={() => void handleAiCampaign("expand", "opening_scene")}
                      onRegen={() => void handleAiCampaign("scratch", "opening_scene")}
                    />
                  </div>
                  <textarea
                    rows={3}
                    value={openingScene}
                    onChange={(e) => setOpeningScene(e.target.value)}
                    placeholder="Sensory hook right before Turn 1: rain-slick alley, Afterlife booth, convoy checkpoint…"
                    className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100"
                  />
                </div>
              </div>
            )}
          </div>

          {/* Beat Chart Outline (Collapsible) */}
          <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3 space-y-2">
            <button
              type="button"
              onClick={() => setShowBeatChart((v) => !v)}
              className="flex w-full items-center justify-between text-xs font-semibold text-slate-200 hover:text-cyan-200"
            >
              <span className="inline-flex items-center gap-1.5">
                <ShieldAlert className="h-3.5 w-3.5 text-amber-400" />
                Beat Chart Outline
              </span>
              <span className="font-mono text-[10px] text-cyan-400">{showBeatChart ? "▲ Hide" : "▼ Expand"}</span>
            </button>
            {showBeatChart && (
              <div className="space-y-2 border-t border-slate-800/80 pt-2">
                <p className="text-[11px] text-amber-200/80">
                  Beat Chart: alternate Action, Investigation, and Character-Interaction beats.
                </p>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {([
                    ["Hook", "beat_hook", beatHook, setBeatHook, "Inciting Screamsheet / Fixer offer"],
                    ["Developments", "beat_developments", beatDev, setBeatDev, "Complications & mid-run twists"],
                    ["Cliffhanger", "beat_cliffhanger", beatCliff, setBeatCliff, "Reversal or trap raising stakes"],
                    ["Climax", "beat_climax", beatClimax, setBeatClimax, "Showdown / extraction payoff"],
                    ["Resolution", "beat_resolution", beatRes, setBeatRes, "Eddie payout, Rep & IP aftermath"],
                  ] as const).map(([label, fieldKey, val, setter, ph]) => (
                    <div key={label}>
                      <div className="mb-0.5 flex items-center justify-between gap-1">
                        <label className="block text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                          {label}
                        </label>
                        <FieldAiActions
                          label={label}
                          compact
                          disabled={aiBusy}
                          busyAction={busyFor(fieldKey)}
                          onImprove={() => void handleAiCampaign("expand", fieldKey)}
                          onRegen={() => void handleAiCampaign("scratch", fieldKey)}
                        />
                      </div>
                      <input
                        type="text"
                        value={val}
                        onChange={(e) => setter(e.target.value)}
                        placeholder={ph}
                        className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                      />
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Starting NPCs & Objectives (Collapsible) */}
          <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-3 space-y-2.5">
            <button
              type="button"
              onClick={() => setShowNpcsObjectives((v) => !v)}
              className="flex w-full items-center justify-between text-xs font-semibold text-slate-200 hover:text-cyan-200"
            >
              <span className="inline-flex items-center gap-1.5">
                <Users className="h-3.5 w-3.5 text-cyan-400" />
                Starting NPCs ({npcPairs.length}) &amp; Objectives ({objectivePairs.length})
              </span>
              <span className="font-mono text-[10px] text-cyan-400">{showNpcsObjectives ? "▲ Hide" : "▼ Expand"}</span>
            </button>
            {showNpcsObjectives && (
              <div className="grid grid-cols-1 gap-3 border-t border-slate-800/80 pt-2.5 sm:grid-cols-2">
                <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3 space-y-2">
                  <div className="flex flex-wrap items-center justify-between gap-1.5">
                    <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-200">
                      <Users className="h-3.5 w-3.5 text-cyan-400" /> Starting NPCs ({npcPairs.length})
                    </span>
                    <button
                      type="button"
                      onClick={() => setNpcPairs((p) => [...p, { key: "", val: "" }])}
                      className="inline-flex items-center gap-1 rounded border border-slate-700 bg-slate-950 px-2 py-0.5 text-[11px] text-cyan-300"
                    >
                      <Plus className="h-3 w-3" /> Add
                    </button>
                  </div>
                  {npcPairs.map((item, idx) => (
                    <div key={idx} className="space-y-1.5 rounded border border-slate-800/80 bg-slate-950/40 p-1.5">
                      <div className="flex flex-wrap items-center gap-1">
                        <div className="flex items-center gap-1">
                          <input
                            type="text"
                            value={item.key}
                            onChange={(e) =>
                              setNpcPairs((p) => p.map((x, i) => (i === idx ? { ...x, key: e.target.value } : x)))
                            }
                            placeholder="NPC Name / Role"
                            className="w-32 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                          />
                          <FieldAiActions
                            label={`NPC ${idx + 1} Name`}
                            compact
                            disabled={aiBusy}
                            busyAction={busyFor("npcs", idx, "key")}
                            onImprove={() => void handleAiCampaign("expand", "npcs", idx, "key")}
                            onRegen={() => void handleAiCampaign("scratch", "npcs", idx, "key")}
                          />
                        </div>
                        <div className="flex min-w-[140px] flex-1 items-center gap-1">
                          <input
                            type="text"
                            value={item.val}
                            onChange={(e) =>
                              setNpcPairs((p) => p.map((x, i) => (i === idx ? { ...x, val: e.target.value } : x)))
                            }
                            placeholder="Motive / tie to crew"
                            className="min-w-0 flex-1 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                          />
                          <FieldAiActions
                            label={`NPC ${idx + 1} Motive`}
                            compact
                            disabled={aiBusy}
                            busyAction={busyFor("npcs", idx, "val")}
                            onImprove={() => void handleAiCampaign("expand", "npcs", idx, "val")}
                            onRegen={() => void handleAiCampaign("scratch", "npcs", idx, "val")}
                          />
                        </div>
                        <button
                          type="button"
                          onClick={() =>
                            setNpcPairs((p) => p.map((x, i) => (i === idx ? { ...x, showIdentity: !x.showIdentity } : x)))
                          }
                          title="Edit NPC hidden legal name, personality & speech style"
                          className="rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-[10px] text-cyan-300 hover:border-cyan-400"
                        >
                          ID
                        </button>
                        <button
                          type="button"
                          onClick={() => setNpcPairs((p) => p.filter((_, i) => i !== idx))}
                          className="text-slate-500 hover:text-rose-400"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                      {item.showIdentity && (
                        <div className="grid grid-cols-1 gap-1.5 border-t border-slate-800/70 pt-1.5 sm:grid-cols-2">
                          <input
                            type="text"
                            value={item.realName ?? ""}
                            onChange={(e) =>
                              setNpcPairs((p) => p.map((x, i) => (i === idx ? { ...x, realName: e.target.value } : x)))
                            }
                            placeholder="Real legal name"
                            className="rounded border border-slate-800 bg-slate-950 px-2 py-0.5 text-[11px] text-slate-200"
                          />
                          <label className="inline-flex items-center gap-1.5 text-[10px] text-slate-300">
                            <input
                              type="checkbox"
                              checked={Boolean(item.realNameHidden)}
                              onChange={(e) =>
                                setNpcPairs((p) =>
                                  p.map((x, i) => (i === idx ? { ...x, realNameHidden: e.target.checked } : x)),
                                )
                              }
                              className="h-3 w-3 accent-amber-400"
                            />
                            <span>Hide legal name (GM Secret)</span>
                          </label>
                          <input
                            type="text"
                            value={item.personality ?? ""}
                            onChange={(e) =>
                              setNpcPairs((p) => p.map((x, i) => (i === idx ? { ...x, personality: e.target.value } : x)))
                            }
                            placeholder="Personality (e.g. Paranoid, sharp)"
                            className="rounded border border-slate-800 bg-slate-950 px-2 py-0.5 text-[11px] text-slate-200"
                          />
                          <input
                            type="text"
                            value={item.speechStyle ?? ""}
                            onChange={(e) =>
                              setNpcPairs((p) => p.map((x, i) => (i === idx ? { ...x, speechStyle: e.target.value } : x)))
                            }
                            placeholder="Speech style (e.g. Clipped corp-speak)"
                            className="rounded border border-slate-800 bg-slate-950 px-2 py-0.5 text-[11px] text-slate-200"
                          />
                        </div>
                      )}
                    </div>
                  ))}
                </div>

                <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3 space-y-2">
                  <div className="flex flex-wrap items-center justify-between gap-1.5">
                    <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-200">
                      <Target className="h-3.5 w-3.5 text-emerald-400" /> Starting Objectives ({objectivePairs.length})
                    </span>
                    <button
                      type="button"
                      onClick={() => setObjectivePairs((p) => [...p, { key: "", val: "" }])}
                      className="inline-flex items-center gap-1 rounded border border-slate-700 bg-slate-950 px-2 py-0.5 text-[11px] text-emerald-300"
                    >
                      <Plus className="h-3 w-3" /> Add
                    </button>
                  </div>
                  {objectivePairs.map((item, idx) => (
                    <div key={idx} className="flex flex-wrap items-center gap-1">
                      <div className="flex items-center gap-1">
                        <input
                          type="text"
                          value={item.key}
                          onChange={(e) =>
                            setObjectivePairs((p) => p.map((x, i) => (i === idx ? { ...x, key: e.target.value } : x)))
                          }
                          placeholder="Objective"
                          className="w-32 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                        />
                        <FieldAiActions
                          label={`Objective ${idx + 1} Title`}
                          compact
                          disabled={aiBusy}
                          busyAction={busyFor("objectives", idx, "key")}
                          onImprove={() => void handleAiCampaign("expand", "objectives", idx, "key")}
                          onRegen={() => void handleAiCampaign("scratch", "objectives", idx, "key")}
                        />
                      </div>
                      <div className="flex min-w-[140px] flex-1 items-center gap-1">
                        <input
                          type="text"
                          value={item.val}
                          onChange={(e) =>
                            setObjectivePairs((p) => p.map((x, i) => (i === idx ? { ...x, val: e.target.value } : x)))
                          }
                          placeholder="Details"
                          className="min-w-0 flex-1 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                        />
                        <FieldAiActions
                          label={`Objective ${idx + 1} Details`}
                          compact
                          disabled={aiBusy}
                          busyAction={busyFor("objectives", idx, "val")}
                          onImprove={() => void handleAiCampaign("expand", "objectives", idx, "val")}
                          onRegen={() => void handleAiCampaign("scratch", "objectives", idx, "val")}
                        />
                      </div>
                      <button
                        type="button"
                        onClick={() => setObjectivePairs((p) => p.filter((_, i) => i !== idx))}
                        className="text-slate-500 hover:text-rose-400"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* World Entities: Locations, Starting Gig & Discoveries */}
          <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3 space-y-2.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <button
                type="button"
                onClick={() => setShowWorldEntities((v) => !v)}
                className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-200 hover:text-cyan-200"
              >
                <MapPin className="h-3.5 w-3.5 text-cyan-400" />
                <span>
                  World Builder Extras: Locations ({locations.length}), Starting Gig &amp; Clues ({discoveryPairs.length})
                </span>
                <span className="font-mono text-[10px] text-cyan-400">{showWorldEntities ? "▲ Hide" : "▼ Expand"}</span>
              </button>
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => {
                    setShowWorldEntities(true);
                    setLocations((p) => [...p, { name: "", district, security: "", notes: "" }]);
                  }}
                  className="inline-flex items-center gap-1 rounded border border-slate-700 bg-slate-950 px-2 py-0.5 text-[10px] text-cyan-300"
                >
                  <Plus className="h-3 w-3" /> Location
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setShowWorldEntities(true);
                    setDiscoveryPairs((p) => [...p, { key: "", val: "" }]);
                  }}
                  className="inline-flex items-center gap-1 rounded border border-slate-700 bg-slate-950 px-2 py-0.5 text-[10px] text-emerald-300"
                >
                  <Plus className="h-3 w-3" /> Clue / Discovery
                </button>
              </div>
            </div>
            {showWorldEntities && (
              <div className="space-y-3 border-t border-slate-800/80 pt-2.5">
                {/* Starting Gig / Contract */}
                <div className="space-y-1.5">
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                    Starting Gig / Contract (Seeded to Library)
                  </div>
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                    <div className="flex items-center gap-1">
                      <input
                        type="text"
                        value={gig.title}
                        onChange={(e) => setGig((g) => ({ ...g, title: e.target.value }))}
                        placeholder="Gig Title (e.g. Kabuki Cold Drop)"
                        className="min-w-0 flex-1 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                      />
                      <FieldAiActions
                        label="Gig Title"
                        compact
                        disabled={aiBusy}
                        busyAction={busyFor("gig_title")}
                        onImprove={() => void handleAiCampaign("expand", "gig_title")}
                        onRegen={() => void handleAiCampaign("scratch", "gig_title")}
                      />
                    </div>
                    <div className="flex items-center gap-1">
                      <input
                        type="text"
                        value={gig.client}
                        onChange={(e) => setGig((g) => ({ ...g, client: e.target.value }))}
                        placeholder="Client / Fixer"
                        className="min-w-0 flex-1 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                      />
                      <FieldAiActions
                        label="Gig Client"
                        compact
                        disabled={aiBusy}
                        busyAction={busyFor("gig_client")}
                        onImprove={() => void handleAiCampaign("expand", "gig_client")}
                        onRegen={() => void handleAiCampaign("scratch", "gig_client")}
                      />
                    </div>
                    <div className="flex items-center gap-1">
                      <input
                        type="text"
                        value={gig.target}
                        onChange={(e) => setGig((g) => ({ ...g, target: e.target.value }))}
                        placeholder="Target / Asset"
                        className="min-w-0 flex-1 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                      />
                      <FieldAiActions
                        label="Gig Target"
                        compact
                        disabled={aiBusy}
                        busyAction={busyFor("gig_target")}
                        onImprove={() => void handleAiCampaign("expand", "gig_target")}
                        onRegen={() => void handleAiCampaign("scratch", "gig_target")}
                      />
                    </div>
                    <input
                      type="number"
                      min={0}
                      value={gig.payoutEb}
                      onChange={(e) => setGig((g) => ({ ...g, payoutEb: e.target.value }))}
                      placeholder="Payout (eb)"
                      className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                    />
                    <div className="flex items-center gap-1">
                      <input
                        type="text"
                        value={gig.deadline}
                        onChange={(e) => setGig((g) => ({ ...g, deadline: e.target.value }))}
                        placeholder="Deadline (e.g. 48 hours)"
                        className="min-w-0 flex-1 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                      />
                      <FieldAiActions
                        label="Gig Deadline"
                        compact
                        disabled={aiBusy}
                        busyAction={busyFor("gig_deadline")}
                        onImprove={() => void handleAiCampaign("expand", "gig_deadline")}
                        onRegen={() => void handleAiCampaign("scratch", "gig_deadline")}
                      />
                    </div>
                    <div className="flex items-center gap-1">
                      <input
                        type="text"
                        value={gig.notes}
                        onChange={(e) => setGig((g) => ({ ...g, notes: e.target.value }))}
                        placeholder="Contract terms / twist"
                        className="min-w-0 flex-1 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                      />
                      <FieldAiActions
                        label="Gig Notes"
                        compact
                        disabled={aiBusy}
                        busyAction={busyFor("gig_notes")}
                        onImprove={() => void handleAiCampaign("expand", "gig_notes")}
                        onRegen={() => void handleAiCampaign("scratch", "gig_notes")}
                      />
                    </div>
                  </div>
                </div>
                {/* Locations */}
                {locations.length > 0 && (
                  <div className="space-y-1.5">
                    <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                      Key Locations / Venues
                    </div>
                    {locations.map((loc, idx) => (
                      <div key={idx} className="grid grid-cols-1 gap-1.5 sm:grid-cols-4">
                        <div className="flex items-center gap-1">
                          <input
                            type="text"
                            value={loc.name}
                            onChange={(e) =>
                              setLocations((p) => p.map((x, i) => (i === idx ? { ...x, name: e.target.value } : x)))
                            }
                            placeholder="Venue / Block Name"
                            className="min-w-0 flex-1 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                          />
                          <FieldAiActions
                            label={`Location ${idx + 1} Name`}
                            compact
                            disabled={aiBusy}
                            busyAction={busyFor("locations", idx, "name")}
                            onImprove={() => void handleAiCampaign("expand", "locations", idx, "name")}
                            onRegen={() => void handleAiCampaign("scratch", "locations", idx, "name")}
                          />
                        </div>
                        <input
                          type="text"
                          value={loc.district}
                          onChange={(e) =>
                            setLocations((p) => p.map((x, i) => (i === idx ? { ...x, district: e.target.value } : x)))
                          }
                          placeholder="District"
                          className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                        />
                        <input
                          type="text"
                          value={loc.security}
                          onChange={(e) =>
                            setLocations((p) => p.map((x, i) => (i === idx ? { ...x, security: e.target.value } : x)))
                          }
                          placeholder="Security / Threat"
                          className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                        />
                        <div className="flex items-center gap-1">
                          <input
                            type="text"
                            value={loc.notes}
                            onChange={(e) =>
                              setLocations((p) => p.map((x, i) => (i === idx ? { ...x, notes: e.target.value } : x)))
                            }
                            placeholder="Vibe / access notes"
                            className="min-w-0 flex-1 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                          />
                          <FieldAiActions
                            label={`Location ${idx + 1} Notes`}
                            compact
                            disabled={aiBusy}
                            busyAction={busyFor("locations", idx, "notes")}
                            onImprove={() => void handleAiCampaign("expand", "locations", idx, "notes")}
                            onRegen={() => void handleAiCampaign("scratch", "locations", idx, "notes")}
                          />
                          <button
                            type="button"
                            onClick={() => setLocations((p) => p.filter((_, i) => i !== idx))}
                            className="text-slate-500 hover:text-rose-400"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                {/* Starting Discoveries */}
                {discoveryPairs.length > 0 && (
                  <div className="space-y-1.5">
                    <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                      Starting Discoveries / Clues Known to PCs
                    </div>
                    {discoveryPairs.map((dp, idx) => (
                      <div key={idx} className="flex flex-wrap items-center gap-1.5">
                        <div className="flex items-center gap-1">
                          <input
                            type="text"
                            value={dp.key}
                            onChange={(e) =>
                              setDiscoveryPairs((p) => p.map((x, i) => (i === idx ? { ...x, key: e.target.value } : x)))
                            }
                            placeholder="Clue / Intel"
                            className="w-36 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                          />
                          <FieldAiActions
                            label={`Discovery ${idx + 1} Title`}
                            compact
                            disabled={aiBusy}
                            busyAction={busyFor("discoveries", idx, "key")}
                            onImprove={() => void handleAiCampaign("expand", "discoveries", idx, "key")}
                            onRegen={() => void handleAiCampaign("scratch", "discoveries", idx, "key")}
                          />
                        </div>
                        <div className="flex min-w-[160px] flex-1 items-center gap-1">
                          <input
                            type="text"
                            value={dp.val}
                            onChange={(e) =>
                              setDiscoveryPairs((p) => p.map((x, i) => (i === idx ? { ...x, val: e.target.value } : x)))
                            }
                            placeholder="What the crew already knows at Session 1"
                            className="min-w-0 flex-1 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                          />
                          <FieldAiActions
                            label={`Discovery ${idx + 1} Details`}
                            compact
                            disabled={aiBusy}
                            busyAction={busyFor("discoveries", idx, "val")}
                            onImprove={() => void handleAiCampaign("expand", "discoveries", idx, "val")}
                            onRegen={() => void handleAiCampaign("scratch", "discoveries", idx, "val")}
                          />
                        </div>
                        <button
                          type="button"
                          onClick={() => setDiscoveryPairs((p) => p.filter((_, i) => i !== idx))}
                          className="text-slate-500 hover:text-rose-400"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* GM Secrets (Spoiler-Shielded) + Opening World Clocks (Collapsible) */}
          <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-3 space-y-2.5">
            <button
              type="button"
              onClick={() => setShowSecretsClocks((v) => !v)}
              className="flex w-full items-center justify-between text-xs font-semibold text-slate-200 hover:text-cyan-200"
            >
              <span className="inline-flex items-center gap-1.5">
                <Clock className="h-3.5 w-3.5 text-rose-400" />
                GM Secrets &amp; Opening Clocks
              </span>
              <span className="font-mono text-[10px] text-cyan-400">{showSecretsClocks ? "▲ Hide" : "▼ Expand"}</span>
            </button>
            {showSecretsClocks && (
              <div className="grid grid-cols-1 gap-3 border-t border-slate-800/80 pt-2.5 sm:grid-cols-2">
                <div className="rounded-lg border border-amber-500/30 bg-amber-950/10 p-3 space-y-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <label className="flex items-center gap-1.5 text-xs font-semibold text-amber-200">
                      {revealGmSecrets ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />}
                      <span>Hidden GM Secrets</span>
                    </label>
                    <label className="inline-flex cursor-pointer items-center gap-1.5 rounded border border-amber-500/40 bg-slate-950/90 px-2 py-0.5 text-[10px] font-semibold text-amber-200 hover:border-amber-400">
                      <input
                        type="checkbox"
                        checked={revealGmSecrets}
                        onChange={(e) => setRevealGmSecrets(e.target.checked)}
                        aria-label="Unspoil GM Secrets"
                        className="h-3 w-3 accent-amber-400"
                      />
                      <span>Unspoil</span>
                    </label>
                  </div>
                  {revealGmSecrets ? (
                    <div className="space-y-2">
                      <div className="space-y-1">
                        <div className="flex items-center justify-between gap-1">
                          <span className="text-[10px] font-semibold uppercase tracking-wider text-amber-300/80">
                            Core GM Truths
                          </span>
                          <FieldAiActions
                            label="GM Secrets"
                            compact
                            disabled={aiBusy}
                            busyAction={busyFor("gm_secrets")}
                            onImprove={() => void handleAiCampaign("expand", "gm_secrets")}
                            onRegen={() => void handleAiCampaign("scratch", "gm_secrets")}
                          />
                        </div>
                        <textarea
                          rows={2}
                          value={gmSecrets}
                          onChange={(e) => setGmSecrets(e.target.value)}
                          placeholder="Secret corporate betrayals, hidden employers, or traps kept out of player view…"
                          className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100"
                        />
                      </div>
                      {secretPairs.map((sp, idx) => (
                        <div key={idx} className="flex flex-wrap items-center gap-1.5">
                          <div className="flex items-center gap-1">
                            <input
                              type="text"
                              value={sp.key}
                              onChange={(e) =>
                                setSecretPairs((p) => p.map((x, i) => (i === idx ? { ...x, key: e.target.value } : x)))
                              }
                              placeholder="Secret Key"
                              className="w-28 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                            />
                            <FieldAiActions
                              label={`Secret ${idx + 1} Key`}
                              compact
                              disabled={aiBusy}
                              busyAction={busyFor("gm_secrets", idx, "key")}
                              onImprove={() => void handleAiCampaign("expand", "gm_secrets", idx, "key")}
                              onRegen={() => void handleAiCampaign("scratch", "gm_secrets", idx, "key")}
                            />
                          </div>
                          <div className="flex min-w-[140px] flex-1 items-center gap-1">
                            <input
                              type="text"
                              value={sp.val}
                              onChange={(e) =>
                                setSecretPairs((p) => p.map((x, i) => (i === idx ? { ...x, val: e.target.value } : x)))
                              }
                              placeholder="Hidden truth…"
                              className="min-w-0 flex-1 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                            />
                            <FieldAiActions
                              label={`Secret ${idx + 1} Truth`}
                              compact
                              disabled={aiBusy}
                              busyAction={busyFor("gm_secrets", idx, "val")}
                              onImprove={() => void handleAiCampaign("expand", "gm_secrets", idx, "val")}
                              onRegen={() => void handleAiCampaign("scratch", "gm_secrets", idx, "val")}
                            />
                          </div>
                          <button
                            type="button"
                            onClick={() => setSecretPairs((p) => p.filter((_, i) => i !== idx))}
                            className="text-slate-500 hover:text-rose-400"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      ))}
                      <button
                        type="button"
                        onClick={() => setSecretPairs((p) => [...p, { key: "", val: "" }])}
                        className="inline-flex items-center gap-1 rounded border border-amber-500/40 bg-slate-950 px-2 py-0.5 text-[10px] text-amber-200"
                      >
                        <Plus className="h-3 w-3" /> Add Secret Entry
                      </button>
                    </div>
                  ) : (
                    <div className="flex flex-col items-center justify-center rounded border border-amber-500/30 bg-slate-950/90 px-3 py-4 text-center">
                      <span className="font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-amber-300/90">
                        CLASSIFIED // SPOILER SHIELDED
                      </span>
                      <span className="mt-1 text-[11px] text-slate-400">
                        {gmSecrets.trim() || secretPairs.length > 0
                          ? "GM secrets are stored privately. Check Unspoil to reveal or edit."
                          : "Empty — AI can generate hidden twists. Check Unspoil to write or view."}
                      </span>
                    </div>
                  )}
                </div>

                <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3 space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-200">
                      <Clock className="h-3.5 w-3.5 text-rose-400" /> Opening World / Heat Clock
                    </div>
                    <button
                      type="button"
                      onClick={() =>
                        setExtraClocks((p) => [
                          ...p,
                          { name: "", segments: 4, filled: 0, category: "deadline", visibility: "public", note: "" },
                        ])
                      }
                      className="inline-flex items-center gap-1 rounded border border-slate-700 bg-slate-950 px-2 py-0.5 text-[10px] text-rose-300"
                    >
                      <Plus className="h-3 w-3" /> Clock
                    </button>
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <div className="flex min-w-[140px] flex-1 items-center gap-1">
                      <input
                        type="text"
                        value={clockName}
                        onChange={(e) => setClockName(e.target.value)}
                        placeholder="Clock name (e.g. Corp Trace)"
                        className="min-w-0 flex-1 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                      />
                      <FieldAiActions
                        label="Clock Name"
                        compact
                        disabled={aiBusy}
                        busyAction={busyFor("clock_name")}
                        onImprove={() => void handleAiCampaign("expand", "clock_name")}
                        onRegen={() => void handleAiCampaign("scratch", "clock_name")}
                      />
                    </div>
                    <input
                      type="number"
                      min={2}
                      max={12}
                      aria-label="Primary clock segments"
                      value={clockSegments}
                      onChange={(e) => {
                        const seg = Math.max(2, Math.min(12, parseInt(e.target.value, 10) || 4));
                        setClockSegments(seg);
                        setClockFilled((f) => Math.min(f, seg));
                      }}
                      className="w-14 rounded border border-slate-700 bg-slate-950 px-2 py-1 font-mono text-xs text-slate-100"
                    />
                    <input
                      type="number"
                      min={0}
                      max={clockSegments}
                      aria-label="Primary clock filled"
                      title="Initial filled segments"
                      value={clockFilled}
                      onChange={(e) => setClockFilled(Math.max(0, Math.min(clockSegments, parseInt(e.target.value, 10) || 0)))}
                      className="w-14 rounded border border-slate-700 bg-slate-950 px-2 py-1 font-mono text-xs text-slate-100"
                    />
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <select
                      aria-label="Primary clock category"
                      value={clockCategory}
                      onChange={(e) => setClockCategory(e.target.value as ExtraClockDraft["category"])}
                      className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-[11px] text-slate-200"
                    >
                      {["heat", "obligation", "deadline", "faction", "recovery"].map((c) => (
                        <option key={c} value={c}>{c}</option>
                      ))}
                    </select>
                    <select
                      aria-label="Primary clock visibility"
                      value={clockVisibility}
                      onChange={(e) => setClockVisibility(e.target.value as "public" | "secret")}
                      className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-[11px] text-slate-200"
                    >
                      <option value="public">Public</option>
                      <option value="secret">GM Secret</option>
                    </select>
                    <div className="flex min-w-[140px] flex-1 items-center gap-1">
                      <input
                        type="text"
                        value={clockNote}
                        onChange={(e) => setClockNote(e.target.value)}
                        placeholder="What happens when the clock fills…"
                        className="min-w-0 flex-1 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                      />
                      <FieldAiActions
                        label="Clock Trigger Note"
                        compact
                        disabled={aiBusy}
                        busyAction={busyFor("clock_note")}
                        onImprove={() => void handleAiCampaign("expand", "clock_note")}
                        onRegen={() => void handleAiCampaign("scratch", "clock_note")}
                      />
                    </div>
                  </div>
              {extraClocks.map((ec, idx) => (
                <div key={idx} className="space-y-1 border-t border-slate-800/80 pt-2">
                  <div className="flex gap-1.5">
                    <input
                      type="text"
                      value={ec.name}
                      onChange={(e) =>
                        setExtraClocks((p) => p.map((x, i) => (i === idx ? { ...x, name: e.target.value } : x)))
                      }
                      placeholder="Additional clock name"
                      className="flex-1 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                    />
                    <input
                      type="number"
                      min={2}
                      max={12}
                      value={ec.segments}
                      onChange={(e) => {
                        const seg = Math.max(2, Math.min(12, parseInt(e.target.value, 10) || 4));
                        setExtraClocks((p) =>
                          p.map((x, i) => (i === idx ? { ...x, segments: seg, filled: Math.min(x.filled, seg) } : x)),
                        );
                      }}
                      className="w-14 rounded border border-slate-700 bg-slate-950 px-2 py-1 font-mono text-xs text-slate-100"
                    />
                    <select
                      value={ec.visibility}
                      onChange={(e) =>
                        setExtraClocks((p) =>
                          p.map((x, i) => (i === idx ? { ...x, visibility: e.target.value as "public" | "secret" } : x)),
                        )
                      }
                      className="rounded border border-slate-700 bg-slate-950 px-1.5 py-1 text-[10px] text-slate-200"
                    >
                      <option value="public">Public</option>
                      <option value="secret">Secret</option>
                    </select>
                    <button
                      type="button"
                      onClick={() => setExtraClocks((p) => p.filter((_, i) => i !== idx))}
                      className="text-slate-500 hover:text-rose-400"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  <div className="flex gap-1.5">
                    <select
                      value={ec.category}
                      onChange={(e) =>
                        setExtraClocks((p) =>
                          p.map((x, i) =>
                            i === idx ? { ...x, category: e.target.value as ExtraClockDraft["category"] } : x,
                          ),
                        )
                      }
                      className="rounded border border-slate-700 bg-slate-950 px-1.5 py-0.5 text-[10px] text-slate-200"
                    >
                      {["heat", "obligation", "deadline", "faction", "recovery"].map((c) => (
                        <option key={c} value={c}>{c}</option>
                      ))}
                    </select>
                    <input
                      type="text"
                      value={ec.note}
                      onChange={(e) =>
                        setExtraClocks((p) => p.map((x, i) => (i === idx ? { ...x, note: e.target.value } : x)))
                      }
                      placeholder="Trigger note…"
                      className="flex-1 rounded border border-slate-700 bg-slate-950 px-2 py-0.5 text-[11px] text-slate-100"
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>
            )}
          </div>

          {/* Session Zero & Table Dials + Starting Party */}
          <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3 space-y-2.5">
            <button
              type="button"
              onClick={() => setShowSessionZero((v) => !v)}
              className="flex w-full items-center justify-between text-xs font-semibold text-slate-200 hover:text-cyan-200"
            >
              <span className="inline-flex items-center gap-1.5">
                <ShieldAlert className="h-3.5 w-3.5 text-cyan-400" />
                Session Zero Dials, Starting Time &amp; Table Boundaries
              </span>
              <span className="font-mono text-[10px] text-cyan-400">{showSessionZero ? "▲ Hide" : "▼ Expand"}</span>
            </button>
            {showSessionZero && (
              <div className="space-y-3 border-t border-slate-800/80 pt-2.5">
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                  <div>
                    <label className="mb-1 block text-[10px] font-semibold uppercase text-slate-400">GM Tone Override</label>
                    <select
                      aria-label="Session Zero GM Style"
                      value={szGmStyle}
                      onChange={(e) => setSzGmStyle(e.target.value)}
                      className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                    >
                      <option value="inherit">Inherit Server Default</option>
                      <option value="grounded">Grounded Street</option>
                      <option value="cinematic">Cinematic</option>
                      <option value="grit_dark">Grit &amp; Dark</option>
                      <option value="spy_thriller">Spy Thriller</option>
                      <option value="full_action">Full Action</option>
                      <option value="lethal">Lethal Combat Zone</option>
                      <option value="noir_mystery">Noir Mystery</option>
                      <option value="sandbox">Open Sandbox</option>
                    </select>
                  </div>
                  <div>
                    <label className="mb-1 block text-[10px] font-semibold uppercase text-slate-400">Reply Length</label>
                    <select
                      aria-label="Session Zero Reply Length"
                      value={szNarratorLength}
                      onChange={(e) => setSzNarratorLength(e.target.value)}
                      className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                    >
                      <option value="inherit">Inherit Server Default</option>
                      <option value="auto">Auto</option>
                      <option value="concise">Concise</option>
                      <option value="standard">Standard</option>
                      <option value="detailed">Detailed</option>
                      <option value="novel">Novelistic</option>
                    </select>
                  </div>
                  <div>
                    <label className="mb-1 block text-[10px] font-semibold uppercase text-slate-400">Pacing</label>
                    <select
                      aria-label="Session Zero Pacing"
                      value={szNarratorPacing}
                      onChange={(e) => setSzNarratorPacing(e.target.value)}
                      className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                    >
                      <option value="inherit">Inherit Server Default</option>
                      <option value="balanced">Balanced</option>
                      <option value="reactive">Reactive / Fast</option>
                      <option value="tactical">Tactical Crunch</option>
                      <option value="roleplay">Roleplay Heavy</option>
                      <option value="slow_burn">Slow Burn</option>
                    </select>
                  </div>
                  <div>
                    <label className="mb-1 block text-[10px] font-semibold uppercase text-slate-400">Lethality Dial</label>
                    <select
                      aria-label="Lethality Dial"
                      value={szLethality}
                      onChange={(e) => setSzLethality(e.target.value)}
                      className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                    >
                      <option value="Standard RED">Standard RED</option>
                      <option value="Gritty / High Lethality">Gritty / High Lethality</option>
                      <option value="Cinematic Action">Cinematic Action</option>
                    </select>
                  </div>
                  <div>
                    <label className="mb-1 block text-[10px] font-semibold uppercase text-slate-400">Economy Dial</label>
                    <select
                      aria-label="Economy Dial"
                      value={szEconomy}
                      onChange={(e) => setSzEconomy(e.target.value)}
                      className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                    >
                      <option value="Raw Scarcity">Raw Scarcity (Time of the Red)</option>
                      <option value="Standard RED">Standard RED (500–2,000 eb gigs)</option>
                      <option value="High-Roller">High-Roller Contracts</option>
                    </select>
                  </div>
                  <div>
                    <label className="mb-1 block text-[10px] font-semibold uppercase text-slate-400">Campaign Scope &amp; Time</label>
                    <div className="flex gap-1.5">
                      <select
                        aria-label="Campaign Scope"
                        value={szScope}
                        onChange={(e) => setSzScope(e.target.value)}
                        className="w-1/2 rounded border border-slate-700 bg-slate-950 px-1.5 py-1 text-xs text-slate-100"
                      >
                        <option value="One-Shot">One-Shot</option>
                        <option value="Mini-Arc">Mini-Arc</option>
                        <option value="Open Sandbox">Open Sandbox</option>
                      </select>
                      <select
                        aria-label="Starting Night City Time"
                        disabled={Boolean(editCampaign)}
                        title={editCampaign ? "Starting clock time is only set on campaign creation" : "Starting Night City time"}
                        value={szStartMinutes}
                        onChange={(e) => setSzStartMinutes(parseInt(e.target.value, 10) || 0)}
                        className="w-1/2 rounded border border-slate-700 bg-slate-950 px-1.5 py-1 text-xs text-slate-100 disabled:opacity-50"
                      >
                        <option value={0}>00:00 Midnight</option>
                        <option value={360}>06:00 Red Dawn</option>
                        <option value={720}>12:00 High Noon</option>
                        <option value={1140}>19:00 Dusk</option>
                        <option value={1320}>22:00 Night</option>
                      </select>
                    </div>
                  </div>
                </div>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <input
                    type="text"
                    value={szCrewConcept}
                    onChange={(e) => setSzCrewConcept(e.target.value)}
                    placeholder="Crew Concept / Shared HQ or Patron (e.g. Heywood ripperdoc clinic crew)"
                    className="rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100"
                  />
                  <input
                    type="text"
                    value={szLinesVeils}
                    onChange={(e) => setSzLinesVeils(e.target.value)}
                    placeholder="Lines & Veils / Safety Boundaries (topics off-limits for GM)"
                    className="rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100"
                  />
                </div>
                {!editCampaign && (
                  <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-800/80 pt-2">
                    <div className="flex flex-wrap items-center gap-2 text-xs">
                      {unattachedChars.length > 0 && (
                        <>
                          <span className="text-[11px] font-semibold text-slate-300">Attach Starting PCs:</span>
                          {unattachedChars.map((ch) => {
                            const checked = attachCharIds.includes(ch.id);
                            return (
                              <label key={ch.id} className="inline-flex items-center gap-1 rounded border border-slate-700 bg-slate-950 px-2 py-0.5 text-[11px] text-slate-200">
                                <input
                                  type="checkbox"
                                  checked={checked}
                                  onChange={() =>
                                    setAttachCharIds((prev) =>
                                      prev.includes(ch.id) ? prev.filter((x) => x !== ch.id) : [...prev, ch.id],
                                    )
                                  }
                                  className="h-3 w-3 accent-cyan-400"
                                />
                                <span>{ch.name}</span>
                              </label>
                            );
                          })}
                        </>
                      )}
                    </div>
                    <label className="inline-flex cursor-pointer items-center gap-1.5 text-[11px] font-semibold text-cyan-200">
                      <input
                        type="checkbox"
                        checked={launchIntroOnCreate}
                        onChange={(e) => setLaunchIntroOnCreate(e.target.checked)}
                        className="h-3.5 w-3.5 accent-cyan-400"
                      />
                      <span>Launch Opening GM Intro on Create</span>
                    </label>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-slate-800 bg-[#0e1424] px-5 py-3">
          <span className="text-[11px] text-slate-400">
            Closing preserves your draft automatically until saved or reset.
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-slate-300 hover:text-white"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={busy || !name.trim()}
              className="rounded-md bg-cyan-600 px-4 py-1.5 text-xs font-semibold text-white hover:bg-cyan-500 disabled:opacity-50"
            >
              {busy
                ? editCampaign
                  ? "Updating…"
                  : "Creating…"
                : editCampaign
                  ? "Apply Architect Updates"
                  : "Create Campaign"}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}
