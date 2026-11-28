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
import { CyberFrame, HazardBadge, HudButton, HudToggle, SegmentedBar } from "./cyber";
import { FieldAiActions } from "./FieldAiActions";

interface CampaignCreatorModalProps {
  open: boolean;
  editCampaign?: CampaignRecord | null;
  onClose: () => void;
  onCreated: (campaignId: string, name: string, options?: { launchIntro?: boolean }) => Promise<void>;
  onUpdated?: (campaignId: string, name: string) => Promise<void>;
  onNotify: (msg: string) => void;
}

const NO_PRESETS: CampaignPresets = {
  districts: [],
  factions: [],
  zone_types: [],
  threat_ratings: [],
  screamsheet_headlines: [],
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
  zoneType?: string;
  threatRating?: string;
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
  const [presets, setPresets] = useState<CampaignPresets>(NO_PRESETS);
  const [name, setName] = useState("");
  const [district, setDistrict] = useState("");
  const [zoneType, setZoneType] = useState("");
  const [threatRating, setThreatRating] = useState("");
  const [customFaction, setCustomFaction] = useState("");
  const [caperStyle, setCaperStyle] = useState("");
  const [selectedFactions, setSelectedFactions] = useState<string[]>([]);
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
      // The saved district, zone and threat arrive with the campaign context.
      setDistrict("");
      setZoneType("");
      setThreatRating("");
      setCaperStyle("");
      setSelectedFactions([]);
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
      setDistrict("");
      setZoneType("");
      setThreatRating("");
      setCaperStyle("");
      setSelectedFactions([]);
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
      setDistrict(existing.district ?? "");
      setZoneType(existing.zoneType ?? "");
      setThreatRating(existing.threatRating ?? "");
      setCaperStyle(existing.caperStyle ?? "");
      setSelectedFactions(Array.isArray(existing.selectedFactions) ? existing.selectedFactions : []);
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
      zoneType,
      threatRating,
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
    zoneType,
    threatRating,
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
        if (!cancelled) setPresets(ref.campaign_presets);
      })
      .catch((err) => {
        if (!cancelled) onNotify(err instanceof Error ? err.message : "Failed to load Corebook campaign presets");
      });
    if (editCampaign && !hadSavedDraftRef.current) {
      fetchCampaignContext(editCampaign.id)
        .then((ctx) => {
          if (cancelled || !ctx) return;
          const meta = ctx.campaign_meta;
          if (meta?.district) setDistrict(meta.district);
          if (meta?.zone_type) setZoneType(meta.zone_type);
          if (meta?.threat_rating) setThreatRating(meta.threat_rating);
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

  const activeDistrict = presets.districts.find((d) => d.name === district);
  const factionChoices = [
    ...presets.factions,
    ...selectedFactions
      .filter((name) => !presets.factions.some((f) => f.name === name))
      .map((name) => ({ name, type: "Custom", summary: "Your own faction" })),
  ];

  const rollScreamsheetHeadline = () => {
    const corp = () => pickOne(presets.factions.filter((f) => f.type === "Corporation")).name;
    return presets.screamsheet_headlines
      .map((column) => pickOne(column))
      .map((word) => (/pick a corp/i.test(word) ? corp() : word))
      .join(" ");
  };

  const toggleFaction = (fname: string) => {
    setSelectedFactions((prev) =>
      prev.includes(fname) ? prev.filter((x) => x !== fname) : prev.length < 4 ? [...prev, fname] : prev,
    );
  };

  const applyPresetScaffold = () => {
    const dist = activeDistrict ?? presets.districts[0];
    if (!dist) return;
    const hookLine = screamsheetHook || rollScreamsheetHeadline();
    if (!district) setDistrict(dist.name);
    if (!screamsheetHook) setScreamsheetHook(hookLine);
    if (!name.trim()) {
      setName(`${dist.name} Run`);
    }
    setSummary(
      `Set in ${dist.name}${zoneType ? ` [${zoneType}]` : ""}${threatRating ? ` (Threat: ${threatRating})` : ""}. Active powers: ${selectedFactions.length ? selectedFactions.join(", ") : "Night City fixers and boostergangs"}.`,
    );
    setOpeningScene(
      `Your crew meets in ${dist.name} as a Fixer slides an agent across the table. The screamsheet reads: "${hookLine}"`,
    );
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
          threat_rating: threatRating || undefined,
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
        if (res.caper_style) setCaperStyle(res.caper_style);
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
        const unresolvedPayload: Record<string, string> = editCampaign
          ? { ...(editCampaign.state.unresolved ?? {}) }
          : {};
        if (beatLines.length > 0) {
          unresolvedPayload["Beat Chart"] = beatLines.join(" | ");
        } else if (editCampaign) {
          delete unresolvedPayload["Beat Chart"];
        }
        if (district) {
          unresolvedPayload["District & Threat"] = `${district}${zoneType ? ` [${zoneType}]` : ""}${threatRating ? ` (${threatRating})` : ""}`;
        } else if (editCampaign) {
          delete unresolvedPayload["District & Threat"];
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
          ...(zoneType ? { zone_type: zoneType } : {}),
          ...(threatRating ? { threat_rating: threatRating } : {}),
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
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-3 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="Campaign Creator"
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
      }}
    >
      <CyberFrame
        variant="modal"
        className="flex max-h-[92vh] w-full max-w-5xl flex-col overflow-hidden"
      >
        <form onSubmit={handleSubmit} className="flex min-h-0 flex-1 flex-col overflow-hidden">
          {/* Slim Crimson Header Band with Night Market Hero Strip */}
          <div className="relative flex items-center justify-between overflow-hidden border-b border-[var(--hud-line)] bg-[#5a0b1c]/55 px-4 py-3 sm:px-5">
            <img
              src={nightMarketHero}
              alt=""
              aria-hidden="true"
              className="pointer-events-none absolute inset-0 h-full w-full object-cover opacity-20"
            />
            <div className="pointer-events-none absolute inset-0 bg-gradient-to-r from-[#3a0712]/80 via-[#5a0b1c]/55 to-[#12070c]/85" />
            <div className="relative z-10 flex items-center gap-2.5">
              <Compass className="h-5 w-5 shrink-0 text-[var(--hud-accent)]" />
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h2
                    data-text="Corebook Campaign Architect (Night City 2045)"
                    className="cp-glitch font-cyber-display text-sm font-semibold uppercase tracking-wider text-[var(--hud-text)]"
                  >
                    Corebook Campaign Architect (Night City 2045)
                  </h2>
                  {draftRestored && (
                    <span className="border border-[var(--hud-accent-line)] bg-[var(--hud-accent-navy)] px-1.5 py-0.5 font-cyber-data text-[10px] text-[var(--hud-accent)]">
                      Draft Restored
                    </span>
                  )}
                </div>
                <p className="font-cyber-ui text-[11px] text-[var(--hud-muted)]">
                  District threat, active gangs &amp; factions, Beat Chart, and spoiler-shielded GM truths.
                </p>
              </div>
            </div>
            <div className="relative z-10 flex items-center gap-1.5">
              <HudButton
                variant="tactical"
                size="xs"
                onClick={handleResetDraft}
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
                aria-label="Close Campaign Creator"
                className="px-2 py-1"
              >
                <X className="h-4 w-4" />
              </HudButton>
            </div>
          </div>

          {/* Body */}
          <div className="flex-1 space-y-4 overflow-y-auto p-5 font-cyber-ui">
            {/* Quick AI / Scaffold Bar */}
            <div className="space-y-2.5 border border-[var(--hud-accent-line)]/55 bg-[var(--hud-accent-navy)]/50 p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="font-cyber-display text-xs font-semibold uppercase tracking-wider text-[var(--hud-accent)]">
                    World Builder &amp; Co-Architect
                  </div>
                  <p className="font-cyber-ui text-[11px] text-[var(--hud-text)]">
                    {lockChoices
                      ? "Locked mode: Generate from Scratch builds around your chosen District, Style, Gangs, and counts."
                      : "Auto mode: Generate from Scratch picks the District, Style, Gangs, and starting NPC/Objective counts."}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  <HudButton
                    variant="tactical"
                    size="xs"
                    active={lockChoices}
                    aria-pressed={lockChoices}
                    onClick={() => setLockChoices((v) => !v)}
                    title="Lock District, Caper Style, Gangs, and starting NPC/Objective counts so AI generates around them"
                    className={
                      lockChoices
                        ? "border-[var(--hud-warn)]/80 bg-[var(--hud-warn)]/15 text-[var(--hud-warn)]"
                        : ""
                    }
                  >
                    {lockChoices ? <Lock className="h-3 w-3" /> : <Unlock className="h-3 w-3" />}
                    {lockChoices ? "Choices Locked" : "Lock Choices"}
                  </HudButton>
                  <HudButton
                    variant="tactical"
                    size="xs"
                    onClick={applyPresetScaffold}
                  >
                    <Dices className="h-3.5 w-3.5 text-[var(--hud-accent)]" /> Apply Preset Scaffold
                  </HudButton>
                  <HudButton
                    variant="tactical"
                    size="xs"
                    disabled={aiBusy}
                    onClick={() => void handleAiCampaign("scratch")}
                    className="border-[var(--hud-accent-line)] bg-[var(--hud-accent-navy)] text-[var(--hud-accent)]"
                  >
                    <Sparkles className="h-3 w-3" /> {aiBusyField === "scratch" ? "Architecting…" : "Generate from Scratch"}
                  </HudButton>
                </div>
              </div>

              {lockChoices && (
                <div className="flex flex-wrap items-center gap-3 border-t border-[var(--hud-line-soft)] pt-2 font-cyber-ui text-[11px] text-[var(--hud-warn)]">
                  <span className="font-cyber-ui text-[10px] font-semibold uppercase tracking-wider text-[var(--hud-warn)]">
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
                      className="w-14 border border-[var(--hud-warn)]/50 bg-black/60 px-2 py-0.5 text-center font-cyber-data text-xs text-[var(--hud-text)] focus:border-[var(--hud-warn)] focus:outline-none"
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
                      className="w-14 border border-[var(--hud-warn)]/50 bg-black/60 px-2 py-0.5 text-center font-cyber-data text-xs text-[var(--hud-text)] focus:border-[var(--hud-warn)] focus:outline-none"
                    />
                  </label>
                </div>
              )}
            </div>

            {error && (
              <div className="cyber-hazard-thin border border-[var(--hud-primary-bright)]/70 bg-[#5a0b1c]/40 px-3 py-2 font-cyber-ui text-xs text-rose-100">
                {error}
              </div>
            )}

            {/* Setting & Style (Collapsible) */}
            <div className="space-y-3 border border-[var(--hud-line-soft)] bg-[var(--hud-row)] p-3">
              <button
                type="button"
                onClick={() => setShowSettingStyle((v) => !v)}
                className="flex w-full items-center justify-between font-cyber-display text-xs font-semibold uppercase tracking-wider text-[var(--hud-text)] hover:text-[var(--hud-accent)]"
              >
                <span className="inline-flex items-center gap-1.5">
                  <MapPin className="h-3.5 w-3.5 text-[var(--hud-primary-bright)]" />
                  Setting &amp; Style
                </span>
                <span className="font-cyber-data text-[10px] text-[var(--hud-accent)]">{showSettingStyle ? "▲ Hide" : "▼ Expand"}</span>
              </button>
              {showSettingStyle && (
                <div className="space-y-3 border-t border-[var(--hud-line-soft)] pt-2.5">
                  {/* Row 1: Title + Guidance */}
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <div>
                      <div className="mb-1 flex items-center justify-between gap-2">
                        <label className="block font-cyber-ui text-xs font-semibold text-[var(--hud-text)]">
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
                        className="w-full border border-[var(--hud-line)] bg-black/60 px-3 py-2 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
                      />
                    </div>
                    <div>
                      <label className="mb-1 block font-cyber-ui text-xs font-semibold text-[var(--hud-text)]">
                        Direction / Theme Prompt
                      </label>
                      <input
                        type="text"
                        value={aiGuidance}
                        onChange={(e) => setAiGuidance(e.target.value)}
                        placeholder="e.g. Noir smuggling crew caught between Maelstrom & Trauma Team"
                        className="w-full border border-[var(--hud-line)] bg-black/60 px-3 py-2 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
                      />
                    </div>
                  </div>

                  {/* Row 2: District & Caper Style */}
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <div
                      className={`space-y-2 border p-3 bg-[var(--hud-panel)] ${
                        lockChoices ? "border-[var(--hud-warn)]/60" : "border-[var(--hud-line-soft)]"
                      }`}
                    >
                      <label className="flex items-center justify-between font-cyber-ui text-xs font-semibold text-[var(--hud-text)]">
                        <span className="inline-flex items-center gap-1.5">
                          <MapPin className="h-3.5 w-3.5 text-[var(--hud-primary-bright)]" /> Starting District
                        </span>
                      </label>
                      <select
                        value={district}
                        onChange={(e) => setDistrict(e.target.value)}
                        className="w-full border border-[var(--hud-line)] bg-black/60 px-2.5 py-1.5 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                      >
                        <option value="">Choose a district…</option>
                        {presets.districts.map((d) => (
                          <option key={d.name} value={d.name}>
                            {d.name}
                          </option>
                        ))}
                      </select>
                      {activeDistrict && (
                        <p className="font-cyber-ui text-[11px] text-[var(--hud-muted)]">{activeDistrict.summary}</p>
                      )}
                      <div className="grid grid-cols-2 gap-2">
                        {(
                          [
                            ["Zone Type", zoneType, setZoneType, presets.zone_types],
                            ["Threat Rating", threatRating, setThreatRating, presets.threat_ratings],
                          ] as const
                        ).map(([label, value, set, options]) => (
                          <select
                            key={label}
                            aria-label={label}
                            title={options.find((o) => o.name === value)?.summary}
                            value={value}
                            onChange={(e) => set(e.target.value)}
                            className="w-full border border-[var(--hud-line)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                          >
                            <option value="">{label}…</option>
                            {options.map((o) => (
                              <option key={o.name} value={o.name}>{o.name}</option>
                            ))}
                          </select>
                        ))}
                      </div>
                    </div>

                    <div
                      className={`space-y-2 border p-3 bg-[var(--hud-panel)] ${
                        lockChoices ? "border-[var(--hud-warn)]/60" : "border-[var(--hud-line-soft)]"
                      }`}
                    >
                      <label className="flex items-center justify-between gap-1.5 font-cyber-ui text-xs font-semibold text-[var(--hud-text)]">
                        <span className="inline-flex items-center gap-1.5">
                          <Target className="h-3.5 w-3.5 text-[var(--hud-accent)]" /> Campaign / Caper Style
                        </span>
                        <span className="font-cyber-data text-[10px] text-[var(--hud-muted)]">
                          {lockChoices ? "Locked" : "Auto on Scratch"}
                        </span>
                      </label>
                      <input
                        type="text"
                        aria-label="Campaign / Caper Style"
                        value={caperStyle}
                        onChange={(e) => setCaperStyle(e.target.value)}
                        placeholder="e.g. Heist, turf war, convoy run…"
                        className="w-full border border-[var(--hud-line)] bg-black/60 px-2.5 py-1.5 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
                      />
                    </div>
                  </div>

                  {/* Factions & Screamsheet Hook */}
                  <div
                    className={`space-y-3 border p-3 bg-[var(--hud-panel)] ${
                      lockChoices ? "border-[var(--hud-warn)]/60" : "border-[var(--hud-line-soft)]"
                    }`}
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-cyber-ui text-xs font-semibold text-[var(--hud-text)]">
                        Active Gangs &amp; Factions (up to 4)
                      </span>
                      <HudButton
                        variant="tactical"
                        size="xs"
                        disabled={!presets.screamsheet_headlines.length}
                        onClick={() => setScreamsheetHook(rollScreamsheetHeadline())}
                      >
                        <Dices className="h-3 w-3 text-[var(--hud-accent)]" /> Roll Screamsheet Headline
                      </HudButton>
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {factionChoices.map((fac) => {
                        const picked = selectedFactions.includes(fac.name);
                        return (
                          <button
                            key={fac.name}
                            type="button"
                            title={`${fac.type}: ${fac.summary}`}
                            onClick={() => toggleFaction(fac.name)}
                            className={`border px-2.5 py-0.5 font-cyber-ui text-[11px] transition ${
                              picked
                                ? "border-[var(--hud-accent-line)] bg-[var(--hud-accent-navy)] text-[var(--hud-accent)]"
                                : "border-[var(--hud-line-soft)] bg-black/50 text-[var(--hud-muted)] hover:border-[var(--hud-line)] hover:text-[var(--hud-text)]"
                            }`}
                          >
                            {fac.name}
                          </button>
                        );
                      })}
                    </div>
                    <input
                      type="text"
                      aria-label="Add a gang or faction"
                      value={customFaction}
                      onChange={(e) => setCustomFaction(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key !== "Enter") return;
                        e.preventDefault();
                        const added = customFaction.trim();
                        if (added && !selectedFactions.includes(added)) toggleFaction(added);
                        setCustomFaction("");
                      }}
                      placeholder="Add a gang or other faction and press Enter…"
                      className="w-full border border-[var(--hud-line)] bg-black/60 px-2.5 py-1.5 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
                    />
                    <input
                      type="text"
                      value={screamsheetHook}
                      onChange={(e) => setScreamsheetHook(e.target.value)}
                      placeholder="Screamsheet broadcast headline or rumor hitting Night City Nets today…"
                      className="w-full border border-[var(--hud-line)] bg-black/60 px-2.5 py-1.5 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
                    />
                    {selectedFactions.length > 0 && (
                      <div className="space-y-1.5 border-t border-[var(--hud-line-soft)] pt-2">
                        <div className="font-cyber-ui text-[10px] font-semibold uppercase tracking-wider text-[var(--hud-label)]">
                          Faction Dispositions &amp; Turf (Seeded to Campaign Library)
                        </div>
                        <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                          {selectedFactions.map((fname) => {
                            const meta = factionMeta[fname] ?? { disposition: "Neutral", turf: "" };
                            return (
                              <div
                                key={fname}
                                className="flex items-center gap-1.5 border border-[var(--hud-line-soft)] bg-black/50 px-2 py-1"
                              >
                                <span className="min-w-[90px] truncate font-cyber-ui text-[11px] font-medium text-[var(--hud-text)]">
                                  {fname}
                                </span>
                                <select
                                  aria-label={`${fname} disposition`}
                                  value={meta.disposition}
                                  onChange={(e) =>
                                    setFactionMeta((prev) => ({
                                      ...prev,
                                      [fname]: { disposition: e.target.value, turf: meta.turf },
                                    }))
                                  }
                                  className="border border-[var(--hud-line)] bg-black/70 px-1.5 py-0.5 font-cyber-ui text-[10px] text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
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
                                  className="min-w-0 flex-1 border border-[var(--hud-line-soft)] bg-black/60 px-1.5 py-0.5 font-cyber-ui text-[10px] text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
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
            <div className="space-y-2.5 border border-[var(--hud-line-soft)] bg-[var(--hud-row)] p-3">
              <button
                type="button"
                onClick={() => setShowPremiseOpening((v) => !v)}
                className="flex w-full items-center justify-between font-cyber-display text-xs font-semibold uppercase tracking-wider text-[var(--hud-text)] hover:text-[var(--hud-accent)]"
              >
                <span className="inline-flex items-center gap-1.5">
                  <Sparkles className="h-3.5 w-3.5 text-[var(--hud-accent)]" />
                  Premise &amp; Opening Scene
                </span>
                <span className="font-cyber-data text-[10px] text-[var(--hud-accent)]">{showPremiseOpening ? "▲ Hide" : "▼ Expand"}</span>
              </button>
              {showPremiseOpening && (
                <div className="grid grid-cols-1 gap-3 border-t border-[var(--hud-line-soft)] pt-2.5 sm:grid-cols-2">
                  <div>
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <label className="block font-cyber-ui text-xs font-semibold text-[var(--hud-text)]">
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
                      className="w-full border border-[var(--hud-line)] bg-black/60 px-2.5 py-1.5 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
                    />
                  </div>
                  <div>
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <label className="block font-cyber-ui text-xs font-semibold text-[var(--hud-text)]">
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
                      className="w-full border border-[var(--hud-line)] bg-black/60 px-2.5 py-1.5 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
                    />
                  </div>
                </div>
              )}
            </div>

            {/* Beat Chart Outline (Collapsible) */}
            <div className="space-y-2 border border-[var(--hud-line-soft)] bg-[var(--hud-row)] p-3">
              <button
                type="button"
                onClick={() => setShowBeatChart((v) => !v)}
                className="flex w-full items-center justify-between font-cyber-display text-xs font-semibold uppercase tracking-wider text-[var(--hud-text)] hover:text-[var(--hud-accent)]"
              >
                <span className="inline-flex items-center gap-1.5">
                  <ShieldAlert className="h-3.5 w-3.5 text-[var(--hud-warn)]" />
                  Beat Chart Outline
                </span>
                <span className="font-cyber-data text-[10px] text-[var(--hud-accent)]">{showBeatChart ? "▲ Hide" : "▼ Expand"}</span>
              </button>
              {showBeatChart && (
                <div className="space-y-2 border-t border-[var(--hud-line-soft)] pt-2">
                  <p className="font-cyber-ui text-[11px] text-[var(--hud-warn)]/90">
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
                          <label className="block font-cyber-ui text-[10px] font-semibold uppercase tracking-wider text-[var(--hud-label)]">
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
                          className="w-full border border-[var(--hud-line)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
                        />
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Starting NPCs & Objectives (Collapsible) */}
            <div className="space-y-2.5 border border-[var(--hud-line-soft)] bg-[var(--hud-row)] p-3">
              <button
                type="button"
                onClick={() => setShowNpcsObjectives((v) => !v)}
                className="flex w-full items-center justify-between font-cyber-display text-xs font-semibold uppercase tracking-wider text-[var(--hud-text)] hover:text-[var(--hud-accent)]"
              >
                <span className="inline-flex items-center gap-1.5">
                  <Users className="h-3.5 w-3.5 text-[var(--hud-accent)]" />
                  Starting NPCs (<span className="font-cyber-data">{npcPairs.length}</span>) &amp; Objectives (
                  <span className="font-cyber-data">{objectivePairs.length}</span>)
                </span>
                <span className="font-cyber-data text-[10px] text-[var(--hud-accent)]">
                  {showNpcsObjectives ? "▲ Hide" : "▼ Expand"}
                </span>
              </button>
              {showNpcsObjectives && (
                <div className="grid grid-cols-1 gap-3 border-t border-[var(--hud-line-soft)] pt-2.5 sm:grid-cols-2">
                  <div className="space-y-2 border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] p-3">
                    <div className="flex flex-wrap items-center justify-between gap-1.5">
                      <span className="inline-flex items-center gap-1.5 font-cyber-ui text-xs font-semibold text-[var(--hud-text)]">
                        <Users className="h-3.5 w-3.5 text-[var(--hud-accent)]" /> Starting NPCs (
                        <span className="font-cyber-data">{npcPairs.length}</span>)
                      </span>
                      <HudButton
                        variant="tactical"
                        size="xs"
                        onClick={() => setNpcPairs((p) => [...p, { key: "", val: "" }])}
                      >
                        <Plus className="h-3 w-3 text-[var(--hud-accent)]" /> Add
                      </HudButton>
                    </div>
                    {npcPairs.map((item, idx) => (
                      <div key={idx} className="space-y-1.5 border border-[var(--hud-line-soft)] bg-black/45 p-1.5">
                        <div className="flex flex-wrap items-center gap-1">
                          <div className="flex items-center gap-1">
                            <input
                              type="text"
                              value={item.key}
                              onChange={(e) =>
                                setNpcPairs((p) => p.map((x, i) => (i === idx ? { ...x, key: e.target.value } : x)))
                              }
                              placeholder="NPC Name / Role"
                              className="w-32 border border-[var(--hud-line)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
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
                              className="min-w-0 flex-1 border border-[var(--hud-line)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
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
                          <HudButton
                            variant="tactical"
                            size="xs"
                            active={Boolean(item.showIdentity)}
                            onClick={() =>
                              setNpcPairs((p) =>
                                p.map((x, i) => (i === idx ? { ...x, showIdentity: !x.showIdentity } : x)),
                              )
                            }
                            title="Edit NPC hidden legal name, personality & speech style"
                            className="px-1.5"
                          >
                            ID
                          </HudButton>
                          <HudButton
                            variant="ghost"
                            size="xs"
                            onClick={() => setNpcPairs((p) => p.filter((_, i) => i !== idx))}
                            aria-label={`Remove NPC ${idx + 1}`}
                            className="px-1 text-[var(--hud-muted)] hover:text-[var(--hud-primary-bright)]"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </HudButton>
                        </div>
                        {item.showIdentity && (
                          <div className="grid grid-cols-1 gap-1.5 border-t border-[var(--hud-line-soft)] pt-1.5 sm:grid-cols-2">
                            <input
                              type="text"
                              value={item.realName ?? ""}
                              onChange={(e) =>
                                setNpcPairs((p) => p.map((x, i) => (i === idx ? { ...x, realName: e.target.value } : x)))
                              }
                              placeholder="Real legal name"
                              className="border border-[var(--hud-line-soft)] bg-black/60 px-2 py-0.5 font-cyber-ui text-[11px] text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
                            />
                            <label className="inline-flex items-center gap-1.5 font-cyber-ui text-[10px] text-[var(--hud-text)]">
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
                                setNpcPairs((p) =>
                                  p.map((x, i) => (i === idx ? { ...x, personality: e.target.value } : x)),
                                )
                              }
                              placeholder="Personality (e.g. Paranoid, sharp)"
                              className="border border-[var(--hud-line-soft)] bg-black/60 px-2 py-0.5 font-cyber-ui text-[11px] text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
                            />
                            <input
                              type="text"
                              value={item.speechStyle ?? ""}
                              onChange={(e) =>
                                setNpcPairs((p) =>
                                  p.map((x, i) => (i === idx ? { ...x, speechStyle: e.target.value } : x)),
                                )
                              }
                              placeholder="Speech style (e.g. Clipped corp-speak)"
                              className="border border-[var(--hud-line-soft)] bg-black/60 px-2 py-0.5 font-cyber-ui text-[11px] text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
                            />
                          </div>
                        )}
                      </div>
                    ))}
                  </div>

                  <div className="space-y-2 border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] p-3">
                    <div className="flex flex-wrap items-center justify-between gap-1.5">
                      <span className="inline-flex items-center gap-1.5 font-cyber-ui text-xs font-semibold text-[var(--hud-text)]">
                        <Target className="h-3.5 w-3.5 text-[var(--hud-ok)]" /> Starting Objectives (
                        <span className="font-cyber-data">{objectivePairs.length}</span>)
                      </span>
                      <HudButton
                        variant="tactical"
                        size="xs"
                        onClick={() => setObjectivePairs((p) => [...p, { key: "", val: "" }])}
                      >
                        <Plus className="h-3 w-3 text-[var(--hud-ok)]" /> Add
                      </HudButton>
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
                            className="w-32 border border-[var(--hud-line)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
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
                            className="min-w-0 flex-1 border border-[var(--hud-line)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
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
                        <HudButton
                          variant="ghost"
                          size="xs"
                          onClick={() => setObjectivePairs((p) => p.filter((_, i) => i !== idx))}
                          aria-label={`Remove Objective ${idx + 1}`}
                          className="px-1 text-[var(--hud-muted)] hover:text-[var(--hud-primary-bright)]"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </HudButton>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* World Entities: Locations, Starting Gig & Discoveries */}
            <div className="space-y-2.5 border border-[var(--hud-line-soft)] bg-[var(--hud-row)] p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <button
                  type="button"
                  onClick={() => setShowWorldEntities((v) => !v)}
                  className="inline-flex items-center gap-1.5 font-cyber-display text-xs font-semibold uppercase tracking-wider text-[var(--hud-text)] hover:text-[var(--hud-accent)]"
                >
                  <MapPin className="h-3.5 w-3.5 text-[var(--hud-accent)]" />
                  <span>
                    World Builder Extras: Locations (<span className="font-cyber-data">{locations.length}</span>), Starting Gig &amp; Clues (
                    <span className="font-cyber-data">{discoveryPairs.length}</span>)
                  </span>
                  <span className="font-cyber-data text-[10px] text-[var(--hud-accent)]">
                    {showWorldEntities ? "▲ Hide" : "▼ Expand"}
                  </span>
                </button>
                <div className="flex items-center gap-1.5">
                  <HudButton
                    variant="tactical"
                    size="xs"
                    onClick={() => {
                      setShowWorldEntities(true);
                      setLocations((p) => [...p, { name: "", district, security: "", notes: "" }]);
                    }}
                  >
                    <Plus className="h-3 w-3 text-[var(--hud-accent)]" /> Location
                  </HudButton>
                  <HudButton
                    variant="tactical"
                    size="xs"
                    onClick={() => {
                      setShowWorldEntities(true);
                      setDiscoveryPairs((p) => [...p, { key: "", val: "" }]);
                    }}
                  >
                    <Plus className="h-3 w-3 text-[var(--hud-ok)]" /> Clue / Discovery
                  </HudButton>
                </div>
              </div>
              {showWorldEntities && (
                <div className="space-y-3 border-t border-[var(--hud-line-soft)] pt-2.5">
                  {/* Starting Gig / Contract */}
                  <div className="space-y-1.5">
                    <div className="font-cyber-ui text-[10px] font-semibold uppercase tracking-wider text-[var(--hud-label)]">
                      Starting Gig / Contract (Seeded to Library)
                    </div>
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                      <div className="flex items-center gap-1">
                        <input
                          type="text"
                          value={gig.title}
                          onChange={(e) => setGig((g) => ({ ...g, title: e.target.value }))}
                          placeholder="Gig Title (e.g. Kabuki Cold Drop)"
                          className="min-w-0 flex-1 border border-[var(--hud-line)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
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
                          className="min-w-0 flex-1 border border-[var(--hud-line)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
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
                          className="min-w-0 flex-1 border border-[var(--hud-line)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
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
                        className="border border-[var(--hud-line)] bg-black/60 px-2 py-1 font-cyber-data text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
                      />
                      <div className="flex items-center gap-1">
                        <input
                          type="text"
                          value={gig.deadline}
                          onChange={(e) => setGig((g) => ({ ...g, deadline: e.target.value }))}
                          placeholder="Deadline (e.g. 48 hours)"
                          className="min-w-0 flex-1 border border-[var(--hud-line)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
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
                          className="min-w-0 flex-1 border border-[var(--hud-line)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
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
                      <div className="font-cyber-ui text-[10px] font-semibold uppercase tracking-wider text-[var(--hud-label)]">
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
                              className="min-w-0 flex-1 border border-[var(--hud-line)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
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
                            className="border border-[var(--hud-line)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
                          />
                          <input
                            type="text"
                            value={loc.security}
                            onChange={(e) =>
                              setLocations((p) => p.map((x, i) => (i === idx ? { ...x, security: e.target.value } : x)))
                            }
                            placeholder="Security / Threat"
                            className="border border-[var(--hud-line)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
                          />
                          <div className="flex items-center gap-1">
                            <input
                              type="text"
                              value={loc.notes}
                              onChange={(e) =>
                                setLocations((p) => p.map((x, i) => (i === idx ? { ...x, notes: e.target.value } : x)))
                              }
                              placeholder="Vibe / access notes"
                              className="min-w-0 flex-1 border border-[var(--hud-line)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
                            />
                            <FieldAiActions
                              label={`Location ${idx + 1} Notes`}
                              compact
                              disabled={aiBusy}
                              busyAction={busyFor("locations", idx, "notes")}
                              onImprove={() => void handleAiCampaign("expand", "locations", idx, "notes")}
                              onRegen={() => void handleAiCampaign("scratch", "locations", idx, "notes")}
                            />
                            <HudButton
                              variant="ghost"
                              size="xs"
                              onClick={() => setLocations((p) => p.filter((_, i) => i !== idx))}
                              aria-label={`Remove Location ${idx + 1}`}
                              className="px-1 text-[var(--hud-muted)] hover:text-[var(--hud-primary-bright)]"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </HudButton>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                  {/* Starting Discoveries */}
                  {discoveryPairs.length > 0 && (
                    <div className="space-y-1.5">
                      <div className="font-cyber-ui text-[10px] font-semibold uppercase tracking-wider text-[var(--hud-label)]">
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
                              className="w-36 border border-[var(--hud-line)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
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
                              className="min-w-0 flex-1 border border-[var(--hud-line)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
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
                          <HudButton
                            variant="ghost"
                            size="xs"
                            onClick={() => setDiscoveryPairs((p) => p.filter((_, i) => i !== idx))}
                            aria-label={`Remove Discovery ${idx + 1}`}
                            className="px-1 text-[var(--hud-muted)] hover:text-[var(--hud-primary-bright)]"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </HudButton>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* GM Secrets (Spoiler-Shielded) + Opening World Clocks (Collapsible) */}
            <div className="space-y-2.5 border border-[var(--hud-line-soft)] bg-[var(--hud-row)] p-3">
              <button
                type="button"
                onClick={() => setShowSecretsClocks((v) => !v)}
                className="flex w-full items-center justify-between font-cyber-display text-xs font-semibold uppercase tracking-wider text-[var(--hud-text)] hover:text-[var(--hud-accent)]"
              >
                <span className="inline-flex items-center gap-1.5">
                  <Clock className="h-3.5 w-3.5 text-[var(--hud-primary-bright)]" />
                  GM Secrets &amp; Opening Clocks
                </span>
                <span className="font-cyber-data text-[10px] text-[var(--hud-accent)]">
                  {showSecretsClocks ? "▲ Hide" : "▼ Expand"}
                </span>
              </button>
              {showSecretsClocks && (
                <div className="grid grid-cols-1 gap-3 border-t border-[var(--hud-line-soft)] pt-2.5 sm:grid-cols-2">
                  <div className="space-y-2 border border-[var(--hud-warn)]/45 bg-[var(--hud-panel)] p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="flex items-center gap-1.5 font-cyber-ui text-xs font-semibold text-[var(--hud-warn)]">
                        {revealGmSecrets ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />}
                        <span>Hidden GM Secrets</span>
                      </span>
                      <label className="inline-flex cursor-pointer items-center gap-1.5 font-cyber-ui text-[10px] font-semibold text-[var(--hud-warn)]">
                        <span>Unspoil</span>
                        <HudToggle
                          as="checkbox"
                          checked={revealGmSecrets}
                          onCheckedChange={setRevealGmSecrets}
                          aria-label="Unspoil GM Secrets"
                          className="min-w-12 py-0.5 text-[10px]"
                        />
                      </label>
                    </div>
                    {revealGmSecrets ? (
                      <div className="space-y-2">
                        <div className="space-y-1">
                          <div className="flex items-center justify-between gap-1">
                            <span className="font-cyber-ui text-[10px] font-semibold uppercase tracking-wider text-[var(--hud-warn)]">
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
                            className="w-full border border-[var(--hud-line)] bg-black/60 px-2.5 py-1.5 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
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
                                className="w-28 border border-[var(--hud-line)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
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
                                className="min-w-0 flex-1 border border-[var(--hud-line)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
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
                            <HudButton
                              variant="ghost"
                              size="xs"
                              onClick={() => setSecretPairs((p) => p.filter((_, i) => i !== idx))}
                              aria-label={`Remove Secret ${idx + 1}`}
                              className="px-1 text-[var(--hud-muted)] hover:text-[var(--hud-primary-bright)]"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </HudButton>
                          </div>
                        ))}
                        <HudButton
                          variant="tactical"
                          size="xs"
                          onClick={() => setSecretPairs((p) => [...p, { key: "", val: "" }])}
                          className="border-[var(--hud-warn)]/60 text-[var(--hud-warn)]"
                        >
                          <Plus className="h-3 w-3" /> Add Secret Entry
                        </HudButton>
                      </div>
                    ) : (
                      <div className="cyber-hazard-thin flex flex-col items-center justify-center border border-[var(--hud-warn)]/60 bg-black/60 px-3 py-4 text-center">
                        <HazardBadge tone="warn">
                          CLASSIFIED // SPOILER SHIELDED
                        </HazardBadge>
                        <span className="mt-1.5 font-cyber-ui text-[11px] text-[var(--hud-muted)]">
                          {gmSecrets.trim() || secretPairs.length > 0
                            ? "GM secrets are stored privately. Check Unspoil to reveal or edit."
                            : "Empty — AI can generate hidden twists. Check Unspoil to write or view."}
                        </span>
                      </div>
                    )}
                  </div>

                  <div className="space-y-2 border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] p-3">
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-1.5 font-cyber-ui text-xs font-semibold text-[var(--hud-text)]">
                        <Clock className="h-3.5 w-3.5 text-[var(--hud-primary-bright)]" /> Opening World / Heat Clock
                      </div>
                      <HudButton
                        variant="tactical"
                        size="xs"
                        onClick={() =>
                          setExtraClocks((p) => [
                            ...p,
                            { name: "", segments: 4, filled: 0, category: "deadline", visibility: "public", note: "" },
                          ])
                        }
                      >
                        <Plus className="h-3 w-3 text-[var(--hud-primary-bright)]" /> Clock
                      </HudButton>
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <div className="flex min-w-[140px] flex-1 items-center gap-1">
                        <input
                          type="text"
                          value={clockName}
                          onChange={(e) => setClockName(e.target.value)}
                          placeholder="Clock name (e.g. Corp Trace)"
                          className="min-w-0 flex-1 border border-[var(--hud-line)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
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
                        className="w-14 border border-[var(--hud-line)] bg-black/60 px-2 py-1 font-cyber-data text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                      />
                      <input
                        type="number"
                        min={0}
                        max={clockSegments}
                        aria-label="Primary clock filled"
                        title="Initial filled segments"
                        value={clockFilled}
                        onChange={(e) =>
                          setClockFilled(Math.max(0, Math.min(clockSegments, parseInt(e.target.value, 10) || 0)))
                        }
                        className="w-14 border border-[var(--hud-line)] bg-black/60 px-2 py-1 font-cyber-data text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                      />
                    </div>
                    <div className="space-y-1 border border-[var(--hud-line-soft)] bg-black/45 px-2.5 py-1.5">
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate font-cyber-ui text-[11px] font-semibold text-[var(--hud-label)]">
                          {clockName.trim() || "Clock Preview"}
                        </span>
                        <div className="flex items-center gap-1.5">
                          {clockVisibility === "secret" && <HazardBadge tone="warn">SECRET</HazardBadge>}
                          <span className="font-cyber-data text-[11px] text-[var(--hud-warn)]">
                            {clockFilled}/{clockSegments}
                          </span>
                        </div>
                      </div>
                      <SegmentedBar
                        value={clockFilled}
                        max={clockSegments}
                        segments={clockSegments}
                        tone={clockFilled >= clockSegments ? "primary" : "warn"}
                      />
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <select
                        aria-label="Primary clock category"
                        value={clockCategory}
                        onChange={(e) => setClockCategory(e.target.value as ExtraClockDraft["category"])}
                        className="border border-[var(--hud-line)] bg-black/60 px-2 py-1 font-cyber-ui text-[11px] text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                      >
                        {["heat", "obligation", "deadline", "faction", "recovery"].map((c) => (
                          <option key={c} value={c}>{c}</option>
                        ))}
                      </select>
                      <select
                        aria-label="Primary clock visibility"
                        value={clockVisibility}
                        onChange={(e) => setClockVisibility(e.target.value as "public" | "secret")}
                        className="border border-[var(--hud-line)] bg-black/60 px-2 py-1 font-cyber-ui text-[11px] text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
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
                          className="min-w-0 flex-1 border border-[var(--hud-line)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
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
                      <div key={idx} className="space-y-1.5 border-t border-[var(--hud-line-soft)] pt-2">
                        <div className="flex gap-1.5">
                          <input
                            type="text"
                            value={ec.name}
                            onChange={(e) =>
                              setExtraClocks((p) => p.map((x, i) => (i === idx ? { ...x, name: e.target.value } : x)))
                            }
                            placeholder="Additional clock name"
                            className="flex-1 border border-[var(--hud-line)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
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
                            className="w-14 border border-[var(--hud-line)] bg-black/60 px-2 py-1 font-cyber-data text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                          />
                          <select
                            value={ec.visibility}
                            onChange={(e) =>
                              setExtraClocks((p) =>
                                p.map((x, i) =>
                                  i === idx ? { ...x, visibility: e.target.value as "public" | "secret" } : x,
                                ),
                              )
                            }
                            className="border border-[var(--hud-line)] bg-black/60 px-1.5 py-1 font-cyber-ui text-[10px] text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                          >
                            <option value="public">Public</option>
                            <option value="secret">Secret</option>
                          </select>
                          <HudButton
                            variant="ghost"
                            size="xs"
                            onClick={() => setExtraClocks((p) => p.filter((_, i) => i !== idx))}
                            aria-label={`Remove Extra Clock ${idx + 1}`}
                            className="px-1 text-[var(--hud-muted)] hover:text-[var(--hud-primary-bright)]"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </HudButton>
                        </div>
                        <SegmentedBar
                          value={ec.filled}
                          max={ec.segments}
                          segments={ec.segments}
                          tone={ec.filled >= ec.segments ? "primary" : "warn"}
                        />
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
                            className="border border-[var(--hud-line)] bg-black/60 px-1.5 py-0.5 font-cyber-ui text-[10px] text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
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
                            className="flex-1 border border-[var(--hud-line)] bg-black/60 px-2 py-0.5 font-cyber-ui text-[11px] text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Session Zero & Table Dials + Starting Party */}
            <div className="space-y-2.5 border border-[var(--hud-line-soft)] bg-[var(--hud-row)] p-3">
              <button
                type="button"
                onClick={() => setShowSessionZero((v) => !v)}
                className="flex w-full items-center justify-between font-cyber-display text-xs font-semibold uppercase tracking-wider text-[var(--hud-text)] hover:text-[var(--hud-accent)]"
              >
                <span className="inline-flex items-center gap-1.5">
                  <ShieldAlert className="h-3.5 w-3.5 text-[var(--hud-accent)]" />
                  Session Zero Dials, Starting Time &amp; Table Boundaries
                </span>
                <span className="font-cyber-data text-[10px] text-[var(--hud-accent)]">
                  {showSessionZero ? "▲ Hide" : "▼ Expand"}
                </span>
              </button>
              {showSessionZero && (
                <div className="space-y-3 border-t border-[var(--hud-line-soft)] pt-2.5">
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                    <div>
                      <label className="mb-1 block font-cyber-ui text-[10px] font-semibold uppercase tracking-wider text-[var(--hud-label)]">
                        GM Tone Override
                      </label>
                      <select
                        aria-label="Session Zero GM Style"
                        value={szGmStyle}
                        onChange={(e) => setSzGmStyle(e.target.value)}
                        className="w-full border border-[var(--hud-line)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
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
                      <label className="mb-1 block font-cyber-ui text-[10px] font-semibold uppercase tracking-wider text-[var(--hud-label)]">
                        Reply Length
                      </label>
                      <select
                        aria-label="Session Zero Reply Length"
                        value={szNarratorLength}
                        onChange={(e) => setSzNarratorLength(e.target.value)}
                        className="w-full border border-[var(--hud-line)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
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
                      <label className="mb-1 block font-cyber-ui text-[10px] font-semibold uppercase tracking-wider text-[var(--hud-label)]">
                        Pacing
                      </label>
                      <select
                        aria-label="Session Zero Pacing"
                        value={szNarratorPacing}
                        onChange={(e) => setSzNarratorPacing(e.target.value)}
                        className="w-full border border-[var(--hud-line)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
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
                      <label className="mb-1 block font-cyber-ui text-[10px] font-semibold uppercase tracking-wider text-[var(--hud-label)]">
                        Lethality Dial
                      </label>
                      <select
                        aria-label="Lethality Dial"
                        value={szLethality}
                        onChange={(e) => setSzLethality(e.target.value)}
                        className="w-full border border-[var(--hud-line)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                      >
                        <option value="Standard RED">Standard RED</option>
                        <option value="Gritty / High Lethality">Gritty / High Lethality</option>
                        <option value="Cinematic Action">Cinematic Action</option>
                      </select>
                    </div>
                    <div>
                      <label className="mb-1 block font-cyber-ui text-[10px] font-semibold uppercase tracking-wider text-[var(--hud-label)]">
                        Economy Dial
                      </label>
                      <select
                        aria-label="Economy Dial"
                        value={szEconomy}
                        onChange={(e) => setSzEconomy(e.target.value)}
                        className="w-full border border-[var(--hud-line)] bg-black/60 px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                      >
                        <option value="Raw Scarcity">Raw Scarcity (Time of the Red)</option>
                        <option value="Standard RED">Standard RED (500–2,000 eb gigs)</option>
                        <option value="High-Roller">High-Roller Contracts</option>
                      </select>
                    </div>
                    <div>
                      <label className="mb-1 block font-cyber-ui text-[10px] font-semibold uppercase tracking-wider text-[var(--hud-label)]">
                        Campaign Scope &amp; Time
                      </label>
                      <div className="flex gap-1.5">
                        <select
                          aria-label="Campaign Scope"
                          value={szScope}
                          onChange={(e) => setSzScope(e.target.value)}
                          className="w-1/2 border border-[var(--hud-line)] bg-black/60 px-1.5 py-1 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
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
                          className="w-1/2 border border-[var(--hud-line)] bg-black/60 px-1.5 py-1 font-cyber-data text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none disabled:opacity-50"
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
                      className="border border-[var(--hud-line)] bg-black/60 px-2.5 py-1.5 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
                    />
                    <input
                      type="text"
                      value={szLinesVeils}
                      onChange={(e) => setSzLinesVeils(e.target.value)}
                      placeholder="Lines & Veils / Safety Boundaries (topics off-limits for GM)"
                      className="border border-[var(--hud-line)] bg-black/60 px-2.5 py-1.5 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
                    />
                  </div>
                  {!editCampaign && (
                    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[var(--hud-line-soft)] pt-2">
                      <div className="flex flex-wrap items-center gap-2 text-xs">
                        {unattachedChars.length > 0 && (
                          <>
                            <span className="font-cyber-ui text-[11px] font-semibold text-[var(--hud-text)]">
                              Attach Starting PCs:
                            </span>
                            {unattachedChars.map((ch) => {
                              const checked = attachCharIds.includes(ch.id);
                              return (
                                <label
                                  key={ch.id}
                                  className={`inline-flex cursor-pointer items-center gap-1 border px-2 py-0.5 font-cyber-ui text-[11px] transition ${
                                    checked
                                      ? "border-[var(--hud-accent-line)] bg-[var(--hud-accent-navy)] text-[var(--hud-accent)]"
                                      : "border-[var(--hud-line-soft)] bg-black/50 text-[var(--hud-text)]"
                                  }`}
                                >
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
                      <label className="inline-flex cursor-pointer items-center gap-2 font-cyber-ui text-[11px] font-semibold text-[var(--hud-accent)]">
                        <HudToggle
                          as="checkbox"
                          checked={launchIntroOnCreate}
                          onCheckedChange={setLaunchIntroOnCreate}
                          className="min-w-12 py-0.5 text-[10px]"
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
          <div className="flex items-center justify-between border-t border-[var(--hud-line)] bg-[#5a0b1c]/25 px-5 py-3">
            <span className="font-cyber-ui text-[11px] text-[var(--hud-muted)]">
              Closing preserves your draft automatically until saved or reset.
            </span>
            <div className="flex items-center gap-2">
              <HudButton variant="ghost" size="md" onClick={onClose}>
                Cancel
              </HudButton>
              <HudButton
                type="submit"
                variant="cta"
                size="md"
                disabled={busy || !name.trim()}
              >
                {busy
                  ? editCampaign
                    ? "Updating…"
                    : "Creating…"
                  : editCampaign
                    ? "Apply Architect Updates"
                    : "Create Campaign"}
              </HudButton>
            </div>
          </div>
        </form>
      </CyberFrame>
    </div>
  );
}
