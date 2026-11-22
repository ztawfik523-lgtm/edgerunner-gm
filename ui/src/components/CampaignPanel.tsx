import { useEffect, useState } from "react";
import {
  BookOpen,
  Clock,
  Compass,
  Cpu,
  Download,
  Eye,
  EyeOff,
  ImagePlus,
  MapPin,
  Minus,
  Plus,
  RotateCcw,
  Save,
  Sparkles,
  Star,
  Swords,
  Target,
  Trash2,
  Users,
} from "lucide-react";
import {
  assistCharacterCreation,
  fetchCampaignClocks,
  mutateCampaignClock,
  saveCampaignBanner,
  undoCampaignChange,
  updateCampaignState,
  updateNpcIdentity,
  updatePartyLocation,
} from "../api";
import type { CampaignContext, CampaignNarrativeState, CampaignRecord, WorldClock } from "../types";
import { FieldAiActions } from "./FieldAiActions";

interface CampaignPanelProps {
  context: CampaignContext | null;
  campaigns?: CampaignRecord[];
  canManageCampaigns?: boolean;
  isAdmin?: boolean;
  currentUsername?: string | null;
  activeLeafId?: string | null;
  onSelectCampaign?: (id: string) => void;
  onSetPrimaryCampaign?: (id: string) => Promise<void>;
  onDeleteCampaign?: (id: string) => Promise<void>;
  onOpenNewCampaign?: () => void;
  onOpenEditCampaign?: () => void;
  onStartSession?: () => Promise<void>;
  onExportChat?: () => Promise<void>;
  onCompressMemory?: () => Promise<void>;
  compressingMemory?: boolean;
  onRefresh: () => Promise<void>;
  onNotify: (msg: string) => void;
}

type SectionKey = "npcs" | "objectives" | "discoveries" | "unresolved";
type CampaignSubTab = "briefing" | "rules";

const SECTION_LABELS: Array<{ key: SectionKey; title: string; placeholderKey: string; adminOnly?: boolean }> = [
  { key: "npcs", title: "NPCs & Contacts", placeholderKey: "Name (e.g. Rogue)" },
  { key: "objectives", title: "Active Objectives", placeholderKey: "Objective" },
  { key: "discoveries", title: "Discoveries & Clues", placeholderKey: "Clue" },
  { key: "unresolved", title: "Unresolved Threads", placeholderKey: "Thread", adminOnly: true },
];

const ROLES_OVERVIEW = [
  { name: "Solo", ability: "Combat Awareness", desc: "Tactical threat detection, precision damage, and initiative control." },
  { name: "Netrunner", ability: "Interface", desc: "Breach local NET architectures, crack Black ICE, and hijack control nodes." },
  { name: "Tech", ability: "Maker", desc: "Field-rig, upgrade, fabricate, and invent custom hardware & weapons." },
  { name: "Medtech", ability: "Medicine", desc: "Trauma surgery, combat pharmaceuticals (Speedheal/Stim), and cryotanks." },
  { name: "Rockerboy", ability: "Charismatic Impact", desc: "Sway crowds, fans, and street venues through raw rebel presence." },
  { name: "Media", ability: "Credibility", desc: "Uncover street rumors, break corporate coverups, and broadcast truth." },
  { name: "Exec", ability: "Teamwork", desc: "Corporate housing, business suit, and a loyal specialist team member." },
  { name: "Lawman", ability: "Backup", desc: "Call armed patrol or tactical response squads when under fire." },
  { name: "Fixer", ability: "Operator", desc: "Source scarce Night Market gear, haggle 10% margins, and work street contacts." },
  { name: "Nomad", ability: "Moto", desc: "Access the clan motorpool for armored groundcars, bikes, and combat upgrades." },
];

export function CampaignPanel({
  context,
  campaigns = [],
  canManageCampaigns = true,
  isAdmin = true,
  currentUsername = null,
  activeLeafId,
  onSelectCampaign,
  onSetPrimaryCampaign,
  onDeleteCampaign,
  onOpenNewCampaign,
  onOpenEditCampaign,
  onStartSession,
  onExportChat,
  onCompressMemory,
  compressingMemory,
  onRefresh,
  onNotify,
}: CampaignPanelProps) {
  const campaign = context?.campaign ?? null;
  const solo = context?.solo ?? null;

  const [subTab, setSubTab] = useState<CampaignSubTab>("briefing");
  const [scene, setScene] = useState(campaign?.state.scene ?? "");
  const [summary, setSummary] = useState(campaign?.state.summary ?? "");
  const contextBannerUrl = (context as { banner_url?: string } | null)?.banner_url ?? "";
  const [bannerUrl, setBannerUrl] = useState(
    contextBannerUrl ||
      campaign?.state.discoveries?.["__banner_url"] ||
      campaign?.state.discoveries?.["Banner URL"] ||
      "",
  );
  const [clocks, setClocks] = useState<WorldClock[]>([]);
  const [newClockName, setNewClockName] = useState("");
  const [newClockMax, setNewClockMax] = useState("4");
  const [newClockTrigger, setNewClockTrigger] = useState("");
  const [newClockVisibility, setNewClockVisibility] = useState<"public" | "secret">("public");
  const [draftKey, setDraftKey] = useState<Record<SectionKey, string>>({
    npcs: "",
    objectives: "",
    discoveries: "",
    unresolved: "",
  });
  const [draftVal, setDraftVal] = useState<Record<SectionKey, string>>({
    npcs: "",
    objectives: "",
    discoveries: "",
    unresolved: "",
  });
  const [confirmRemove, setConfirmRemove] = useState<{ section: SectionKey; key: string } | null>(null);
  const [confirmDeleteCampaignId, setConfirmDeleteCampaignId] = useState<string | null>(null);
  const [npcRealNameDraft, setNpcRealNameDraft] = useState("");
  const [npcRealHiddenDraft, setNpcRealHiddenDraft] = useState(true);
  const [pcLocDrafts, setPcLocDrafts] = useState<Record<string, string>>({});
  const [aiBusyMode, setAiBusyMode] = useState<"improve" | "regen" | null>(null);
  const [startingSession, setStartingSession] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [busy, setBusy] = useState(false);
  const aiBusy = aiBusyMode !== null;

  useEffect(() => {
    setScene(campaign?.state.scene ?? "");
    setSummary(campaign?.state.summary ?? "");
    setBannerUrl(
      contextBannerUrl ||
        campaign?.state.discoveries?.["__banner_url"] ||
        campaign?.state.discoveries?.["Banner URL"] ||
        "",
    );
    setConfirmRemove(null);
    const locs: Record<string, string> = {};
    for (const ch of context?.party_grouping?.characters ?? []) {
      locs[ch.id] = ch.location;
    }
    setPcLocDrafts(locs);
  }, [
    campaign?.id,
    campaign?.revision,
    campaign?.state.scene,
    campaign?.state.summary,
    campaign?.state.discoveries,
    context?.party_grouping,
  ]);

  useEffect(() => {
    if (!campaign) {
      setClocks([]);
      return;
    }
    let cancelled = false;
    fetchCampaignClocks(campaign.id, activeLeafId)
      .then((res) => {
        if (!cancelled) setClocks(res.clocks ?? []);
      })
      .catch(() => {
        if (!cancelled) setClocks([]);
      });
    return () => {
      cancelled = true;
    };
  }, [campaign?.id, campaign?.revision, activeLeafId, isAdmin]);

  const handleSaveText = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!campaign || !isAdmin || busy) return;
    setBusy(true);
    try {
      const nextDiscoveries = { ...(campaign.state.discoveries ?? {}) };
      delete nextDiscoveries["__banner_url"];
      await saveCampaignBanner(campaign.id, bannerUrl.trim());
      await updateCampaignState(
        campaign.id,
        campaign.revision,
        { scene, summary, discoveries: nextDiscoveries },
        "Update scene and summary",
      );
      await onRefresh();
      onNotify("Campaign notes saved.");
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Failed to save notes");
    } finally {
      setBusy(false);
    }
  };

  const handleBannerUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 2_000_000) {
      onNotify("Backdrop image must be under 2 MB.");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") {
        setBannerUrl(reader.result);
      }
    };
    reader.readAsDataURL(file);
  };

  const handleAddEntry = async (section: SectionKey) => {
    if (!campaign || !isAdmin) return;
    const key = draftKey[section].trim();
    const val = draftVal[section].trim();
    if (!key || !val || busy) return;
    setBusy(true);
    try {
      if (section === "npcs") {
        await updateNpcIdentity(campaign.id, {
          handle: key,
          description: val,
          real_name: npcRealNameDraft.trim() || undefined,
          real_name_hidden: npcRealHiddenDraft,
        });
        setNpcRealNameDraft("");
        setNpcRealHiddenDraft(true);
      } else {
        const nextMap = { ...campaign.state[section], [key]: val };
        await updateCampaignState(
          campaign.id,
          campaign.revision,
          { [section]: nextMap },
          `Add ${section} entry: ${key}`,
        );
      }
      setDraftKey((p) => ({ ...p, [section]: "" }));
      setDraftVal((p) => ({ ...p, [section]: "" }));
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Failed to add entry");
    } finally {
      setBusy(false);
    }
  };

  const canEditPcLocation = (chId: string) => {
    if (isAdmin) return true;
    const uname = (currentUsername || "").trim().toLowerCase();
    if (!uname || !context) return false;
    const ch = context.characters.find((c) => c.id === chId);
    const owner = String((ch?.detail as Record<string, unknown> | undefined)?.owner_username ?? "")
      .trim()
      .toLowerCase();
    return !owner || owner === uname;
  };

  const handleSavePartyLocations = async () => {
    if (!campaign || busy) return;
    setBusy(true);
    try {
      const payloadLocs: Record<string, string> = {};
      for (const [cid, loc] of Object.entries(pcLocDrafts)) {
        if (canEditPcLocation(cid)) payloadLocs[cid] = loc;
      }
      await updatePartyLocation(campaign.id, { pc_locations: payloadLocs, append_notice: true });
      await onRefresh();
      onNotify("Updated party locations & scene grouping.");
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Failed to update party locations");
    } finally {
      setBusy(false);
    }
  };

  const handleReuniteParty = async () => {
    if (!campaign || !isAdmin || busy) return;
    setBusy(true);
    try {
      await updatePartyLocation(campaign.id, {
        action: "reunite",
        location: scene.trim() || undefined,
        append_notice: true,
      });
      await onRefresh();
      onNotify("Reunited party in Main Table.");
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Failed to reunite party");
    } finally {
      setBusy(false);
    }
  };

  const handleRemoveEntry = async (section: SectionKey, key: string) => {
    if (!campaign || !isAdmin || busy) return;
    setBusy(true);
    try {
      if (section === "npcs") {
        await updateNpcIdentity(campaign.id, { handle: key, delete: true });
      } else {
        const nextMap = { ...campaign.state[section] };
        delete nextMap[key];
        await updateCampaignState(
          campaign.id,
          campaign.revision,
          { [section]: nextMap },
          `Remove ${section} entry: ${key}`,
        );
      }
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Failed to remove entry");
    } finally {
      setBusy(false);
    }
  };

  const handleUndo = async () => {
    if (!campaign || !isAdmin || busy) return;
    setBusy(true);
    try {
      await undoCampaignChange(campaign.id, campaign.revision);
      await onRefresh();
      onNotify("Reverted latest narrative change.");
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Cannot undo");
    } finally {
      setBusy(false);
    }
  };

  const handleClockAction = async (payload: {
    action: "upsert" | "tick" | "delete";
    id?: string;
    name?: string;
    filled?: number;
    segments?: number;
    delta?: number;
    category?: string;
    visibility?: "public" | "secret";
    note?: string;
  }) => {
    if (!campaign || !isAdmin || busy) return;
    setBusy(true);
    try {
      const res = await mutateCampaignClock(campaign.id, {
        ...payload,
        leaf_id: activeLeafId,
      });
      setClocks(res.clocks ?? []);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Failed to update clock");
    } finally {
      setBusy(false);
    }
  };

  const handleAiNotes = async (assistMode: "expand" | "scratch") => {
    if (!campaign || !isAdmin || aiBusy || busy) return;
    setAiBusyMode(assistMode === "scratch" ? "regen" : "improve");
    try {
      const meta = context?.campaign_meta;
      const res = await assistCharacterCreation({
        target: "campaign",
        mode: assistMode,
        campaign: {
          name: campaign.name,
          lock_choices: true,
          ...(meta?.district ? { district: meta.district } : {}),
          ...(meta?.threat_rating ? { threat_rating: meta.threat_rating } : {}),
          ...(meta?.caper_style ? { caper_style: meta.caper_style } : {}),
          ...(meta?.factions?.length ? { factions: meta.factions } : {}),
          ...(meta?.screamsheet_hook ? { screamsheet_hook: meta.screamsheet_hook } : {}),
          ...(meta ? { campaign_meta: meta } : {}),
        } as Parameters<typeof assistCharacterCreation>[0]["campaign"],
        current: {
          summary: summary.trim() || undefined,
          opening_scene: scene.trim() || undefined,
          npcs: campaign.state.npcs,
          objectives: campaign.state.objectives,
        },
      });
      if (res.opening_scene) setScene(res.opening_scene);
      if (res.summary) setSummary(res.summary);
      onNotify("Updated Scene & Summary drafts — click Save Scene & Summary to keep.");
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Narrative assist failed");
    } finally {
      setAiBusyMode(null);
    }
  };

  const handleStartSession = async () => {
    if (!onStartSession || startingSession) return;
    setStartingSession(true);
    try {
      await onStartSession();
    } finally {
      setStartingSession(false);
    }
  };

  const handleExport = async () => {
    if (!onExportChat || exporting) return;
    setExporting(true);
    try {
      await onExportChat();
    } finally {
      setExporting(false);
    }
  };

  const activeEncounter = solo?.runtime.encounter?.active ? solo.runtime.encounter : null;
  const activeRuns = Object.entries(solo?.runtime.runs ?? {})
    .map(([runId, runEntry]) => [runId, runEntry?.run ?? runEntry] as const)
    .filter(([, r]) => Boolean(r?.connected));
  const totalMins = Math.max(0, solo?.runtime.clock_minutes ?? 0);
  const clockDay = Math.floor(totalMins / 1440) + 1;
  const hourNum = Math.floor((totalMins % 1440) / 60);
  const clockHour = String(hourNum).padStart(2, "0");
  const clockMin = String(totalMins % 60).padStart(2, "0");
  const clockTod =
    hourNum < 5
      ? "Late Night"
      : hourNum < 8
        ? "Dawn"
        : hourNum < 12
          ? "Morning"
          : hourNum < 17
            ? "Afternoon"
            : hourNum < 21
              ? "Evening"
              : "Night";

  const rulesNode = (
    <div className="space-y-3 text-xs text-slate-200">
      <div className="space-y-2">
        <div className="rounded-lg border border-cyan-500/30 bg-[#101624] p-3">
          <div className="font-mono text-[10px] font-bold uppercase text-cyan-300">
            1. Skill Checks (1d10)
          </div>
          <p className="mt-1 text-[11px] leading-relaxed text-slate-300">
            Roll <strong>1d10 + STAT + Skill</strong> vs Difficulty Value (DV 13 Everyday, DV 15 Difficult, DV 17 Professional). Natural <strong>10</strong> explodes (+1d10); Natural <strong>1</strong> fumbles (-1d10).
          </p>
        </div>

        <div className="rounded-lg border border-amber-500/30 bg-[#101624] p-3">
          <div className="font-mono text-[10px] font-bold uppercase text-amber-300">
            2. LUCK &amp; Overclock
          </div>
          <p className="mt-1 text-[11px] leading-relaxed text-slate-300">
            Pre-commit <strong>LUCK</strong> (+1 per point, refills each session) in the chat bar or arm <strong>Overclock</strong> (-2 Humanity for +2 on a check) in the Character tab before rolling.
          </p>
        </div>

        <div className="rounded-lg border border-rose-500/30 bg-[#101624] p-3">
          <div className="font-mono text-[10px] font-bold uppercase text-rose-300">
            3. Wounds &amp; Chrome
          </div>
          <p className="mt-1 text-[11px] leading-relaxed text-slate-300">
            Below 50% HP = <strong>Seriously Wounded (-2)</strong>. Below 1 HP = <strong>Death Saves</strong> vs BODY. Every 10 Humanity lost drops current EMP by 1.
          </p>
        </div>
      </div>

      <div className="rounded-lg border border-slate-800 bg-[#101624] p-3 space-y-2">
        <div className="font-mono text-[10px] font-bold uppercase tracking-wider text-slate-400">
          The 10 Iconic Roles (Start at Rank 4)
        </div>
        <div className="grid grid-cols-1 gap-1.5">
          {ROLES_OVERVIEW.map((r) => (
            <div
              key={r.name}
              className="rounded border border-slate-800/80 bg-slate-950/60 px-2.5 py-1.5 text-[11px]"
            >
              <span className="font-bold text-slate-100">{r.name}</span>{" "}
              <span className="font-mono text-[10px] text-cyan-300">({r.ability})</span>
              <div className="text-slate-400">{r.desc}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );

  return (
    <div className="space-y-4 p-4">
      {/* Sub-navigation: Story & Briefing vs Rules & Roles */}
      <div className="flex rounded-lg border border-slate-800 bg-[#0c111c] p-1 text-xs">
        <button
          type="button"
          onClick={() => setSubTab("briefing")}
          className={`flex flex-1 items-center justify-center gap-1.5 rounded-md py-1.5 font-medium transition ${
            subTab === "briefing"
              ? "bg-slate-800 text-cyan-300 shadow-sm"
              : "text-slate-400 hover:text-slate-200"
          }`}
        >
          <Target className="h-3.5 w-3.5" />
          Story &amp; Briefing
        </button>
        <button
          type="button"
          onClick={() => setSubTab("rules")}
          className={`flex flex-1 items-center justify-center gap-1.5 rounded-md py-1.5 font-medium transition ${
            subTab === "rules"
              ? "bg-slate-800 text-cyan-300 shadow-sm"
              : "text-slate-400 hover:text-slate-200"
          }`}
        >
          <BookOpen className="h-3.5 w-3.5" />
          Rules &amp; Roles
        </button>
      </div>

      {subTab === "rules" ? (
        rulesNode
      ) : (
        <>
          {/* Admin-only Campaigns & Sessions Manager */}
          {isAdmin && canManageCampaigns && (
            <div className="space-y-2.5 rounded-lg border border-slate-800 bg-[#101624] p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-300">
                  Campaigns &amp; Sessions
                </span>
                <div className="flex flex-wrap items-center gap-1.5">
                  {campaign && onStartSession && (
                    <button
                      type="button"
                      disabled={startingSession}
                      onClick={() => void handleStartSession()}
                      title="Start next session and refill all party LUCK"
                      className="inline-flex items-center gap-1 rounded border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-[11px] font-medium text-amber-300 hover:bg-amber-500/20 disabled:opacity-50"
                    >
                      <Sparkles className="h-3 w-3" />
                      {startingSession ? "Starting..." : "Start Session"}
                    </button>
                  )}
                  {campaign && onExportChat && (
                    <button
                      type="button"
                      disabled={exporting}
                      onClick={() => void handleExport()}
                      title="Export active story log as Markdown"
                      className="inline-flex items-center gap-1 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-[11px] text-slate-300 hover:border-cyan-500/60 hover:text-cyan-200 disabled:opacity-50"
                    >
                      <Download className="h-3 w-3 text-slate-400" />
                      {exporting ? "Exporting..." : "Export"}
                    </button>
                  )}
                  {campaign && onOpenEditCampaign && (
                    <button
                      type="button"
                      onClick={onOpenEditCampaign}
                      className="inline-flex items-center gap-1 rounded border border-cyan-500/40 bg-cyan-500/10 px-2 py-1 text-[11px] font-medium text-cyan-200 hover:bg-cyan-500/20"
                    >
                      <Compass className="h-3 w-3" />
                      Architect
                    </button>
                  )}
                  {onOpenNewCampaign && (
                    <button
                      type="button"
                      onClick={onOpenNewCampaign}
                      className="inline-flex items-center gap-1 rounded bg-cyan-600 px-2 py-1 text-[11px] font-semibold text-white hover:bg-cyan-500"
                    >
                      <Plus className="h-3 w-3" />
                      New Campaign
                    </button>
                  )}
                </div>
              </div>

              {campaigns.length > 0 && onSelectCampaign && (
                <select
                  aria-label="Active campaign"
                  value={campaign?.id ?? ""}
                  onChange={(e) => e.target.value && onSelectCampaign(e.target.value)}
                  className="w-full rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                >
                  {campaigns.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.is_primary ? "★ " : ""}{c.name} (Session {c.session_number})
                    </option>
                  ))}
                </select>
              )}

              {campaigns.length > 0 && (
                <div className="space-y-1">
                  {campaigns.map((c) => {
                    const isActive = c.id === campaign?.id;
                    const confirmingDelete = confirmDeleteCampaignId === c.id;
                    return (
                      <div
                        key={c.id}
                        className={`flex items-center justify-between gap-2 rounded border px-2.5 py-1.5 text-xs ${
                          isActive
                            ? "border-cyan-500/50 bg-cyan-950/25 text-slate-100"
                            : "border-slate-800/80 bg-slate-950/60 text-slate-300"
                        }`}
                      >
                        <button
                          type="button"
                          onClick={() => onSelectCampaign?.(c.id)}
                          className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
                        >
                          {c.is_primary && (
                            <span title="Primary campaign" className="shrink-0">
                              <Star className="h-3.5 w-3.5 fill-amber-400 text-amber-400" />
                            </span>
                          )}
                          <span className="truncate font-medium">{c.name}</span>
                          <span className="shrink-0 font-mono text-[10px] text-slate-400">
                            S{c.session_number}
                          </span>
                        </button>

                        <div className="flex shrink-0 items-center gap-1">
                          {!c.is_primary && onSetPrimaryCampaign && (
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => {
                                setBusy(true);
                                void onSetPrimaryCampaign(c.id).finally(() => setBusy(false));
                              }}
                              title="Make Primary (default for players)"
                              className="rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-[10px] text-slate-300 hover:border-amber-400 hover:text-amber-300 disabled:opacity-40"
                            >
                              Set Primary
                            </button>
                          )}
                          {onDeleteCampaign && (
                            confirmingDelete ? (
                              <div className="flex items-center gap-1 font-mono text-[10px]">
                                <button
                                  type="button"
                                  disabled={busy}
                                  onClick={() => {
                                    setConfirmDeleteCampaignId(null);
                                    setBusy(true);
                                    void onDeleteCampaign(c.id).finally(() => setBusy(false));
                                  }}
                                  className="rounded bg-rose-600 px-1.5 py-0.5 text-white hover:bg-rose-500 disabled:opacity-40"
                                >
                                  Confirm
                                </button>
                                <button
                                  type="button"
                                  onClick={() => setConfirmDeleteCampaignId(null)}
                                  className="px-1 text-slate-400 hover:text-slate-200"
                                >
                                  Cancel
                                </button>
                              </div>
                            ) : (
                              <button
                                type="button"
                                disabled={busy}
                                onClick={() => setConfirmDeleteCampaignId(c.id)}
                                aria-label={`Delete campaign ${c.name}`}
                                className="rounded p-1 text-slate-500 hover:text-rose-400 disabled:opacity-40"
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </button>
                            )
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {!isAdmin && campaigns.length > 1 && onSelectCampaign && (
            <div className="rounded-lg border border-slate-800 bg-[#101624] p-3 space-y-1.5">
              <label className="block text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                Switch Campaign
              </label>
              <select
                aria-label="Active campaign"
                value={campaign?.id ?? ""}
                onChange={(e) => e.target.value && onSelectCampaign(e.target.value)}
                className="w-full rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
              >
                {campaigns.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.is_primary ? "★ " : ""}{c.name} (Session {c.session_number})
                  </option>
                ))}
              </select>
            </div>
          )}

          {!campaign || !context ? (
            <div className="rounded-lg border border-slate-800 bg-[#101624] p-5 text-center text-xs text-slate-400">
              {isAdmin
                ? "Create or select a campaign above to view and manage its story, scene, and objectives."
                : "No active campaign yet. Check the Rules & Roles tab while your GM sets up the run."}
            </div>
          ) : !isAdmin ? (
            /* Normal Player Read-Only View: Story, Current Scene, Objectives, Known Contacts & Clues */
            <div className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-800 bg-[#101624] px-3 py-2.5">
                <div>
                  <h3 className="text-sm font-bold text-slate-100">{campaign.name}</h3>
                  <p className="font-mono text-[11px] text-cyan-300">
                    Session {campaign.session_number}
                  </p>
                </div>
              </div>

              {(activeEncounter || activeRuns.length > 0) && (
                <div className="space-y-2 rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-xs">
                  {activeEncounter && (
                    <div className="flex items-center justify-between text-rose-200">
                      <span className="inline-flex items-center gap-1.5 font-semibold">
                        <Swords className="h-4 w-4 text-rose-400" />
                        Active Encounter · Round {activeEncounter.round ?? 1}
                      </span>
                    </div>
                  )}
                  {activeRuns.map(([runId, run]) => (
                    <div key={runId} className="flex items-center justify-between text-cyan-200">
                      <span className="inline-flex items-center gap-1.5 font-semibold">
                        <Cpu className="h-4 w-4 text-cyan-400" />
                        Active NET Run
                      </span>
                      <span className="font-mono">
                        Actions: {run.actions_remaining ?? 0} · Floor: {run.floor_id ?? run.current_floor_id ?? "root"}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              <div className="space-y-2.5 rounded-lg border border-slate-800 bg-[#111726] p-3 text-xs">
                <div>
                  <div className="mb-1 flex items-center gap-1.5 font-semibold text-cyan-300">
                    <MapPin className="h-3.5 w-3.5" />
                    Current Scene
                  </div>
                  <p className="text-slate-200">
                    {campaign.state.scene?.trim() || "No active scene location recorded yet."}
                  </p>
                </div>
                <div className="border-t border-slate-800/80 pt-2.5">
                  <div className="mb-1 font-semibold text-slate-300">Story Briefing</div>
                  <p className="whitespace-pre-line leading-relaxed text-slate-300">
                    {campaign.state.summary?.trim() || "No story briefing recorded yet."}
                  </p>
                </div>
              </div>

              {/* Read-only Public World Clocks for Players */}
              {clocks.length > 0 && (
                <div className="space-y-2 rounded-lg border border-slate-800 bg-[#111726] p-3">
                  <div className="flex items-center justify-between">
                    <span className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-slate-400">
                      <Clock className="h-3.5 w-3.5 text-amber-400" />
                      World Clocks &amp; Heat
                    </span>
                    <span className="font-mono text-[10px] text-slate-500">
                      Day {clockDay} · {clockHour}:{clockMin}
                    </span>
                  </div>
                  <div className="space-y-1.5">
                    {clocks.map((clock) => {
                      const segments = Math.max(1, Math.min(12, clock.segments || 4));
                      const filled = Math.max(0, Math.min(segments, clock.filled || 0));
                      const isFull = filled >= segments;
                      return (
                        <div
                          key={clock.id}
                          className="rounded border border-slate-800/80 bg-slate-950/70 px-2.5 py-2 text-xs"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <div className="min-w-0">
                              <span className={`font-semibold ${isFull ? "text-rose-300" : "text-slate-200"}`}>
                                {clock.name}
                              </span>
                              {clock.note && (
                                <p className="truncate text-[10px] text-slate-400">{clock.note}</p>
                              )}
                            </div>
                            <span className="shrink-0 font-mono text-[11px] text-amber-300">
                              {filled}/{segments}
                            </span>
                          </div>
                          <div className="mt-1.5 flex gap-1">
                            {Array.from({ length: segments }).map((_, idx) => (
                              <div
                                key={idx}
                                className={`h-1.5 flex-1 rounded-sm ${
                                  idx < filled
                                    ? isFull
                                      ? "bg-rose-500"
                                      : "bg-amber-400"
                                    : "bg-slate-800"
                                }`}
                              />
                            ))}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Read-only Objectives, Contacts, Discoveries (no Unresolved Threads) */}
              {SECTION_LABELS.filter((s) => !s.adminOnly).map(({ key, title }) => {
                const entries = Object.entries((campaign.state as CampaignNarrativeState)[key] ?? {}).filter(
                  ([k]) => !k.startsWith("__"),
                );
                return (
                  <div key={key} className="rounded-lg border border-slate-800 bg-[#111726] p-3 space-y-2">
                    <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                      {title}
                    </div>
                    {entries.length === 0 ? (
                      <p className="text-xs text-slate-500">None recorded yet.</p>
                    ) : (
                      <div className="space-y-1.5">
                        {entries.map(([k, v]) => {
                          const npcProf = key === "npcs" ? context.npc_profiles?.[k] : undefined;
                          const npcReal = npcProf?.real_name;
                          const npcHidden = Boolean(npcProf?.real_name_hidden);
                          return (
                            <div
                              key={k}
                              className="rounded border border-slate-800/80 bg-slate-950/60 px-2.5 py-1.5 text-xs"
                            >
                              <span className="font-semibold text-cyan-300">{k}</span>
                              {npcReal && !npcHidden && npcReal !== k && (
                                <span className="ml-1 text-[10px] text-slate-400">({npcReal})</span>
                              )}
                              <span className="font-semibold text-cyan-300">:</span>{" "}
                              <span className="text-slate-200">{v}</span>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })}

              {/* Party Locations (players can only update their own character if allowed) */}
              {context.characters.length >= 2 && (
                <div className="space-y-2 rounded-lg border border-slate-800 bg-[#101624] p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-200">
                      <Users className="h-3.5 w-3.5 text-cyan-400" />
                      Party Locations
                      <span
                        className={`rounded border px-1.5 py-0.5 font-mono text-[10px] ${
                          context.party_grouping?.mode === "split"
                            ? "border-amber-500/50 bg-amber-500/15 text-amber-200"
                            : "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
                        }`}
                      >
                        {context.party_grouping?.mode === "split" ? "SPLIT" : "TOGETHER"}
                      </span>
                    </span>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void handleSavePartyLocations()}
                      className="rounded border border-cyan-500/40 bg-cyan-500/15 px-2 py-0.5 text-[11px] font-semibold text-cyan-200 hover:bg-cyan-500/25 disabled:opacity-45"
                    >
                      Update My Location
                    </button>
                  </div>
                  <div className="space-y-1.5">
                    {context.characters.map((ch) => {
                      const d = (ch.detail ?? {}) as Record<string, unknown>;
                      const handle = typeof d.handle === "string" && d.handle.trim() ? d.handle.trim() : ch.name;
                      const editable = canEditPcLocation(ch.id);
                      return (
                        <div key={ch.id} className="flex items-center gap-2 text-xs">
                          <span className="w-28 shrink-0 truncate font-semibold text-cyan-300">{handle}</span>
                          <input
                            type="text"
                            disabled={!editable}
                            value={pcLocDrafts[ch.id] ?? scene}
                            onChange={(e) => setPcLocDrafts((p) => ({ ...p, [ch.id]: e.target.value }))}
                            placeholder="Current location..."
                            className="flex-1 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none disabled:opacity-50"
                          />
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          ) : (
            /* Admin Full Campaign Controls */
            <>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h3 className="text-sm font-bold text-slate-100">{campaign.name}</h3>
                  <p className="font-mono text-[11px] text-slate-400">
                    Session {campaign.session_number} · rev {campaign.revision} · Day {clockDay} {clockHour}:{clockMin} ({clockTod})
                  </p>
                </div>
                <div className="flex items-center gap-1.5">
                  {onCompressMemory && (
                    <button
                      type="button"
                      disabled={busy || Boolean(compressingMemory)}
                      onClick={() => void onCompressMemory()}
                      title="Distill long session history into Campaign Library dossiers & compact summary"
                      className="inline-flex items-center gap-1 rounded border border-cyan-500/40 bg-cyan-500/10 px-2.5 py-1 text-xs text-cyan-200 hover:bg-cyan-500/20 disabled:opacity-50"
                    >
                      <Sparkles className="h-3.5 w-3.5" />
                      {compressingMemory ? "Compressing..." : "Compress to Library"}
                    </button>
                  )}
                  <button
                    type="button"
                    disabled={busy}
                    onClick={handleUndo}
                    className="inline-flex items-center gap-1 rounded border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs text-slate-300 hover:border-amber-500/60 hover:text-amber-300"
                  >
                    <RotateCcw className="h-3.5 w-3.5" />
                    Undo Note
                  </button>
                </div>
              </div>

              {(activeEncounter || activeRuns.length > 0) && (
                <div className="space-y-2 rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-xs">
                  {activeEncounter && (
                    <div className="flex items-center justify-between text-rose-200">
                      <span className="inline-flex items-center gap-1.5 font-semibold">
                        <Swords className="h-4 w-4 text-rose-400" />
                        Active Encounter · Round {activeEncounter.round ?? 1}
                      </span>
                      <span className="font-mono">
                        {activeEncounter.queue?.length ?? 0} combatants
                      </span>
                    </div>
                  )}
                  {activeRuns.map(([runId, run]) => (
                    <div key={runId} className="flex items-center justify-between text-cyan-200">
                      <span className="inline-flex items-center gap-1.5 font-semibold">
                        <Cpu className="h-4 w-4 text-cyan-400" />
                        Active NET Run
                      </span>
                      <span className="font-mono">
                        Actions: {run.actions_remaining ?? 0} · Floor: {run.floor_id ?? run.current_floor_id ?? "root"}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              <form onSubmit={handleSaveText} className="space-y-3 rounded-lg border border-slate-800 bg-[#111726] p-3">
                <div>
                  <label className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-slate-300">
                    <MapPin className="h-3.5 w-3.5 text-cyan-400" />
                    Current Scene
                  </label>
                  <input
                    type="text"
                    value={scene}
                    onChange={(e) => setScene(e.target.value)}
                    placeholder="Where is the crew right now?"
                    className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                  />
                </div>

                <div>
                  <label className="mb-1 block text-xs font-semibold text-slate-300">Story Summary</label>
                  <textarea
                    rows={3}
                    value={summary}
                    onChange={(e) => setSummary(e.target.value)}
                    placeholder="Ongoing plot summary for the AI GM..."
                    className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                  />
                </div>

                <div>
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <label className="flex items-center gap-1.5 text-xs font-semibold text-slate-300">
                      <ImagePlus className="h-3.5 w-3.5 text-cyan-400" />
                      Scene / Campaign Backdrop Image (optional)
                    </label>
                    <div className="flex items-center gap-1.5">
                      <label className="inline-flex cursor-pointer items-center gap-1 rounded border border-cyan-500/40 bg-cyan-500/10 px-2 py-0.5 text-[10px] font-medium text-cyan-200 hover:bg-cyan-500/20">
                        <ImagePlus className="h-3 w-3" /> Upload Image
                        <input
                          type="file"
                          accept="image/*"
                          onChange={handleBannerUpload}
                          className="hidden"
                        />
                      </label>
                      {bannerUrl && (
                        <button
                          type="button"
                          onClick={() => setBannerUrl("")}
                          className="rounded border border-slate-700 bg-slate-950 px-1.5 py-0.5 text-[10px] text-slate-400 hover:text-rose-300"
                        >
                          Reset Default
                        </button>
                      )}
                    </div>
                  </div>
                  <input
                    type="url"
                    value={bannerUrl.startsWith("data:") ? "" : bannerUrl}
                    onChange={(e) => setBannerUrl(e.target.value)}
                    placeholder={bannerUrl.startsWith("data:") ? "Custom image uploaded from device" : "Paste an online image URL (https://…) or upload above"}
                    className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                  />
                </div>

                <div className="flex flex-wrap items-center justify-between gap-2">
                  <button
                    type="submit"
                    disabled={busy}
                    className="inline-flex items-center gap-1.5 rounded bg-cyan-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-cyan-500 disabled:opacity-50"
                  >
                    <Save className="h-3.5 w-3.5" />
                    Save Scene & Summary
                  </button>
                  <FieldAiActions
                    label="Scene & Summary"
                    disabled={busy || aiBusy}
                    busyAction={aiBusyMode}
                    onImprove={() => void handleAiNotes("expand")}
                    onRegen={() => void handleAiNotes("scratch")}
                  />
                </div>
              </form>

              {/* Party Locations & Split-Scene Grouping */}
              {context.characters.length >= 2 && (
                <div className="space-y-2 rounded-lg border border-slate-800 bg-[#101624] p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-200">
                      <Users className="h-3.5 w-3.5 text-cyan-400" />
                      Party Locations &amp; Grouping
                      <span
                        className={`rounded border px-1.5 py-0.5 font-mono text-[10px] ${
                          context.party_grouping?.mode === "split"
                            ? "border-amber-500/50 bg-amber-500/15 text-amber-200"
                            : "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
                        }`}
                      >
                        {context.party_grouping?.mode === "split" ? "SPLIT" : "TOGETHER"}
                      </span>
                    </span>
                    <div className="flex items-center gap-1.5">
                      {context.party_grouping?.mode === "split" && (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => void handleReuniteParty()}
                          className="rounded border border-emerald-500/50 bg-emerald-500/15 px-2 py-0.5 text-[11px] font-semibold text-emerald-200 hover:bg-emerald-500/25 disabled:opacity-45"
                        >
                          Reunite All
                        </button>
                      )}
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void handleSavePartyLocations()}
                        className="rounded border border-cyan-500/40 bg-cyan-500/15 px-2 py-0.5 text-[11px] font-semibold text-cyan-200 hover:bg-cyan-500/25 disabled:opacity-45"
                      >
                        Update Locations
                      </button>
                    </div>
                  </div>
                  <div className="space-y-1.5">
                    {context.characters.map((ch) => {
                      const d = (ch.detail ?? {}) as Record<string, unknown>;
                      const handle = typeof d.handle === "string" && d.handle.trim() ? d.handle.trim() : ch.name;
                      return (
                        <div key={ch.id} className="flex items-center gap-2 text-xs">
                          <span className="w-28 shrink-0 truncate font-semibold text-cyan-300">{handle}</span>
                          <input
                            type="text"
                            value={pcLocDrafts[ch.id] ?? scene}
                            onChange={(e) => setPcLocDrafts((p) => ({ ...p, [ch.id]: e.target.value }))}
                            placeholder="Current location..."
                            className="flex-1 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                          />
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* World Clocks & Heat (Admin only) */}
              <div className="space-y-2 rounded-lg border border-slate-800 bg-[#101624] p-3">
                <div className="flex items-center justify-between">
                  <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-200">
                    <Clock className="h-3.5 w-3.5 text-amber-400" />
                    World Clocks &amp; Heat
                  </span>
                  <span className="font-mono text-[10px] text-slate-500">
                    Day {clockDay} · {clockHour}:{clockMin}
                  </span>
                </div>

                {clocks.length > 0 && (
                  <div className="space-y-1.5">
                    {clocks.map((clock) => {
                      const segments = Math.max(1, Math.min(12, clock.segments || 4));
                      const filled = Math.max(0, Math.min(segments, clock.filled || 0));
                      const isFull = filled >= segments;
                      return (
                        <div
                          key={clock.id}
                          className="rounded border border-slate-800/80 bg-slate-950/70 px-2.5 py-2 text-xs"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <div className="min-w-0">
                              <span className={`font-semibold ${isFull ? "text-rose-300" : "text-slate-200"}`}>
                                {clock.name}
                              </span>
                              {clock.note && (
                                <p className="truncate text-[10px] text-slate-400">{clock.note}</p>
                              )}
                            </div>
                            <div className="flex items-center gap-1 shrink-0">
                              <button
                                type="button"
                                disabled={busy}
                                onClick={() =>
                                  void handleClockAction({
                                    action: "upsert",
                                    id: clock.id,
                                    name: clock.name,
                                    segments: clock.segments,
                                    filled: clock.filled,
                                    note: clock.note,
                                    visibility: clock.visibility === "secret" ? "public" : "secret",
                                  })
                                }
                                title={
                                  clock.visibility === "secret"
                                    ? "Secret clock (GM only) — click to make Public"
                                    : "Public clock (visible to players) — click to make Secret"
                                }
                                aria-label={`Toggle visibility for ${clock.name}`}
                                className={`inline-flex items-center gap-0.5 rounded border px-1.5 py-0.5 font-mono text-[9px] disabled:opacity-40 ${
                                  clock.visibility === "secret"
                                    ? "border-amber-500/40 bg-amber-500/10 text-amber-300"
                                    : "border-slate-700 bg-slate-900 text-slate-400 hover:border-cyan-400"
                                }`}
                              >
                                {clock.visibility === "secret" ? (
                                  <>
                                    <EyeOff className="h-2.5 w-2.5" /> Secret
                                  </>
                                ) : (
                                  <>
                                    <Eye className="h-2.5 w-2.5" /> Public
                                  </>
                                )}
                              </button>
                              <button
                                type="button"
                                disabled={busy || filled <= 0}
                                onClick={() => void handleClockAction({ action: "tick", id: clock.id, delta: -1 })}
                                aria-label={`Decrement ${clock.name}`}
                                className="rounded border border-slate-700 bg-slate-900 p-0.5 text-slate-300 hover:border-cyan-400 disabled:opacity-35"
                              >
                                <Minus className="h-3 w-3" />
                              </button>
                              <span className="min-w-[2.5rem] text-center font-mono text-[11px] text-amber-300">
                                {filled}/{segments}
                              </span>
                              <button
                                type="button"
                                disabled={busy || filled >= segments}
                                onClick={() => void handleClockAction({ action: "tick", id: clock.id, delta: 1 })}
                                aria-label={`Increment ${clock.name}`}
                                className="rounded border border-slate-700 bg-slate-900 p-0.5 text-slate-300 hover:border-amber-400 disabled:opacity-35"
                              >
                                <Plus className="h-3 w-3" />
                              </button>
                              <button
                                type="button"
                                disabled={busy}
                                onClick={() => void handleClockAction({ action: "delete", id: clock.id })}
                                aria-label={`Delete ${clock.name}`}
                                className="ml-1 text-slate-500 hover:text-rose-400 disabled:opacity-40"
                              >
                                <Trash2 className="h-3 w-3" />
                              </button>
                            </div>
                          </div>
                          <div className="mt-1.5 flex gap-1">
                            {Array.from({ length: segments }).map((_, idx) => (
                              <div
                                key={idx}
                                className={`h-1.5 flex-1 rounded-sm ${
                                  idx < filled
                                    ? isFull
                                      ? "bg-rose-500"
                                      : "bg-amber-400"
                                    : "bg-slate-800"
                                }`}
                              />
                            ))}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}

                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    const name = newClockName.trim();
                    if (!name) return;
                    const maxVal = Math.max(2, Math.min(12, parseInt(newClockMax, 10) || 4));
                    const trig = newClockTrigger.trim();
                    setNewClockName("");
                    setNewClockTrigger("");
                    void handleClockAction({
                      action: "upsert",
                      name,
                      segments: maxVal,
                      visibility: newClockVisibility,
                      note: trig || undefined,
                    });
                  }}
                  className="flex flex-wrap gap-1.5 pt-1"
                >
                  <input
                    type="text"
                    value={newClockName}
                    onChange={(e) => setNewClockName(e.target.value)}
                    placeholder="Clock (e.g. NCPD Heat)"
                    className="flex-1 min-w-[120px] rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                  />
                  <input
                    type="number"
                    min={2}
                    max={12}
                    value={newClockMax}
                    onChange={(e) => setNewClockMax(e.target.value)}
                    title="Segments (2-12)"
                    className="w-12 rounded border border-slate-700 bg-slate-950 px-1.5 py-1 text-center font-mono text-xs text-slate-100"
                  />
                  <input
                    type="text"
                    value={newClockTrigger}
                    onChange={(e) => setNewClockTrigger(e.target.value)}
                    placeholder="Trigger (optional)"
                    className="w-28 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                  />
                  <button
                    type="button"
                    onClick={() =>
                      setNewClockVisibility((v) => (v === "secret" ? "public" : "secret"))
                    }
                    title={
                      newClockVisibility === "secret"
                        ? "New clock will be Secret (GM only)"
                        : "New clock will be Public (visible to players)"
                    }
                    aria-label="New clock visibility"
                    className={`inline-flex items-center gap-1 rounded border px-2 py-1 font-mono text-[10px] ${
                      newClockVisibility === "secret"
                        ? "border-amber-500/40 bg-amber-500/10 text-amber-300"
                        : "border-slate-700 bg-slate-900 text-slate-300"
                    }`}
                  >
                    {newClockVisibility === "secret" ? (
                      <>
                        <EyeOff className="h-3 w-3" /> Secret
                      </>
                    ) : (
                      <>
                        <Eye className="h-3 w-3" /> Public
                      </>
                    )}
                  </button>
                  <button
                    type="submit"
                    disabled={busy || !newClockName.trim()}
                    aria-label="Add world clock"
                    className="inline-flex items-center rounded bg-slate-800 px-2.5 py-1 text-xs text-amber-300 hover:bg-slate-700 disabled:opacity-40"
                  >
                    <Plus className="h-3.5 w-3.5" />
                  </button>
                </form>
              </div>

              <div className="space-y-3">
                {SECTION_LABELS.map(({ key, title, placeholderKey }) => {
                  const entries = Object.entries((campaign.state as CampaignNarrativeState)[key] ?? {}).filter(
                    ([k]) => !k.startsWith("__"),
                  );
                  return (
                    <div key={key} className="rounded-lg border border-slate-800 bg-[#111726] p-3 space-y-2">
                      <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                        {title}
                      </div>
                      {entries.length === 0 ? (
                        <p className="text-xs text-slate-500">None recorded yet.</p>
                      ) : (
                        <div className="space-y-1.5">
                          {entries.map(([k, v]) => {
                            const confirming = confirmRemove?.section === key && confirmRemove?.key === k;
                            const npcProf = key === "npcs" ? context.npc_profiles?.[k] : undefined;
                            const npcReal = npcProf?.real_name;
                            const npcHidden = Boolean(npcProf?.real_name_hidden);
                            return (
                              <div
                                key={k}
                                className="flex items-start justify-between gap-2 rounded border border-slate-800/80 bg-slate-950/60 px-2.5 py-1.5 text-xs"
                              >
                                <div>
                                  <span className="font-semibold text-cyan-300">{k}</span>
                                  {npcReal && !npcHidden && npcReal !== k && (
                                    <span className="ml-1 text-[10px] text-slate-400">({npcReal})</span>
                                  )}
                                  {npcHidden && (
                                    <span
                                      title={npcReal ? `Real name '${npcReal}' is hidden from players` : "Hidden real name"}
                                      className="ml-1 inline-flex items-center gap-0.5 rounded border border-slate-700 bg-slate-900 px-1 py-0.5 font-mono text-[9px] text-slate-400"
                                    >
                                      <EyeOff className="h-2.5 w-2.5" /> {npcReal ? `Alias (${npcReal})` : "Alias Only"}
                                    </span>
                                  )}
                                  <span className="font-semibold text-cyan-300">:</span>{" "}
                                  <span className="text-slate-200">{v}</span>
                                </div>
                                {confirming ? (
                                  <div className="flex shrink-0 items-center gap-1.5 font-mono text-[10px]">
                                    <button
                                      type="button"
                                      disabled={busy}
                                      onClick={() => {
                                        setConfirmRemove(null);
                                        void handleRemoveEntry(key, k);
                                      }}
                                      className="text-rose-400 hover:text-rose-300 disabled:opacity-40"
                                    >
                                      Remove
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => setConfirmRemove(null)}
                                      className="text-slate-400 hover:text-slate-200"
                                    >
                                      Cancel
                                    </button>
                                  </div>
                                ) : (
                                  <button
                                    type="button"
                                    disabled={busy}
                                    onClick={() => setConfirmRemove({ section: key, key: k })}
                                    aria-label={`Remove ${k}`}
                                    className="shrink-0 text-slate-500 hover:text-rose-400 disabled:opacity-40"
                                  >
                                    <Trash2 className="h-3.5 w-3.5" />
                                  </button>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      )}

                      <form
                        onSubmit={(e) => {
                          e.preventDefault();
                          void handleAddEntry(key);
                        }}
                        className="space-y-1.5 pt-1"
                      >
                        <div className="flex gap-1.5">
                          <input
                            type="text"
                            value={draftKey[key]}
                            onChange={(e) => setDraftKey((p) => ({ ...p, [key]: e.target.value }))}
                            placeholder={key === "npcs" ? "Handle / Alias (e.g. Rogue)" : placeholderKey}
                            className="w-1/3 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                          />
                          <input
                            type="text"
                            value={draftVal[key]}
                            onChange={(e) => setDraftVal((p) => ({ ...p, [key]: e.target.value }))}
                            placeholder="Details..."
                            className="flex-1 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                          />
                          <button
                            type="submit"
                            disabled={busy || !draftKey[key].trim() || !draftVal[key].trim()}
                            aria-label={`Add ${key} entry`}
                            className="inline-flex items-center rounded bg-slate-800 px-2.5 py-1 text-xs text-cyan-300 hover:bg-slate-700 disabled:opacity-40"
                          >
                            <Plus className="h-3.5 w-3.5" />
                          </button>
                        </div>
                        {key === "npcs" && (
                          <div className="flex flex-wrap items-center gap-2">
                            <input
                              type="text"
                              value={npcRealNameDraft}
                              onChange={(e) => setNpcRealNameDraft(e.target.value)}
                              placeholder="Real / Legal Name (optional)"
                              className="flex-1 min-w-[140px] rounded border border-slate-700 bg-slate-950 px-2 py-1 text-[11px] text-slate-100 focus:border-cyan-400 focus:outline-none"
                            />
                            <label className="inline-flex cursor-pointer items-center gap-1 text-[10px] text-amber-300">
                              <input
                                type="checkbox"
                                checked={npcRealHiddenDraft}
                                onChange={(e) => setNpcRealHiddenDraft(e.target.checked)}
                                className="accent-amber-400"
                              />
                              {npcRealHiddenDraft ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
                              <span>{npcRealHiddenDraft ? "Hidden / Secret" : "Public"}</span>
                            </label>
                          </div>
                        )}
                      </form>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
