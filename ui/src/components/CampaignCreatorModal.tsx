import { useEffect, useState } from "react";
import {
  Clock,
  Compass,
  Dices,
  EyeOff,
  MapPin,
  Plus,
  ShieldAlert,
  Sparkles,
  Target,
  Trash2,
  Users,
  Wand2,
  X,
} from "lucide-react";
import {
  assistCharacterCreation,
  bootstrapCampaign,
  createCampaign,
  fetchCreationReference,
  type CampaignBootstrapPayload,
} from "../api";
import type { CampaignPresets, CampaignRecord } from "../types";

interface CampaignCreatorModalProps {
  open: boolean;
  editCampaign?: CampaignRecord | null;
  onClose: () => void;
  onCreated: (campaignId: string, name: string) => Promise<void>;
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
      name: "Rebuilding Urban Center",
      zone_type: "Rebuilding Urban Center",
      threat_rating: "Corporate",
      printed_page: 299,
      summary: "Surviving metropolitan sector under relentless Corporate reconstruction, featuring City Hall, corporate plazas, and mega-construction.",
    },
    {
      name: "Watson Development",
      zone_type: "Rebuilding Urban Center",
      threat_rating: "Moderate",
      printed_page: 301,
      summary: "Densely packed sprawl housing Little China, Kabuki markets, rising megabuildings, and diverse immigrant communities.",
    },
    {
      name: "Old Combat Zone",
      zone_type: "Combat Zone",
      threat_rating: "Combat",
      printed_page: 301,
      summary: "Lawless urban combat sector long abandoned to boostergangs and cyberpsychos with zero NCPD presence.",
    },
    {
      name: "Heywood",
      zone_type: "Overpacked Suburbs",
      threat_rating: "Moderate",
      printed_page: 302,
      summary: "Vast overpacked residential sprawl divided into wealthier northern blocks and refugee-crowded Santo Domingo container camps.",
    },
    {
      name: "New Westbrook",
      zone_type: "Overpacked Suburbs",
      threat_rating: "Moderate",
      printed_page: 302,
      summary: "Glitz-and-glam suburb built among former executive ruins, housing displaced citizens alongside Network 54 studios.",
    },
    {
      name: "Pacifica Playground",
      zone_type: "Rebuilding Urban Center",
      threat_rating: "Moderate",
      printed_page: 300,
      summary: "Corporate-backed coastal vacation and amusement district built around the active Playland by the Sea resort complex.",
    },
    {
      name: "Executive Zone (Beaverville)",
      zone_type: "Executive Zone",
      threat_rating: "Executive",
      printed_page: 300,
      summary: "Gated and heavily guarded enclave in the hills with luxury mansions, private spas, and round-the-clock Lazarus security.",
    },
    {
      name: "The Open Road / Badlands",
      zone_type: "Open Road",
      threat_rating: "Outskirts",
      printed_page: 303,
      summary: "Wide red-dust desert highways connecting to regional hubs, patrolled by Nomad convoys and threatened by gogangs.",
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

export function CampaignCreatorModal({
  open,
  editCampaign,
  onClose,
  onCreated,
  onUpdated,
  onNotify,
}: CampaignCreatorModalProps) {
  const [presets, setPresets] = useState<CampaignPresets>(FALLBACK_PRESETS);
  const [name, setName] = useState("");
  const [district, setDistrict] = useState("Watson Development");
  const [caperStyle, setCaperStyle] = useState("Corporate Data / Cargo Heist");
  const [selectedFactions, setSelectedFactions] = useState<string[]>(["Arasaka", "Tyger Claws"]);
  const [screamsheetHook, setScreamsheetHook] = useState("");
  const [summary, setSummary] = useState("");
  const [openingScene, setOpeningScene] = useState("");
  const [beatHook, setBeatHook] = useState("");
  const [beatDev, setBeatDev] = useState("");
  const [beatCliff, setBeatCliff] = useState("");
  const [beatClimax, setBeatClimax] = useState("");
  const [beatRes, setBeatRes] = useState("");
  const [npcPairs, setNpcPairs] = useState<Array<{ key: string; val: string }>>([]);
  const [objectivePairs, setObjectivePairs] = useState<Array<{ key: string; val: string }>>([]);
  const [gmSecrets, setGmSecrets] = useState("");
  const [clockName, setClockName] = useState("");
  const [clockSegments, setClockSegments] = useState(4);
  const [clockNote, setClockNote] = useState("");
  const [aiGuidance, setAiGuidance] = useState("");
  const [aiBusyField, setAiBusyField] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    if (editCampaign) {
      setName(editCampaign.name);
      setSummary(editCampaign.state.summary || "");
      setOpeningScene(editCampaign.state.scene || "");
      setNpcPairs(Object.entries(editCampaign.state.npcs ?? {}).map(([key, val]) => ({ key, val })));
      setObjectivePairs(Object.entries(editCampaign.state.objectives ?? {}).map(([key, val]) => ({ key, val })));
      const beatStr = editCampaign.state.unresolved?.["Beat Chart"] || "";
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
      setClockName("");
      setClockNote("");
    } else {
      setName("");
      setSummary("");
      setOpeningScene("");
      setBeatHook("");
      setBeatDev("");
      setBeatCliff("");
      setBeatClimax("");
      setBeatRes("");
      setNpcPairs([]);
      setObjectivePairs([]);
      setGmSecrets("");
      setClockName("");
      setClockNote("");
    }
    setError("");
  }, [open, editCampaign?.id]);

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
        // Fallback presets work seamlessly offline/in tests
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

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
    const hookLine = screamsheetHook || pickOne(presets.screamsheet_hooks);
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

  const handleAiCampaign = async (mode: "scratch" | "expand", field?: string) => {
    if (aiBusy) return;
    setError("");
    const busyKey = field ? `expand:${field}` : mode;
    setAiBusyField(busyKey);
    try {
      const npcsMap = Object.fromEntries(
        npcPairs.filter((p) => p.key.trim() && p.val.trim()).map((p) => [p.key.trim(), p.val.trim()]),
      );
      const objMap = Object.fromEntries(
        objectivePairs.filter((p) => p.key.trim() && p.val.trim()).map((p) => [p.key.trim(), p.val.trim()]),
      );
      const res = await assistCharacterCreation({
        target: "campaign",
        mode,
        ...(field ? { field } : {}),
        guidance: aiGuidance.trim() || undefined,
        campaign: {
          name: name.trim() || undefined,
          district,
          threat_rating: activeDistrict?.threat_rating,
          caper_style: caperStyle,
          factions: selectedFactions,
          screamsheet_hook: screamsheetHook || undefined,
        },
        current: {
          name: name.trim() || undefined,
          summary: summary.trim() || undefined,
          opening_scene: openingScene.trim() || undefined,
          gm_secrets: gmSecrets.trim() || undefined,
          beats: {
            hook: beatHook,
            developments: beatDev,
            cliffhanger: beatCliff,
            climax: beatClimax,
            resolution: beatRes,
          },
          npcs: npcsMap,
          objectives: objMap,
          opening_clock: clockName.trim()
            ? { name: clockName.trim(), segments: clockSegments, note: clockNote.trim() }
            : undefined,
        },
      });
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
      if ((!field || field === "gm_secrets") && res.gm_secrets) setGmSecrets(res.gm_secrets);
      if ((!field || field === "opening_clock") && res.opening_clock?.name) {
        setClockName(res.opening_clock.name);
        setClockSegments(res.opening_clock.segments || 4);
        setClockNote(res.opening_clock.note || "");
      }
      onNotify(
        mode === "scratch"
          ? "AI generated full Night City campaign premise, Beat Chart & GM secrets."
          : `AI improved ${field ? field.replace(/^beat_/, "").replace(/_/g, " ") : "campaign notes"}.`,
      );
    } catch (err) {
      const msg = err instanceof Error ? err.message : "AI campaign assist failed";
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
      const beatLines = [
        beatHook.trim() ? `Hook: ${beatHook.trim()}` : "",
        beatDev.trim() ? `Developments: ${beatDev.trim()}` : "",
        beatCliff.trim() ? `Cliffhanger: ${beatCliff.trim()}` : "",
        beatClimax.trim() ? `Climax: ${beatClimax.trim()}` : "",
        beatRes.trim() ? `Resolution: ${beatRes.trim()}` : "",
      ].filter(Boolean);
      const hasWorldData =
        summary.trim() ||
        openingScene.trim() ||
        Object.keys(npcs).length > 0 ||
        Object.keys(objectives).length > 0 ||
        beatLines.length > 0 ||
        gmSecrets.trim() ||
        clockName.trim();

      if (hasWorldData) {
        const payload: CampaignBootstrapPayload = {
          ...(summary.trim() ? { summary: summary.trim() } : {}),
          ...(openingScene.trim() ? { scene: openingScene.trim() } : {}),
          ...(Object.keys(npcs).length > 0 ? { npcs } : {}),
          ...(Object.keys(objectives).length > 0 ? { objectives } : {}),
          ...(beatLines.length > 0
            ? {
                unresolved: {
                  "Beat Chart": beatLines.join(" | "),
                  ...(district
                    ? {
                        "District & Threat": `${district}${activeDistrict?.zone_type ? ` [${activeDistrict.zone_type}]` : ""} (${activeDistrict?.threat_rating ?? "Moderate"})`,
                      }
                    : {}),
                },
              }
            : {}),
          ...(gmSecrets.trim() ? { gm_secrets: gmSecrets.trim() } : {}),
          ...(clockName.trim()
            ? { opening_clock: { name: clockName.trim(), segments: clockSegments, note: clockNote.trim() } }
            : {}),
        };
        await bootstrapCampaign(targetCampaign.id, payload);
      }

      if (editCampaign && onUpdated) {
        await onUpdated(targetCampaign.id, targetCampaign.name);
      } else {
        await onCreated(targetCampaign.id, targetCampaign.name);
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

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/85 p-3 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="Campaign Creator"
    >
      <form
        onSubmit={handleSubmit}
        className="flex max-h-[92vh] w-full max-w-5xl flex-col overflow-hidden rounded-xl border border-slate-700/80 bg-[#0b0f19] shadow-2xl"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-800 bg-[#0e1424] px-5 py-3">
          <div className="flex items-center gap-2.5">
            <Compass className="h-5 w-5 text-cyan-400" />
            <div>
              <h2 className="text-sm font-bold tracking-wide text-slate-100 uppercase">
                Corebook Campaign Architect (Night City 2045)
              </h2>
              <p className="text-[11px] text-slate-400">
                Set district threat, active factions, Screamsheet hook, Beat Chart (pp. 395–408), and hidden GM truths.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close Campaign Creator"
            className="rounded-md p-1.5 text-slate-400 hover:bg-slate-800 hover:text-slate-100"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {/* Quick AI / Scaffold Bar */}
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-cyan-500/30 bg-cyan-950/15 p-3">
            <div>
              <div className="text-xs font-bold text-cyan-200">Quick World Builder or AI Co-Architect</div>
              <p className="text-[11px] text-slate-300">
                Fill just the Campaign Name for a blank sandbox, or build a full Corebook gig with Beat Chart &amp; GM Secrets.
              </p>
            </div>
            <div className="flex flex-wrap gap-1.5">
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
                <Sparkles className="h-3 w-3" /> {aiBusyField === "scratch" ? "Architecting…" : "AI Generate from Scratch"}
              </button>
            </div>
          </div>

          {error && (
            <div className="rounded border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {error}
            </div>
          )}

          {/* Row 1: Title + Guidance */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <div className="mb-1 flex items-center justify-between gap-2">
                <label className="block text-xs font-semibold text-slate-200">
                  Campaign Title *
                </label>
                <button
                  type="button"
                  disabled={aiBusy}
                  onClick={() => void handleAiCampaign("expand", "name")}
                  className="inline-flex items-center gap-1 rounded border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold text-amber-200 hover:bg-amber-500/20 disabled:opacity-50"
                >
                  <Wand2 className="h-2.5 w-2.5" />
                  {aiBusyField === "expand:name" ? "Improving…" : "AI Improve"}
                </button>
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
                Optional AI Direction / Theme Prompt
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
            <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3 space-y-2">
              <label className="flex items-center justify-between text-xs font-semibold text-slate-200">
                <span className="inline-flex items-center gap-1.5">
                  <MapPin className="h-3.5 w-3.5 text-rose-400" /> Starting District (pp. 298–317)
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
                    {d.name} ({d.zone_type ? `${d.zone_type} · ` : ""}{d.threat_rating} · p.{d.printed_page})
                  </option>
                ))}
              </select>
              {activeDistrict && (
                <p className="text-[11px] text-slate-400">{activeDistrict.summary}</p>
              )}
            </div>

            <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3 space-y-2">
              <label className="flex items-center gap-1.5 text-xs font-semibold text-slate-200">
                <Target className="h-3.5 w-3.5 text-cyan-400" /> Campaign / Caper Style (pp. 393–405)
              </label>
              <select
                value={caperStyle}
                onChange={(e) => setCaperStyle(e.target.value)}
                className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100"
              >
                {presets.caper_styles.map((s) => (
                  <option key={s.id} value={s.name}>
                    {s.name} (p.{s.printed_page})
                  </option>
                ))}
              </select>
              {activeStyle && <p className="text-[11px] text-slate-400">{activeStyle.summary}</p>}
            </div>
          </div>

          {/* Factions & Screamsheet Hook */}
          <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs font-semibold text-slate-200">
                Active Power Players &amp; Factions (up to 4)
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
                    title={`${fac.type} (p.${fac.printed_page}): ${fac.summary}`}
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
              placeholder="Optional Screamsheet broadcast headline or rumor hitting Night City Nets today…"
              className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100"
            />
          </div>

          {/* Premise & Opening Scene */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <div className="mb-1 flex items-center justify-between gap-2">
                <label className="block text-xs font-semibold text-slate-200">
                  Campaign Premise &amp; Central Conflict
                </label>
                <button
                  type="button"
                  disabled={aiBusy}
                  onClick={() => void handleAiCampaign("expand", "summary")}
                  className="inline-flex items-center gap-1 rounded border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold text-amber-200 hover:bg-amber-500/20 disabled:opacity-50"
                >
                  <Wand2 className="h-2.5 w-2.5" />
                  {aiBusyField === "expand:summary" ? "Improving…" : "AI Expand / Improve"}
                </button>
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
                <button
                  type="button"
                  disabled={aiBusy}
                  onClick={() => void handleAiCampaign("expand", "opening_scene")}
                  className="inline-flex items-center gap-1 rounded border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold text-amber-200 hover:bg-amber-500/20 disabled:opacity-50"
                >
                  <Wand2 className="h-2.5 w-2.5" />
                  {aiBusyField === "expand:opening_scene" ? "Improving…" : "AI Expand / Improve"}
                </button>
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

          {/* Corebook Beat Chart (pp. 395-408) */}
          <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3 space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-200">
                <ShieldAlert className="h-3.5 w-3.5 text-amber-400" />
                Corebook Beat Chart Outline (pp. 395–408 · Optional)
              </div>
              <button
                type="button"
                disabled={aiBusy}
                onClick={() => void handleAiCampaign("expand", "beat_chart")}
                className="inline-flex items-center gap-1 rounded border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold text-amber-200 hover:bg-amber-500/20 disabled:opacity-50"
              >
                <Wand2 className="h-2.5 w-2.5" />
                {aiBusyField === "expand:beat_chart" ? "Improving…" : "AI Expand Beats"}
              </button>
            </div>
            <p className="text-[11px] text-amber-200/80">
              Corebook Beat Chart (pp. 395–408): alternate Action, Investigation, and Character-Interaction beats.
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
                    <button
                      type="button"
                      disabled={aiBusy}
                      onClick={() => void handleAiCampaign("expand", fieldKey)}
                      title={`AI improve ${label}`}
                      aria-label={`AI improve ${label}`}
                      className="inline-flex items-center gap-0.5 text-[10px] text-amber-300/90 hover:text-amber-200 disabled:opacity-40"
                    >
                      <Wand2 className="h-2.5 w-2.5" />
                      {aiBusyField === `expand:${fieldKey}` ? "…" : "Improve"}
                    </button>
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

          {/* Starting NPCs & Objectives */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3 space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-1.5">
                <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-200">
                  <Users className="h-3.5 w-3.5 text-cyan-400" /> Starting NPCs ({npcPairs.length})
                </span>
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    disabled={aiBusy}
                    onClick={() => void handleAiCampaign("expand", "npcs")}
                    className="inline-flex items-center gap-1 rounded border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold text-amber-200 hover:bg-amber-500/20 disabled:opacity-50"
                  >
                    <Wand2 className="h-2.5 w-2.5" />
                    {aiBusyField === "expand:npcs" ? "Improving…" : "AI Improve"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setNpcPairs((p) => [...p, { key: "", val: "" }])}
                    className="inline-flex items-center gap-1 rounded border border-slate-700 bg-slate-950 px-2 py-0.5 text-[11px] text-cyan-300"
                  >
                    <Plus className="h-3 w-3" /> Add NPC
                  </button>
                </div>
              </div>
              {npcPairs.map((item, idx) => (
                <div key={idx} className="flex gap-1.5">
                  <input
                    type="text"
                    value={item.key}
                    onChange={(e) =>
                      setNpcPairs((p) => p.map((x, i) => (i === idx ? { ...x, key: e.target.value } : x)))
                    }
                    placeholder="NPC Name / Role"
                    className="w-36 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                  />
                  <input
                    type="text"
                    value={item.val}
                    onChange={(e) =>
                      setNpcPairs((p) => p.map((x, i) => (i === idx ? { ...x, val: e.target.value } : x)))
                    }
                    placeholder="Motive / tie to crew"
                    className="flex-1 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                  />
                  <button
                    type="button"
                    onClick={() => setNpcPairs((p) => p.filter((_, i) => i !== idx))}
                    className="text-slate-500 hover:text-rose-400"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>

            <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3 space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-1.5">
                <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-200">
                  <Target className="h-3.5 w-3.5 text-emerald-400" /> Starting Objectives ({objectivePairs.length})
                </span>
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    disabled={aiBusy}
                    onClick={() => void handleAiCampaign("expand", "objectives")}
                    className="inline-flex items-center gap-1 rounded border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold text-amber-200 hover:bg-amber-500/20 disabled:opacity-50"
                  >
                    <Wand2 className="h-2.5 w-2.5" />
                    {aiBusyField === "expand:objectives" ? "Improving…" : "AI Improve"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setObjectivePairs((p) => [...p, { key: "", val: "" }])}
                    className="inline-flex items-center gap-1 rounded border border-slate-700 bg-slate-950 px-2 py-0.5 text-[11px] text-emerald-300"
                  >
                    <Plus className="h-3 w-3" /> Add Objective
                  </button>
                </div>
              </div>
              {objectivePairs.map((item, idx) => (
                <div key={idx} className="flex gap-1.5">
                  <input
                    type="text"
                    value={item.key}
                    onChange={(e) =>
                      setObjectivePairs((p) => p.map((x, i) => (i === idx ? { ...x, key: e.target.value } : x)))
                    }
                    placeholder="Objective"
                    className="w-36 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                  />
                  <input
                    type="text"
                    value={item.val}
                    onChange={(e) =>
                      setObjectivePairs((p) => p.map((x, i) => (i === idx ? { ...x, val: e.target.value } : x)))
                    }
                    placeholder="Details"
                    className="flex-1 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                  />
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

          {/* GM Secrets + Opening World Clock */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="rounded-lg border border-amber-500/30 bg-amber-950/10 p-3 space-y-1.5">
              <div className="flex items-center justify-between gap-2">
                <label className="flex items-center gap-1.5 text-xs font-semibold text-amber-200">
                  <EyeOff className="h-3.5 w-3.5" /> Hidden GM Secrets (Private to AI GM)
                </label>
                <button
                  type="button"
                  disabled={aiBusy}
                  onClick={() => void handleAiCampaign("expand", "gm_secrets")}
                  className="inline-flex items-center gap-1 rounded border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold text-amber-200 hover:bg-amber-500/20 disabled:opacity-50"
                >
                  <Wand2 className="h-2.5 w-2.5" />
                  {aiBusyField === "expand:gm_secrets" ? "Improving…" : "AI Expand / Improve"}
                </button>
              </div>
              <textarea
                rows={2}
                value={gmSecrets}
                onChange={(e) => setGmSecrets(e.target.value)}
                placeholder="Secret corporate betrayals, hidden employers, or traps kept out of player view…"
                className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100"
              />
            </div>

            <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3 space-y-2">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-200">
                  <Clock className="h-3.5 w-3.5 text-rose-400" /> Opening World / Heat Clock (Optional)
                </div>
                <button
                  type="button"
                  disabled={aiBusy}
                  onClick={() => void handleAiCampaign("expand", "opening_clock")}
                  className="inline-flex items-center gap-1 rounded border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold text-amber-200 hover:bg-amber-500/20 disabled:opacity-50"
                >
                  <Wand2 className="h-2.5 w-2.5" />
                  {aiBusyField === "expand:opening_clock" ? "Improving…" : "AI Improve"}
                </button>
              </div>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={clockName}
                  onChange={(e) => setClockName(e.target.value)}
                  placeholder="Clock name (e.g. Corp Trace)"
                  className="flex-1 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                />
                <input
                  type="number"
                  min={2}
                  max={12}
                  value={clockSegments}
                  onChange={(e) => setClockSegments(Math.max(2, Math.min(12, parseInt(e.target.value, 10) || 4)))}
                  className="w-16 rounded border border-slate-700 bg-slate-950 px-2 py-1 font-mono text-xs text-slate-100"
                />
              </div>
              <input
                type="text"
                value={clockNote}
                onChange={(e) => setClockNote(e.target.value)}
                placeholder="What happens when the clock fills…"
                className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
              />
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-slate-800 bg-[#0e1424] px-5 py-3">
          <span className="text-[11px] text-slate-400">
            Creates campaign cleanly and initializes District, Beat Chart, GM Secrets &amp; Opening Clock.
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
