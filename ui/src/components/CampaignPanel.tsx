import { useEffect, useState } from "react";
import { Clock, Compass, Cpu, MapPin, Minus, Plus, RotateCcw, Save, Sparkles, Star, Swords, Trash2 } from "lucide-react";
import {
  assistCharacterCreation,
  fetchCampaignClocks,
  mutateCampaignClock,
  undoCampaignChange,
  updateCampaignState,
} from "../api";
import type { CampaignContext, CampaignNarrativeState, CampaignRecord, WorldClock } from "../types";
import { FieldAiActions } from "./FieldAiActions";

interface CampaignPanelProps {
  context: CampaignContext;
  campaigns?: CampaignRecord[];
  canManageCampaigns?: boolean;
  activeLeafId?: string | null;
  onSelectCampaign?: (id: string) => void;
  onSetPrimaryCampaign?: (id: string) => Promise<void>;
  onDeleteCampaign?: (id: string) => Promise<void>;
  onOpenNewCampaign?: () => void;
  onOpenEditCampaign?: () => void;
  onCompressMemory?: () => Promise<void>;
  compressingMemory?: boolean;
  onRefresh: () => Promise<void>;
  onNotify: (msg: string) => void;
}

type SectionKey = "npcs" | "objectives" | "discoveries" | "unresolved";

const SECTION_LABELS: Array<{ key: SectionKey; title: string; placeholderKey: string }> = [
  { key: "npcs", title: "NPCs & Contacts", placeholderKey: "Name (e.g. Rogue)" },
  { key: "objectives", title: "Active Objectives", placeholderKey: "Objective" },
  { key: "discoveries", title: "Discoveries & Clues", placeholderKey: "Clue" },
  { key: "unresolved", title: "Unresolved Threads", placeholderKey: "Thread" },
];

export function CampaignPanel({
  context,
  campaigns = [],
  canManageCampaigns = true,
  activeLeafId,
  onSelectCampaign,
  onSetPrimaryCampaign,
  onDeleteCampaign,
  onOpenNewCampaign,
  onOpenEditCampaign,
  onCompressMemory,
  compressingMemory,
  onRefresh,
  onNotify,
}: CampaignPanelProps) {
  const { campaign, solo } = context;
  const [scene, setScene] = useState(campaign.state.scene);
  const [summary, setSummary] = useState(campaign.state.summary);
  const [clocks, setClocks] = useState<WorldClock[]>([]);
  const [newClockName, setNewClockName] = useState("");
  const [newClockMax, setNewClockMax] = useState("4");
  const [newClockTrigger, setNewClockTrigger] = useState("");
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
  const [aiBusyMode, setAiBusyMode] = useState<"improve" | "regen" | null>(null);
  const [busy, setBusy] = useState(false);
  const aiBusy = aiBusyMode !== null;

  useEffect(() => {
    setScene(campaign.state.scene);
    setSummary(campaign.state.summary);
    setConfirmRemove(null);
  }, [campaign.id, campaign.revision, campaign.state.scene, campaign.state.summary]);

  useEffect(() => {
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
  }, [campaign.id, campaign.revision, activeLeafId]);

  const handleSaveText = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    try {
      await updateCampaignState(
        campaign.id,
        campaign.revision,
        { scene, summary },
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

  const handleAddEntry = async (section: SectionKey) => {
    const key = draftKey[section].trim();
    const val = draftVal[section].trim();
    if (!key || !val || busy) return;
    const nextMap = { ...campaign.state[section], [key]: val };
    setBusy(true);
    try {
      await updateCampaignState(
        campaign.id,
        campaign.revision,
        { [section]: nextMap },
        `Add ${section} entry: ${key}`,
      );
      setDraftKey((p) => ({ ...p, [section]: "" }));
      setDraftVal((p) => ({ ...p, [section]: "" }));
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Failed to add entry");
    } finally {
      setBusy(false);
    }
  };

  const handleRemoveEntry = async (section: SectionKey, key: string) => {
    if (busy) return;
    const nextMap = { ...campaign.state[section] };
    delete nextMap[key];
    setBusy(true);
    try {
      await updateCampaignState(
        campaign.id,
        campaign.revision,
        { [section]: nextMap },
        `Remove ${section} entry: ${key}`,
      );
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Failed to remove entry");
    } finally {
      setBusy(false);
    }
  };

  const handleUndo = async () => {
    if (busy) return;
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
    note?: string;
  }) => {
    if (busy) return;
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
    if (aiBusy || busy) return;
    setAiBusyMode(assistMode === "scratch" ? "regen" : "improve");
    try {
      const res = await assistCharacterCreation({
        target: "campaign",
        mode: assistMode,
        campaign: { name: campaign.name },
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

  const activeEncounter = solo.runtime.encounter?.active ? solo.runtime.encounter : null;
  const activeRuns = Object.entries(solo.runtime.runs ?? {}).filter(([, r]) => r.connected);
  const totalMins = Math.max(0, solo.runtime.clock_minutes ?? 0);
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

  return (
    <div className="space-y-4 p-4">
      {/* Campaigns & Sessions Manager */}
      {(campaigns.length > 0 || onOpenNewCampaign || onOpenEditCampaign) && (
        <div className="space-y-2 rounded-lg border border-slate-800 bg-[#101624] p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-300">
              Campaigns &amp; Sessions
            </span>
            <div className="flex items-center gap-1.5">
              {onOpenEditCampaign && (
                <button
                  type="button"
                  onClick={onOpenEditCampaign}
                  className="inline-flex items-center gap-1 rounded border border-cyan-500/40 bg-cyan-500/10 px-2 py-1 text-[11px] font-medium text-cyan-200 hover:bg-cyan-500/20"
                >
                  <Compass className="h-3 w-3" />
                  Campaign Architect
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

          {campaigns.length > 0 && (
            <div className="space-y-1">
              {campaigns.map((c) => {
                const isActive = c.id === campaign.id;
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

                    {canManageCampaigns && (
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
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

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
                Actions: {run.actions_remaining ?? 0} · Floor: {run.current_floor_id ?? "root"}
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

      {/* World Clocks & Heat */}
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
          const entries = Object.entries((campaign.state as CampaignNarrativeState)[key] ?? {});
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
                    return (
                      <div
                        key={k}
                        className="flex items-start justify-between gap-2 rounded border border-slate-800/80 bg-slate-950/60 px-2.5 py-1.5 text-xs"
                      >
                        <div>
                          <span className="font-semibold text-cyan-300">{k}:</span>{" "}
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
                className="flex gap-1.5 pt-1"
              >
                <input
                  type="text"
                  value={draftKey[key]}
                  onChange={(e) => setDraftKey((p) => ({ ...p, [key]: e.target.value }))}
                  placeholder={placeholderKey}
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
              </form>
            </div>
          );
        })}
      </div>
    </div>
  );
}
