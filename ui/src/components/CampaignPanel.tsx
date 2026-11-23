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
import { CyberFrame, HazardBadge, HudButton, RoleTag, SegmentedBar } from "./cyber";
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
  const [showCampaignRoster, setShowCampaignRoster] = useState(false);
  const [showBackdropInput, setShowBackdropInput] = useState(false);
  const [showAddClock, setShowAddClock] = useState(false);
  const [openAddSection, setOpenAddSection] = useState<Record<SectionKey, boolean>>({
    npcs: false,
    objectives: false,
    discoveries: false,
    unresolved: false,
  });
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
    <div className="space-y-3 font-cyber-ui text-xs text-[var(--hud-text)]">
      <div className="space-y-2">
        <CyberFrame variant="default" cornerTicks={false} className="border-[var(--hud-accent-line)]/50 p-3">
          <div className="font-cyber-display text-[11px] font-bold uppercase tracking-wider text-[var(--hud-accent)]">
            1. Skill Checks (1d10)
          </div>
          <p className="mt-1 text-[11px] leading-relaxed text-[var(--hud-text)]/90">
            Roll <strong>1d10 + STAT + Skill</strong> vs Difficulty Value (DV 13 Everyday, DV 15 Difficult, DV 17 Professional). Natural <strong>10</strong> explodes (+1d10); Natural <strong>1</strong> fumbles (-1d10).
          </p>
        </CyberFrame>

        <CyberFrame variant="default" cornerTicks={false} className="border-[var(--hud-warn)]/50 p-3">
          <div className="font-cyber-display text-[11px] font-bold uppercase tracking-wider text-[var(--hud-warn)]">
            2. LUCK &amp; Overclock
          </div>
          <p className="mt-1 text-[11px] leading-relaxed text-[var(--hud-text)]/90">
            Pre-commit <strong>LUCK</strong> (+1 per point, refills each session) in the chat bar or arm <strong>Overclock</strong> (-2 Humanity for +2 on a check) in the Character tab before rolling.
          </p>
        </CyberFrame>

        <CyberFrame variant="default" cornerTicks={false} className="border-[var(--hud-line)] p-3">
          <div className="font-cyber-display text-[11px] font-bold uppercase tracking-wider text-[var(--hud-primary-bright)]">
            3. Wounds &amp; Chrome
          </div>
          <p className="mt-1 text-[11px] leading-relaxed text-[var(--hud-text)]/90">
            Below 50% HP = <strong>Seriously Wounded (-2)</strong>. Below 1 HP = <strong>Death Saves</strong> vs BODY. Every 10 Humanity lost drops current EMP by 1.
          </p>
        </CyberFrame>
      </div>

      <CyberFrame variant="default" className="p-3 space-y-2">
        <div className="font-cyber-display text-[11px] font-bold uppercase tracking-wider text-[var(--hud-label)]">
          The 10 Iconic Roles (Start at Rank 4)
        </div>
        <div className="grid grid-cols-1 gap-1.5">
          {ROLES_OVERVIEW.map((r) => (
            <div
              key={r.name}
              className="border border-[var(--hud-line-soft)] bg-[var(--hud-row)] px-2.5 py-2 text-[11px]"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-cyber-ui font-semibold text-[var(--hud-text)]">{r.name}</span>
                <RoleTag role={r.ability} />
              </div>
              <div className="mt-0.5 text-[var(--hud-muted)]">{r.desc}</div>
            </div>
          ))}
        </div>
      </CyberFrame>
    </div>
  );

  return (
    <div className="space-y-4 p-4 font-cyber-ui">
      {/* Sub-navigation: Story & Briefing vs Rules & Roles */}
      <div className="flex border-b border-[var(--hud-line)] bg-[var(--hud-panel)] text-xs font-cyber-ui">
        <button
          type="button"
          onClick={() => setSubTab("briefing")}
          className={`flex flex-1 items-center justify-center gap-1.5 border-b-2 py-2 font-cyber-ui font-semibold transition-colors ${
            subTab === "briefing"
              ? "border-[var(--hud-accent)] bg-[var(--hud-accent-navy)] text-[var(--hud-accent)]"
              : "border-transparent text-[var(--hud-muted)] hover:bg-[var(--hud-row)] hover:text-[var(--hud-text)]"
          }`}
        >
          <Target className="h-3.5 w-3.5" />
          Story &amp; Briefing
        </button>
        <button
          type="button"
          onClick={() => setSubTab("rules")}
          className={`flex flex-1 items-center justify-center gap-1.5 border-b-2 py-2 font-cyber-ui font-semibold transition-colors ${
            subTab === "rules"
              ? "border-[var(--hud-accent)] bg-[var(--hud-accent-navy)] text-[var(--hud-accent)]"
              : "border-transparent text-[var(--hud-muted)] hover:bg-[var(--hud-row)] hover:text-[var(--hud-text)]"
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
          {/* Admin-only Unified Active Campaign Header */}
          {isAdmin && (canManageCampaigns || Boolean(campaign)) && (
            <CyberFrame variant="default" className="space-y-2.5 p-3">
              {/* 1. Header Row */}
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="cyber-section-title">Active Campaign</span>
                {canManageCampaigns && (
                  <div className="flex flex-wrap items-center gap-1.5">
                    {campaign && onStartSession && (
                      <HudButton
                        variant="tactical"
                        size="xs"
                        disabled={startingSession}
                        onClick={() => void handleStartSession()}
                        title="Start next session and refill all party LUCK"
                        className="border-[var(--hud-warn)]/50 text-[var(--hud-warn)]"
                      >
                        <Sparkles className="h-3 w-3" />
                        {startingSession ? "Starting..." : "Start Session"}
                      </HudButton>
                    )}
                    {campaign && onOpenEditCampaign && (
                      <HudButton
                        variant="tactical"
                        size="xs"
                        onClick={onOpenEditCampaign}
                      >
                        <Compass className="h-3 w-3 text-[var(--hud-accent)]" />
                        Architect
                      </HudButton>
                    )}
                    {onOpenNewCampaign && (
                      <HudButton
                        variant="cta"
                        size="xs"
                        onClick={onOpenNewCampaign}
                      >
                        <Plus className="h-3 w-3" />
                        New Campaign
                      </HudButton>
                    )}
                  </div>
                )}
              </div>

              {/* 2. Campaign Selector & Telemetry Block */}
              {((canManageCampaigns && campaigns.length > 0 && onSelectCampaign) || campaign) && (
                <div className="space-y-1.5">
                  {canManageCampaigns && campaigns.length > 0 && onSelectCampaign ? (
                    <select
                      aria-label="Active campaign"
                      value={campaign?.id ?? ""}
                      onChange={(e) => e.target.value && onSelectCampaign(e.target.value)}
                      className="cyber-input px-2.5 py-1.5 text-[13px] font-semibold"
                    >
                      {campaigns.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.is_primary ? "★ " : ""}{c.name} (Session {c.session_number})
                        </option>
                      ))}
                    </select>
                  ) : (
                    campaign && (
                      <h3 className="font-cyber-display text-sm font-bold text-[var(--hud-text)]">
                        {campaign.name}
                      </h3>
                    )
                  )}
                  {campaign && (
                    <p className="font-cyber-data text-[11px] text-[var(--hud-muted)]">
                      Session {campaign.session_number} · rev {campaign.revision} · Day {clockDay} {clockHour}:{clockMin} ({clockTod})
                    </p>
                  )}
                </div>
              )}

              {/* 3. Compact Utility Strip */}
              {(campaign || (canManageCampaigns && campaigns.length > 0)) && (
                <div className="flex flex-wrap items-center gap-1.5">
                  {campaign && onCompressMemory && (
                    <HudButton
                      variant="utility"
                      size="xs"
                      disabled={busy || Boolean(compressingMemory)}
                      onClick={() => void onCompressMemory()}
                      title="Distill long session history into Campaign Library dossiers & compact summary"
                    >
                      <Sparkles className="h-3 w-3 text-[var(--hud-accent)]" />
                      {compressingMemory ? "Compressing..." : "Compress to Library"}
                    </HudButton>
                  )}
                  {campaign && (
                    <HudButton
                      variant="utility"
                      size="xs"
                      disabled={busy}
                      onClick={handleUndo}
                    >
                      <RotateCcw className="h-3 w-3 text-[var(--hud-warn)]" />
                      Undo Note
                    </HudButton>
                  )}
                  {campaign && onExportChat && (
                    <HudButton
                      variant="utility"
                      size="xs"
                      disabled={exporting}
                      onClick={() => void handleExport()}
                      title="Export active story log as Markdown"
                    >
                      <Download className="h-3 w-3 text-[var(--hud-accent)]" />
                      {exporting ? "Exporting..." : "Export"}
                    </HudButton>
                  )}
                  {canManageCampaigns && campaigns.length > 0 && (
                    <HudButton
                      variant="utility"
                      size="xs"
                      active={showCampaignRoster || confirmDeleteCampaignId !== null}
                      onClick={() => setShowCampaignRoster((v) => !v)}
                    >
                      Manage List ({campaigns.length})
                    </HudButton>
                  )}
                </div>
              )}

              {/* 4. Collapsible Campaign Roster */}
              {canManageCampaigns && campaigns.length > 0 && (showCampaignRoster || confirmDeleteCampaignId !== null) && (
                <div className="space-y-1 border-t border-[var(--hud-line-soft)] pt-2">
                  {campaigns.map((c) => {
                    const isActive = c.id === campaign?.id;
                    const confirmingDelete = confirmDeleteCampaignId === c.id;
                    return (
                      <div
                        key={c.id}
                        className={`flex items-center justify-between gap-2 px-2.5 py-1.5 text-xs ${
                          isActive
                            ? "cyber-card-active text-[var(--hud-text)]"
                            : "cyber-card text-[var(--hud-muted)]"
                        }`}
                      >
                        <button
                          type="button"
                          onClick={() => onSelectCampaign?.(c.id)}
                          className="flex min-w-0 flex-1 items-center gap-1.5 text-left font-cyber-ui"
                        >
                          {c.is_primary && (
                            <span title="Primary campaign" className="shrink-0">
                              <Star className="h-3.5 w-3.5 fill-[var(--hud-warn)] text-[var(--hud-warn)]" />
                            </span>
                          )}
                          <span className="truncate font-medium text-[var(--hud-text)]">{c.name}</span>
                          <span className="shrink-0 font-cyber-data text-[10px] text-[var(--hud-muted)]">
                            S{c.session_number}
                          </span>
                        </button>

                        <div className="flex shrink-0 items-center gap-1">
                          {!c.is_primary && onSetPrimaryCampaign && (
                            <HudButton
                              variant="utility"
                              size="xs"
                              disabled={busy}
                              onClick={() => {
                                setBusy(true);
                                void onSetPrimaryCampaign(c.id).finally(() => setBusy(false));
                              }}
                              title="Make Primary (default for players)"
                            >
                              Set Primary
                            </HudButton>
                          )}
                          {onDeleteCampaign && (
                            confirmingDelete ? (
                              <div className="flex items-center gap-1">
                                <HudButton
                                  variant="danger"
                                  size="xs"
                                  disabled={busy}
                                  onClick={() => {
                                    setConfirmDeleteCampaignId(null);
                                    setBusy(true);
                                    void onDeleteCampaign(c.id).finally(() => setBusy(false));
                                  }}
                                >
                                  Confirm
                                </HudButton>
                                <HudButton
                                  variant="ghost"
                                  size="xs"
                                  onClick={() => setConfirmDeleteCampaignId(null)}
                                >
                                  Cancel
                                </HudButton>
                              </div>
                            ) : (
                              <HudButton
                                variant="ghost"
                                size="xs"
                                disabled={busy}
                                onClick={() => setConfirmDeleteCampaignId(c.id)}
                                aria-label={`Delete campaign ${c.name}`}
                                className="px-1.5 text-[var(--hud-muted)] hover:text-[var(--hud-primary-bright)]"
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </HudButton>
                            )
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </CyberFrame>
          )}

          {!isAdmin && campaigns.length > 1 && onSelectCampaign && (
            <CyberFrame variant="default" className="p-3 space-y-1.5">
              <label className="block font-cyber-ui text-[11px] font-semibold uppercase tracking-wider text-[var(--hud-label)]">
                Switch Campaign
              </label>
              <select
                aria-label="Active campaign"
                value={campaign?.id ?? ""}
                onChange={(e) => e.target.value && onSelectCampaign(e.target.value)}
                className="w-full border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] px-2.5 py-1.5 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
              >
                {campaigns.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.is_primary ? "★ " : ""}{c.name} (Session {c.session_number})
                  </option>
                ))}
              </select>
            </CyberFrame>
          )}

          {!campaign || !context ? (
            <CyberFrame variant="default" className="p-5 text-center font-cyber-ui text-xs text-[var(--hud-muted)]">
              {isAdmin
                ? "Create or select a campaign above to view and manage its story, scene, and objectives."
                : "No active campaign yet. Check the Rules & Roles tab while your GM sets up the run."}
            </CyberFrame>
          ) : !isAdmin ? (
            /* Normal Player Read-Only View: Story, Current Scene, Objectives, Known Contacts & Clues */
            <div className="space-y-3">
              <CyberFrame variant="default" className="flex flex-wrap items-center justify-between gap-2 px-3 py-2.5">
                <div>
                  <h3 className="font-cyber-display text-sm font-bold text-[var(--hud-text)]">{campaign.name}</h3>
                  <p className="font-cyber-data text-[11px] text-[var(--hud-accent)]">
                    Session {campaign.session_number}
                  </p>
                </div>
              </CyberFrame>

              {(activeEncounter || activeRuns.length > 0) && (
                <div className="cyber-hazard-thin space-y-2 border border-[var(--hud-primary-bright)]/70 bg-[var(--hud-row)] p-3 text-xs">
                  {activeEncounter && (
                    <div className="flex items-center justify-between text-[var(--hud-text)]">
                      <span className="inline-flex items-center gap-1.5 font-cyber-ui font-semibold">
                        <Swords className="h-4 w-4 text-[var(--hud-primary-bright)]" />
                        Active Encounter · Round{" "}
                        <span className="font-cyber-data text-[var(--hud-warn)]">{activeEncounter.round ?? 1}</span>
                      </span>
                    </div>
                  )}
                  {activeRuns.map(([runId, run]) => (
                    <div key={runId} className="flex items-center justify-between text-[var(--hud-accent)]">
                      <span className="inline-flex items-center gap-1.5 font-cyber-ui font-semibold">
                        <Cpu className="h-4 w-4 text-[var(--hud-accent)]" />
                        Active NET Run
                      </span>
                      <span className="font-cyber-data">
                        Actions: {run.actions_remaining ?? 0} · Floor: {run.floor_id ?? run.current_floor_id ?? "root"}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              <CyberFrame variant="default" className="space-y-2.5 p-3 text-xs">
                <div>
                  <div className="mb-1 flex items-center gap-1.5 font-cyber-display text-[11px] font-semibold uppercase tracking-wider text-[var(--hud-accent)]">
                    <MapPin className="h-3.5 w-3.5" />
                    Current Scene
                  </div>
                  <p className="text-[var(--hud-text)]">
                    {campaign.state.scene?.trim() || "No active scene location recorded yet."}
                  </p>
                </div>
                <div className="border-t border-[var(--hud-line-soft)] pt-2.5">
                  <div className="mb-1 font-cyber-display text-[11px] font-semibold uppercase tracking-wider text-[var(--hud-label)]">
                    Story Briefing
                  </div>
                  <p className="whitespace-pre-line leading-relaxed text-[var(--hud-text)]/90">
                    {campaign.state.summary?.trim() || "No story briefing recorded yet."}
                  </p>
                </div>
              </CyberFrame>

              {/* Read-only Public World Clocks for Players */}
              {clocks.length > 0 && (
                <CyberFrame variant="default" className="space-y-2 p-3">
                  <div className="flex items-center justify-between">
                    <span className="inline-flex items-center gap-1.5 font-cyber-display text-xs font-semibold uppercase tracking-wider text-[var(--hud-label)]">
                      <Clock className="h-3.5 w-3.5 text-[var(--hud-warn)]" />
                      World Clocks &amp; Heat
                    </span>
                    <span className="font-cyber-data text-[10px] text-[var(--hud-muted)]">
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
                          className="border border-[var(--hud-line-soft)] bg-[var(--hud-row)] px-2.5 py-2 text-xs"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <div className="min-w-0">
                              <span
                                className={`font-cyber-ui font-semibold ${
                                  isFull ? "text-[var(--hud-primary-bright)]" : "text-[var(--hud-text)]"
                                }`}
                              >
                                {clock.name}
                              </span>
                              {clock.note && (
                                <p className="truncate text-[10px] text-[var(--hud-muted)]">{clock.note}</p>
                              )}
                            </div>
                            <span className="shrink-0 font-cyber-data text-[11px] text-[var(--hud-warn)]">
                              {filled}/{segments}
                            </span>
                          </div>
                          <SegmentedBar
                            value={filled}
                            max={segments}
                            segments={segments}
                            tone={isFull ? "primary" : "warn"}
                            className="mt-1.5"
                          />
                        </div>
                      );
                    })}
                  </div>
                </CyberFrame>
              )}

              {/* Read-only Objectives, Contacts, Discoveries (no Unresolved Threads) */}
              {SECTION_LABELS.filter((s) => !s.adminOnly).map(({ key, title }) => {
                const entries = Object.entries((campaign.state as CampaignNarrativeState)[key] ?? {}).filter(
                  ([k]) => !k.startsWith("__"),
                );
                return (
                  <CyberFrame key={key} variant="default" className="p-3 space-y-2">
                    <div className="font-cyber-display text-xs font-semibold uppercase tracking-wider text-[var(--hud-label)]">
                      {title}
                    </div>
                    {entries.length === 0 ? (
                      <p className="text-xs text-[var(--hud-muted)]">None recorded yet.</p>
                    ) : (
                      <div className="space-y-1.5">
                        {entries.map(([k, v]) => {
                          const npcProf = key === "npcs" ? context.npc_profiles?.[k] : undefined;
                          const npcReal = npcProf?.real_name;
                          const npcHidden = Boolean(npcProf?.real_name_hidden);
                          return (
                            <div
                              key={k}
                              className="border border-[var(--hud-line-soft)] bg-[var(--hud-row)] px-2.5 py-1.5 text-xs"
                            >
                              <span className="font-cyber-ui font-semibold text-[var(--hud-accent)]">{k}</span>
                              {npcReal && !npcHidden && npcReal !== k && (
                                <span className="ml-1 text-[10px] text-[var(--hud-muted)]">({npcReal})</span>
                              )}
                              <span className="font-cyber-ui font-semibold text-[var(--hud-accent)]">:</span>{" "}
                              <span className="text-[var(--hud-text)]">{v}</span>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </CyberFrame>
                );
              })}

              {/* Party Locations (players can only update their own character if allowed) */}
              {context.characters.length >= 2 && (
                <CyberFrame variant="default" className="space-y-2 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="inline-flex items-center gap-1.5 font-cyber-display text-xs font-semibold text-[var(--hud-text)]">
                      <Users className="h-3.5 w-3.5 text-[var(--hud-accent)]" />
                      Party Locations
                      {context.party_grouping?.mode === "split" ? (
                        <HazardBadge tone="warn">SPLIT</HazardBadge>
                      ) : (
                        <span className="border border-[var(--hud-ok)]/50 bg-[var(--hud-accent-navy)] px-1.5 py-0.5 font-cyber-ui text-[10px] font-semibold uppercase tracking-wider text-[var(--hud-ok)]">
                          TOGETHER
                        </span>
                      )}
                    </span>
                    <HudButton
                      variant="tactical"
                      size="xs"
                      disabled={busy}
                      onClick={() => void handleSavePartyLocations()}
                    >
                      Update My Location
                    </HudButton>
                  </div>
                  <div className="space-y-1.5">
                    {context.characters.map((ch) => {
                      const d = (ch.detail ?? {}) as Record<string, unknown>;
                      const handle = typeof d.handle === "string" && d.handle.trim() ? d.handle.trim() : ch.name;
                      const editable = canEditPcLocation(ch.id);
                      return (
                        <div key={ch.id} className="flex items-center gap-2 text-xs">
                          <span className="w-28 shrink-0 truncate font-cyber-ui font-semibold text-[var(--hud-accent)]">
                            {handle}
                          </span>
                          <input
                            type="text"
                            disabled={!editable}
                            value={pcLocDrafts[ch.id] ?? scene}
                            onChange={(e) => setPcLocDrafts((p) => ({ ...p, [ch.id]: e.target.value }))}
                            placeholder="Current location..."
                            className="flex-1 border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none disabled:opacity-50"
                          />
                        </div>
                      );
                    })}
                  </div>
                </CyberFrame>
              )}
            </div>
          ) : (
            /* Admin Full Campaign Controls */
            <>
              {(activeEncounter || activeRuns.length > 0) && (
                <div className="cyber-hazard-thin space-y-2 border border-[var(--hud-primary-bright)]/70 bg-[var(--hud-row)] p-3 text-xs">
                  {activeEncounter && (
                    <div className="flex items-center justify-between text-[var(--hud-text)]">
                      <span className="inline-flex items-center gap-1.5 font-cyber-ui font-semibold">
                        <Swords className="h-4 w-4 text-[var(--hud-primary-bright)]" />
                        Active Encounter · Round{" "}
                        <span className="font-cyber-data text-[var(--hud-warn)]">{activeEncounter.round ?? 1}</span>
                      </span>
                      <span className="font-cyber-data text-[var(--hud-muted)]">
                        {activeEncounter.queue?.length ?? 0} combatants
                      </span>
                    </div>
                  )}
                  {activeRuns.map(([runId, run]) => (
                    <div key={runId} className="flex items-center justify-between text-[var(--hud-accent)]">
                      <span className="inline-flex items-center gap-1.5 font-cyber-ui font-semibold">
                        <Cpu className="h-4 w-4 text-[var(--hud-accent)]" />
                        Active NET Run
                      </span>
                      <span className="font-cyber-data">
                        Actions: {run.actions_remaining ?? 0} · Floor: {run.floor_id ?? run.current_floor_id ?? "root"}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              <CyberFrame variant="default" className="p-3">
                <form onSubmit={handleSaveText} className="space-y-3">
                  <div>
                    <label className="mb-1 flex items-center gap-1.5 font-cyber-ui text-xs font-semibold uppercase tracking-wider text-[var(--hud-label)]">
                      <MapPin className="h-3.5 w-3.5 text-[var(--hud-accent)]" />
                      Current Scene
                    </label>
                    <input
                      type="text"
                      value={scene}
                      onChange={(e) => setScene(e.target.value)}
                      placeholder="Where is the crew right now?"
                      className="w-full border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] px-2.5 py-1.5 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                    />
                  </div>

                  <div>
                    <label className="mb-1 block font-cyber-ui text-xs font-semibold uppercase tracking-wider text-[var(--hud-label)]">
                      Story Summary
                    </label>
                    <textarea
                      rows={3}
                      value={summary}
                      onChange={(e) => setSummary(e.target.value)}
                      placeholder="Ongoing plot summary for the AI GM..."
                      className="w-full border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] px-2.5 py-1.5 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                    />
                  </div>

                  <div className="space-y-2">
                    <div className="flex items-center justify-between gap-2">
                      <HudButton
                        variant="utility"
                        size="xs"
                        active={showBackdropInput}
                        onClick={() => setShowBackdropInput((v) => !v)}
                      >
                        <ImagePlus className="h-3 w-3 text-[var(--hud-accent)]" />
                        {bannerUrl ? "Backdrop Image (Active)" : "+ Backdrop Image"}
                      </HudButton>
                    </div>

                    {showBackdropInput && (
                      <div className="space-y-1.5 border border-[var(--hud-line-soft)] bg-[var(--hud-row)] p-2">
                        <div className="flex items-center justify-between gap-2">
                          <label className="cyber-btn-util inline-flex cursor-pointer items-center gap-1 px-2 py-0.5 font-cyber-ui text-[10px] font-medium">
                            <ImagePlus className="h-3 w-3 text-[var(--hud-accent)]" /> Upload Image
                            <input
                              type="file"
                              accept="image/*"
                              onChange={handleBannerUpload}
                              className="hidden"
                            />
                          </label>
                          {bannerUrl && (
                            <HudButton
                              variant="ghost"
                              size="xs"
                              onClick={() => setBannerUrl("")}
                            >
                              Reset Default
                            </HudButton>
                          )}
                        </div>
                        <input
                          type="url"
                          value={bannerUrl.startsWith("data:") ? "" : bannerUrl}
                          onChange={(e) => setBannerUrl(e.target.value)}
                          placeholder={bannerUrl.startsWith("data:") ? "Custom image uploaded from device" : "Paste an online image URL (https://…) or upload above"}
                          className="cyber-input px-2.5 py-1.5 text-xs"
                        />
                      </div>
                    )}
                  </div>

                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <HudButton
                      type="submit"
                      variant="cta"
                      size="sm"
                      disabled={busy}
                    >
                      <Save className="h-3.5 w-3.5" />
                      Save Scene & Summary
                    </HudButton>
                    <FieldAiActions
                      label="Scene & Summary"
                      disabled={busy || aiBusy}
                      busyAction={aiBusyMode}
                      onImprove={() => void handleAiNotes("expand")}
                      onRegen={() => void handleAiNotes("scratch")}
                    />
                  </div>
                </form>
              </CyberFrame>

              {/* Party Locations & Split-Scene Grouping */}
              {context.characters.length >= 2 && (
                <CyberFrame variant="default" className="space-y-2 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="inline-flex items-center gap-1.5 font-cyber-display text-xs font-semibold text-[var(--hud-text)]">
                      <Users className="h-3.5 w-3.5 text-[var(--hud-accent)]" />
                      Party Locations &amp; Grouping
                      {context.party_grouping?.mode === "split" ? (
                        <HazardBadge tone="warn">SPLIT</HazardBadge>
                      ) : (
                        <span className="border border-[var(--hud-ok)]/50 bg-[var(--hud-accent-navy)] px-1.5 py-0.5 font-cyber-ui text-[10px] font-semibold uppercase tracking-wider text-[var(--hud-ok)]">
                          TOGETHER
                        </span>
                      )}
                    </span>
                    <div className="flex items-center gap-1.5">
                      {context.party_grouping?.mode === "split" && (
                        <HudButton
                          variant="tactical"
                          size="xs"
                          disabled={busy}
                          onClick={() => void handleReuniteParty()}
                          className="border-[var(--hud-ok)]/50 text-[var(--hud-ok)]"
                        >
                          Reunite All
                        </HudButton>
                      )}
                      <HudButton
                        variant="tactical"
                        size="xs"
                        disabled={busy}
                        onClick={() => void handleSavePartyLocations()}
                      >
                        Update Locations
                      </HudButton>
                    </div>
                  </div>
                  <div className="space-y-1.5">
                    {context.characters.map((ch) => {
                      const d = (ch.detail ?? {}) as Record<string, unknown>;
                      const handle = typeof d.handle === "string" && d.handle.trim() ? d.handle.trim() : ch.name;
                      return (
                        <div key={ch.id} className="flex items-center gap-2 text-xs">
                          <span className="w-28 shrink-0 truncate font-cyber-ui font-semibold text-[var(--hud-accent)]">
                            {handle}
                          </span>
                          <input
                            type="text"
                            value={pcLocDrafts[ch.id] ?? scene}
                            onChange={(e) => setPcLocDrafts((p) => ({ ...p, [ch.id]: e.target.value }))}
                            placeholder="Current location..."
                            className="flex-1 border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                          />
                        </div>
                      );
                    })}
                  </div>
                </CyberFrame>
              )}

              {/* World Clocks & Heat (Admin only) */}
              <CyberFrame variant="default" className="space-y-2.5 p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="inline-flex items-center gap-1.5 font-cyber-display text-xs font-semibold uppercase tracking-wider text-[var(--hud-text)]">
                    <Clock className="h-3.5 w-3.5 text-[var(--hud-warn)]" />
                    World Clocks &amp; Heat
                  </span>
                  <div className="flex items-center gap-2">
                    <span className="font-cyber-data text-[10px] text-[var(--hud-muted)]">
                      Day {clockDay} · {clockHour}:{clockMin}
                    </span>
                    <HudButton
                      variant="utility"
                      size="xs"
                      active={showAddClock}
                      onClick={() => setShowAddClock((v) => !v)}
                    >
                      + Add Clock
                    </HudButton>
                  </div>
                </div>

                {clocks.length > 0 && (
                  <div className="space-y-1.5">
                    {clocks.map((clock) => {
                      const segments = Math.max(1, Math.min(12, clock.segments || 4));
                      const filled = Math.max(0, Math.min(segments, clock.filled || 0));
                      const isFull = filled >= segments;
                      const isSecret = clock.visibility === "secret";
                      return (
                        <div
                          key={clock.id}
                          className={`border px-2.5 py-2 text-xs ${
                            isSecret
                              ? "cyber-hazard-thin border-[var(--hud-warn)]/60 bg-[var(--hud-row)]"
                              : "border-[var(--hud-line-soft)] bg-[var(--hud-row)]"
                          }`}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <div className="min-w-0">
                              <div className="flex flex-wrap items-center gap-1.5">
                                <span
                                  className={`font-cyber-ui font-semibold ${
                                    isFull ? "text-[var(--hud-primary-bright)]" : "text-[var(--hud-text)]"
                                  }`}
                                >
                                  {clock.name}
                                </span>
                                {isSecret && (
                                  <HazardBadge tone="warn">SECRET</HazardBadge>
                                )}
                              </div>
                              {clock.note && (
                                <p className="truncate text-[10px] text-[var(--hud-muted)]">{clock.note}</p>
                              )}
                            </div>
                            <div className="flex items-center gap-1 shrink-0">
                              <HudButton
                                variant="utility"
                                size="xs"
                                disabled={busy}
                                active={isSecret}
                                onClick={() =>
                                  void handleClockAction({
                                    action: "upsert",
                                    id: clock.id,
                                    name: clock.name,
                                    segments: clock.segments,
                                    filled: clock.filled,
                                    note: clock.note,
                                    visibility: isSecret ? "public" : "secret",
                                  })
                                }
                                title={
                                  isSecret
                                    ? "Secret clock (GM only) — click to make Public"
                                    : "Public clock (visible to players) — click to make Secret"
                                }
                                aria-label={`Toggle visibility for ${clock.name}`}
                                className={
                                  isSecret
                                    ? "border-[var(--hud-warn)]/60 text-[var(--hud-warn)]"
                                    : "text-[var(--hud-muted)]"
                                }
                              >
                                {isSecret ? (
                                  <>
                                    <EyeOff className="h-2.5 w-2.5" /> Secret
                                  </>
                                ) : (
                                  <>
                                    <Eye className="h-2.5 w-2.5" /> Public
                                  </>
                                )}
                              </HudButton>
                              <HudButton
                                variant="utility"
                                size="xs"
                                disabled={busy || filled <= 0}
                                onClick={() => void handleClockAction({ action: "tick", id: clock.id, delta: -1 })}
                                aria-label={`Decrement ${clock.name}`}
                                className="px-1.5"
                              >
                                <Minus className="h-3 w-3" />
                              </HudButton>
                              <span className="min-w-[2.5rem] text-center font-cyber-data text-[11px] text-[var(--hud-warn)]">
                                {filled}/{segments}
                              </span>
                              <HudButton
                                variant="utility"
                                size="xs"
                                disabled={busy || filled >= segments}
                                onClick={() => void handleClockAction({ action: "tick", id: clock.id, delta: 1 })}
                                aria-label={`Increment ${clock.name}`}
                                className="px-1.5"
                              >
                                <Plus className="h-3 w-3" />
                              </HudButton>
                              <HudButton
                                variant="ghost"
                                size="xs"
                                disabled={busy}
                                onClick={() => void handleClockAction({ action: "delete", id: clock.id })}
                                aria-label={`Delete ${clock.name}`}
                                className="ml-0.5 px-1 text-[var(--hud-muted)] hover:text-[var(--hud-primary-bright)]"
                              >
                                <Trash2 className="h-3 w-3" />
                              </HudButton>
                            </div>
                          </div>
                          <SegmentedBar
                            value={filled}
                            max={segments}
                            segments={segments}
                            tone={isFull ? "primary" : "warn"}
                            className="mt-1.5"
                          />
                        </div>
                      );
                    })}
                  </div>
                )}

                {(showAddClock || clocks.length === 0) && (
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
                      className="flex-1 min-w-[120px] border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                    />
                    <input
                      type="number"
                      min={2}
                      max={12}
                      value={newClockMax}
                      onChange={(e) => setNewClockMax(e.target.value)}
                      title="Segments (2-12)"
                      className="w-12 border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] px-1.5 py-1 text-center font-cyber-data text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                    />
                    <input
                      type="text"
                      value={newClockTrigger}
                      onChange={(e) => setNewClockTrigger(e.target.value)}
                      placeholder="Trigger (optional)"
                      className="w-28 border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                    />
                    <HudButton
                      variant="tactical"
                      size="xs"
                      active={newClockVisibility === "secret"}
                      onClick={() =>
                        setNewClockVisibility((v) => (v === "secret" ? "public" : "secret"))
                      }
                      title={
                        newClockVisibility === "secret"
                          ? "New clock will be Secret (GM only)"
                          : "New clock will be Public (visible to players)"
                      }
                      aria-label="New clock visibility"
                      className={
                        newClockVisibility === "secret"
                          ? "border-[var(--hud-warn)]/60 text-[var(--hud-warn)]"
                          : "text-[var(--hud-muted)]"
                      }
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
                    </HudButton>
                    <HudButton
                      type="submit"
                      variant="tactical"
                      size="sm"
                      disabled={busy || !newClockName.trim()}
                      aria-label="Add world clock"
                      className="text-[var(--hud-warn)]"
                    >
                      <Plus className="h-3.5 w-3.5" />
                    </HudButton>
                  </form>
                )}
              </CyberFrame>

              <div className="space-y-3">
                {SECTION_LABELS.map(({ key, title, placeholderKey, adminOnly }) => {
                  const entries = Object.entries((campaign.state as CampaignNarrativeState)[key] ?? {}).filter(
                    ([k]) => !k.startsWith("__"),
                  );
                  return (
                    <CyberFrame
                      key={key}
                      variant="default"
                      className={`p-3 space-y-2 ${adminOnly ? "border-[var(--hud-warn)]/60" : ""}`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="font-cyber-display text-xs font-semibold uppercase tracking-wider text-[var(--hud-label)]">
                          {title}
                        </div>
                        <div className="flex items-center gap-1.5">
                          {adminOnly && (
                            <HazardBadge tone="warn">CLASSIFIED // GM</HazardBadge>
                          )}
                          <HudButton
                            variant="utility"
                            size="xs"
                            active={openAddSection[key]}
                            onClick={(e) => {
                              e.stopPropagation();
                              setOpenAddSection((prev) => ({ ...prev, [key]: !prev[key] }));
                            }}
                          >
                            + Add
                          </HudButton>
                        </div>
                      </div>
                      {entries.length === 0 ? (
                        <p className="text-xs text-[var(--hud-muted)]">None recorded yet.</p>
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
                                className="cyber-card flex items-start justify-between gap-2 px-2.5 py-2 text-xs"
                              >
                                <div className="min-w-0 flex-1">
                                  <div className="flex flex-wrap items-center gap-1">
                                    <span className="font-cyber-ui text-[13px] font-semibold text-[var(--hud-accent)]">
                                      {k}
                                    </span>
                                    {npcReal && !npcHidden && npcReal !== k && (
                                      <span className="text-[10px] text-[var(--hud-muted)]">({npcReal})</span>
                                    )}
                                    {npcHidden && (
                                      <HazardBadge
                                        tone="warn"
                                        title={npcReal ? `Real name '${npcReal}' is hidden from players` : "Hidden real name"}
                                        className="ml-0.5 px-1.5 py-0 text-[9px]"
                                      >
                                        <EyeOff className="h-2.5 w-2.5" /> {npcReal ? `Alias (${npcReal})` : "Alias Only"}
                                      </HazardBadge>
                                    )}
                                  </div>
                                  <p className="mt-0.5 text-xs leading-relaxed text-[var(--hud-text)]/90">{v}</p>
                                </div>
                                {confirming ? (
                                  <div className="flex shrink-0 items-center gap-1">
                                    <HudButton
                                      variant="danger"
                                      size="xs"
                                      disabled={busy}
                                      onClick={() => {
                                        setConfirmRemove(null);
                                        void handleRemoveEntry(key, k);
                                      }}
                                    >
                                      Remove
                                    </HudButton>
                                    <HudButton
                                      variant="ghost"
                                      size="xs"
                                      onClick={() => setConfirmRemove(null)}
                                    >
                                      Cancel
                                    </HudButton>
                                  </div>
                                ) : (
                                  <HudButton
                                    variant="ghost"
                                    size="xs"
                                    disabled={busy}
                                    onClick={() => setConfirmRemove({ section: key, key: k })}
                                    aria-label={`Remove ${k}`}
                                    className="shrink-0 px-1 text-[var(--hud-muted)] hover:text-[var(--hud-primary-bright)]"
                                  >
                                    <Trash2 className="h-3.5 w-3.5" />
                                  </HudButton>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      )}

                      {openAddSection[key] && (
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
                              className="w-1/3 border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                            />
                            <input
                              type="text"
                              value={draftVal[key]}
                              onChange={(e) => setDraftVal((p) => ({ ...p, [key]: e.target.value }))}
                              placeholder="Details..."
                              className="flex-1 border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                            />
                            <HudButton
                              type="submit"
                              variant="tactical"
                              size="sm"
                              disabled={busy || !draftKey[key].trim() || !draftVal[key].trim()}
                              aria-label={`Add ${key} entry`}
                              className="text-[var(--hud-accent)]"
                            >
                              <Plus className="h-3.5 w-3.5" />
                            </HudButton>
                          </div>
                          {key === "npcs" && (
                            <div className="flex flex-wrap items-center gap-2">
                              <input
                                type="text"
                                value={npcRealNameDraft}
                                onChange={(e) => setNpcRealNameDraft(e.target.value)}
                                placeholder="Real / Legal Name (optional)"
                                className="flex-1 min-w-[140px] border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] px-2 py-1 font-cyber-ui text-[11px] text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
                              />
                              <label className="inline-flex cursor-pointer items-center gap-1 font-cyber-ui text-[10px] text-[var(--hud-warn)]">
                                <input
                                  type="checkbox"
                                  checked={npcRealHiddenDraft}
                                  onChange={(e) => setNpcRealHiddenDraft(e.target.checked)}
                                  className="accent-[var(--hud-warn)]"
                                />
                                {npcRealHiddenDraft ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
                                <span>{npcRealHiddenDraft ? "Hidden / Secret" : "Public"}</span>
                              </label>
                            </div>
                          )}
                        </form>
                      )}
                    </CyberFrame>
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
