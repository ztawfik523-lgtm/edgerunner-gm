import { useEffect, useState } from "react";
import { BookOpen, FileText, Plus, Search, Sparkles, Trash2 } from "lucide-react";
import netrunArchiveBanner from "../assets/netrun-archive-banner.jpg";
import {
  addHomebrewEntry,
  deleteHomebrewEntry,
  fetchCorebookPage,
  searchLibrary,
} from "../api";
import {
  LIBRARY_CATEGORIES,
  type LibraryCategory,
  type LibraryEntry,
} from "../types";
import { classifyWeaponTiers, getWeaponTierTheme } from "../utils/weaponQuality";
import { CyberFrame, HudButton } from "./cyber";

const CATEGORY_DISPLAY_LABELS: Record<string, string> = {
  streetslang: "Streetslang",
  mook: "Mooks & Bosses",
  screamsheet: "Screamsheets",
  encounter: "Encounters",
  ammo: "Ammo",
  attachment: "Attachments",
  housing: "Housing",
  service: "Services",
  vehicle: "Vehicles",
  drug: "Drugs & Pharma",
  npc: "NPCs",
};

export function categoryLabel(c: string): string {
  return CATEGORY_DISPLAY_LABELS[c] ?? (c ? c.charAt(0).toUpperCase() + c.slice(1) : "");
}

interface LibraryPanelProps {
  campaignId: string | null;
  rulesIndexed: boolean;
  selectedEntry: LibraryEntry | null;
  onSelectEntry: (entry: LibraryEntry | null) => void;
  onNotify: (msg: string) => void;
}

export function LibraryPanel({
  campaignId,
  rulesIndexed,
  selectedEntry,
  onSelectEntry,
  onNotify,
}: LibraryPanelProps) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<LibraryCategory | "">("");
  const [sourceFilter, setSourceFilter] = useState<"all" | "corebook" | "homebrew">("all");
  const [items, setItems] = useState<LibraryEntry[]>([]);
  const [loading, setLoading] = useState(false);

  // Page reader state
  const [pageText, setPageText] = useState<string | null>(null);
  const [pageLoading, setPageLoading] = useState(false);

  // Homebrew creator
  const [creating, setCreating] = useState(false);
  const [hbName, setHbName] = useState("");
  const [hbCat, setHbCat] = useState<LibraryCategory>("weapon");
  const [hbSummary, setHbSummary] = useState("");
  const [hbDesc, setHbDesc] = useState("");
  const [hbCost, setHbCost] = useState("");
  const [hbDamage, setHbDamage] = useState("");
  const [hbStat, setHbStat] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    setLoading(true);
    try {
      const res = await searchLibrary({
        q: query,
        category,
        campaignId: campaignId ?? undefined,
        includeCorebook: sourceFilter !== "homebrew",
        includeHomebrew: sourceFilter !== "corebook",
        limit: 50,
      });
      setItems(res);
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const timer = setTimeout(() => {
      void refresh();
    }, 150);
    return () => clearTimeout(timer);
  }, [query, category, sourceFilter, campaignId]);

  useEffect(() => {
    setPageText(null);
    setConfirmDeleteId(null);
  }, [selectedEntry?.id]);

  const handleLoadPage = async (page: number) => {
    setPageLoading(true);
    try {
      const res = await fetchCorebookPage(page, "printed");
      setPageText(res.text);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Could not read page");
    } finally {
      setPageLoading(false);
    }
  };

  const handleCreateHomebrew = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!campaignId || !hbName.trim() || busy) return;
    const stats: Record<string, unknown> = {};
    if (hbCost.trim()) stats.cost_eb = Math.max(0, parseInt(hbCost, 10) || 0);
    if (hbDamage.trim()) stats.damage = hbDamage.trim();
    if (hbCat === "skill" && hbStat.trim()) stats.stat = hbStat.trim().toUpperCase();

    setBusy(true);
    try {
      const created = await addHomebrewEntry({
        campaign_id: campaignId,
        name: hbName.trim(),
        category: hbCat,
        summary: hbSummary.trim(),
        description: hbDesc.trim(),
        stats,
        tags: [hbCat, "homebrew"],
      });
      setHbName("");
      setHbSummary("");
      setHbDesc("");
      setHbCost("");
      setHbDamage("");
      setHbStat("");
      setCreating(false);
      onSelectEntry(created);
      await refresh();
      onNotify(`Added homebrew ${created.name}.`);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Failed to create homebrew");
    } finally {
      setBusy(false);
    }
  };

  const handleDeleteHomebrew = async (entry: LibraryEntry) => {
    if (!campaignId || busy) return;
    setBusy(true);
    try {
      await deleteHomebrewEntry(entry.id, campaignId);
      if (selectedEntry?.id === entry.id) onSelectEntry(null);
      await refresh();
      onNotify(`Deleted ${entry.name}.`);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Failed to delete entry");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex h-full flex-col p-4 space-y-3 font-cyber-ui">
      <CyberFrame variant="default" className="relative overflow-hidden px-3 py-2">
        <img
          src={netrunArchiveBanner}
          alt=""
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 h-full w-full object-cover opacity-35"
        />
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-r from-[var(--hud-bg)]/92 via-[var(--hud-panel)]/75 to-transparent" />
        <div className="relative z-10 flex items-center justify-between gap-2">
          <div>
            <div className="font-cyber-display text-[11px] font-bold uppercase tracking-[0.14em] text-[var(--hud-accent)]">
              NET Archive // Corebook &amp; Homebrew
            </div>
            <div className="font-cyber-ui text-[11px] text-[var(--hud-muted)]">
              {rulesIndexed ? "Corebook index online · Instant lookup" : "Homebrew & local dossier mode"}
            </div>
          </div>
          <BookOpen className="h-4 w-4 shrink-0 text-[var(--hud-primary-bright)]" />
        </div>
      </CyberFrame>

      <div className="flex items-center justify-between gap-2">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-2 h-3.5 w-3.5 text-[var(--hud-muted)]" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter weapons, programs, vehicles, mooks, screamsheets, streetslang..."
            className="w-full border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] py-1.5 pl-8 pr-3 font-cyber-ui text-xs text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:border-[var(--hud-accent)] focus:outline-none"
          />
        </div>

        {campaignId && (
          <HudButton
            variant="tactical"
            size="sm"
            active={creating}
            onClick={() => setCreating((v) => !v)}
            className="border-[var(--hud-warn)]/50 text-[var(--hud-warn)]"
          >
            <Plus className="h-3.5 w-3.5" />
            Homebrew
          </HudButton>
        )}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--hud-line)] pb-1.5">
        <select
          aria-label="Category filter"
          value={category}
          onChange={(e) => setCategory(e.target.value as LibraryCategory | "")}
          className="border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
        >
          <option value="">All categories</option>
          {LIBRARY_CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {categoryLabel(c)}
            </option>
          ))}
        </select>

        <div className="flex border-b border-[var(--hud-line)] bg-[var(--hud-panel)] font-cyber-ui text-xs">
          {(["all", "corebook", "homebrew"] as const).map((src) => {
            const label = src === "all" ? "All" : src === "corebook" ? "Corebook" : "Campaign Library";
            const active = sourceFilter === src;
            return (
              <button
                key={src}
                type="button"
                onClick={() => setSourceFilter(src)}
                className={`border-b-2 px-2.5 py-1 font-cyber-ui text-xs font-semibold transition-colors ${
                  active
                    ? "border-[var(--hud-accent)] bg-[var(--hud-accent-navy)] text-[var(--hud-accent)]"
                    : "border-transparent text-[var(--hud-muted)] hover:bg-[var(--hud-row)] hover:text-[var(--hud-text)]"
                }`}
              >
                {label}
              </button>
            );
          })}
        </div>
      </div>

      {creating && (
        <CyberFrame variant="default" className="border-[var(--hud-warn)]/60 p-3">
          <form
            onSubmit={handleCreateHomebrew}
            onKeyDown={(e) => {
              if (e.key === "Escape") setCreating(false);
            }}
            className="space-y-2.5"
          >
            <div className="font-cyber-display text-xs font-semibold uppercase tracking-wider text-[var(--hud-warn)]">
              New Campaign Homebrew
            </div>
            <div className="grid grid-cols-2 gap-2">
              <input
                type="text"
                required
                value={hbName}
                onChange={(e) => setHbName(e.target.value)}
                placeholder="Entry name (item, NPC, faction, location, rule)"
                className="border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] px-2.5 py-1.5 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
              />
              <select
                value={hbCat}
                onChange={(e) => setHbCat(e.target.value as LibraryCategory)}
                className="border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] px-2 py-1.5 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
              >
                {LIBRARY_CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {categoryLabel(c)}
                  </option>
                ))}
              </select>
            </div>
            <input
              type="text"
              value={hbSummary}
              onChange={(e) => setHbSummary(e.target.value)}
              placeholder="Short summary..."
              className="w-full border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] px-2.5 py-1.5 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
            />
            <textarea
              rows={2}
              value={hbDesc}
              onChange={(e) => setHbDesc(e.target.value)}
              placeholder="Full mechanics & flavor description..."
              className="w-full border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] px-2.5 py-1.5 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
            />
            <div className="grid grid-cols-3 gap-2">
              <input
                type="number"
                min={0}
                value={hbCost}
                onChange={(e) => setHbCost(e.target.value)}
                placeholder="Cost (eb)"
                className="border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] px-2 py-1 font-cyber-data text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
              />
              <input
                type="text"
                value={hbDamage}
                onChange={(e) => setHbDamage(e.target.value)}
                placeholder="Damage (e.g. 3d6)"
                className="border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
              />
              <input
                type="text"
                value={hbStat}
                onChange={(e) => setHbStat(e.target.value)}
                placeholder="Skill Stat (e.g. TECH)"
                className="border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] px-2 py-1 font-cyber-ui text-xs text-[var(--hud-text)] focus:border-[var(--hud-accent)] focus:outline-none"
              />
            </div>
            <div className="flex justify-end gap-2">
              <HudButton
                variant="ghost"
                size="xs"
                onClick={() => setCreating(false)}
              >
                Cancel
              </HudButton>
              <HudButton
                type="submit"
                variant="cta"
                size="sm"
                disabled={busy}
              >
                Save Homebrew
              </HudButton>
            </div>
          </form>
        </CyberFrame>
      )}

      {selectedEntry && (
        <CyberFrame variant="modal" className="border-[var(--hud-accent-line)] p-3 space-y-2.5">
          <div className="flex items-start justify-between gap-2">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h4 className="font-cyber-display text-sm font-bold text-[var(--hud-text)]">
                  {selectedEntry.name}
                </h4>
                <span className="border border-[var(--hud-line-soft)] bg-[var(--hud-row)] px-1.5 py-0.5 font-cyber-ui text-[10px] font-semibold uppercase tracking-wider text-[var(--hud-accent)]">
                  {selectedEntry.category}
                </span>
                {selectedEntry.printed_page && (
                  <span className="border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] px-1.5 py-0.5 font-cyber-data text-[10px] text-[var(--hud-warn)]">
                    p.{selectedEntry.printed_page}
                  </span>
                )}
              </div>
              <p className="mt-1 font-cyber-ui text-xs leading-relaxed text-[var(--hud-text)]/90">
                {selectedEntry.description || selectedEntry.summary}
              </p>
            </div>

            <div className="flex items-center gap-1 shrink-0">
              {selectedEntry.source === "homebrew" && (
                confirmDeleteId === selectedEntry.id ? (
                  <div className="inline-flex items-center gap-1 border border-[var(--hud-primary-bright)]/60 bg-[var(--hud-row)] px-1.5 py-0.5">
                    <HudButton
                      variant="danger"
                      size="xs"
                      disabled={busy}
                      onClick={() => {
                        setConfirmDeleteId(null);
                        void handleDeleteHomebrew(selectedEntry);
                      }}
                    >
                      Delete
                    </HudButton>
                    <HudButton
                      variant="ghost"
                      size="xs"
                      onClick={() => setConfirmDeleteId(null)}
                    >
                      Cancel
                    </HudButton>
                  </div>
                ) : (
                  <HudButton
                    variant="ghost"
                    size="xs"
                    disabled={busy}
                    onClick={() => setConfirmDeleteId(selectedEntry.id)}
                    title="Delete homebrew entry"
                    aria-label="Delete homebrew entry"
                    className="px-1 text-[var(--hud-muted)] hover:text-[var(--hud-primary-bright)]"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </HudButton>
                )
              )}
              <HudButton
                variant="tactical"
                size="xs"
                onClick={() => onSelectEntry(null)}
                aria-label="Close entry details"
              >
                Close
              </HudButton>
            </div>
          </div>

          {Object.keys(selectedEntry.stats ?? {}).length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(selectedEntry.stats).map(([k, v]) => (
                <span
                  key={k}
                  className="border border-[var(--hud-line-soft)] bg-[var(--hud-row)] px-2 py-0.5 font-cyber-data text-[11px] text-[var(--hud-text)]"
                >
                  {k}: {String(v)}
                </span>
              ))}
            </div>
          )}

          {rulesIndexed && selectedEntry.printed_page && (
            <div>
              <HudButton
                variant="tactical"
                size="xs"
                disabled={pageLoading}
                onClick={() => handleLoadPage(selectedEntry.printed_page!)}
              >
                <FileText className="h-3.5 w-3.5 text-[var(--hud-accent)]" />
                {pageLoading ? "Loading page..." : `Read Corebook p.${selectedEntry.printed_page}`}
              </HudButton>
              {pageText && (
                <pre className="mt-2 max-h-48 overflow-y-auto whitespace-pre-wrap border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] p-2.5 font-cyber-data text-[11px] text-[var(--hud-text)]/90">
                  {pageText}
                </pre>
              )}
            </div>
          )}
        </CyberFrame>
      )}

      <div className="flex-1 overflow-y-auto space-y-1.5 pr-1">
        {loading && (
          <div className="py-6 text-center font-cyber-ui text-xs text-[var(--hud-muted)]">
            Loading library...
          </div>
        )}
        {!loading && items.length === 0 && (
          <CyberFrame variant="default" className="p-4 text-center font-cyber-ui text-xs text-[var(--hud-muted)]">
            {rulesIndexed
              ? "No entries matched your filter."
              : "No Corebook PDF uploaded yet. You can upload your PDF in Settings → Corebook PDF, or add custom homebrew entries above."}
          </CyberFrame>
        )}
        {items.map((entry) => {
          const wTier = entry.category === "weapon" ? classifyWeaponTiers(entry) : null;
          const wTheme = wTier && wTier.primaryTier !== "other" ? getWeaponTierTheme(wTier.primaryTier) : null;
          const isSelected = selectedEntry?.id === entry.id;
          return (
            <button
              key={entry.id}
              type="button"
              onClick={() => onSelectEntry(entry)}
              className={`w-full border px-3 py-2 text-left transition-colors ${
                isSelected
                  ? "border-[var(--hud-accent-line)] bg-[var(--hud-accent-navy)]"
                  : wTheme
                    ? wTheme.cardClass
                    : "border-[var(--hud-line-soft)] bg-[var(--hud-panel)] hover:border-[var(--hud-line)] hover:bg-[var(--hud-row)]"
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-1.5 min-w-0">
                  {entry.source === "homebrew" ? (
                    <Sparkles className="h-3.5 w-3.5 shrink-0 text-[var(--hud-warn)]" />
                  ) : (
                    <BookOpen className="h-3.5 w-3.5 shrink-0 text-[var(--hud-accent)]" />
                  )}
                  <span className="truncate font-cyber-ui text-xs font-semibold text-[var(--hud-text)]">
                    {entry.name}
                  </span>
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                  {wTheme && (
                    <span className={`px-1.5 py-0.5 font-cyber-ui text-[9px] font-bold uppercase ${wTheme.badgeClass}`}>
                      {wTheme.label}
                    </span>
                  )}
                  <span className="border border-[var(--hud-line-soft)] bg-[var(--hud-row)] px-1.5 py-0.5 font-cyber-ui text-[10px] font-semibold uppercase tracking-wider text-[var(--hud-label)]">
                    {entry.category}
                  </span>
                  {entry.printed_page && (
                    <span className="border border-[var(--hud-line-soft)] bg-[var(--hud-panel)] px-1.5 py-0.5 font-cyber-data text-[10px] text-[var(--hud-accent)]">
                      p.{entry.printed_page}
                    </span>
                  )}
                </div>
              </div>
              {entry.summary && (
                <p className="mt-1 line-clamp-1 font-cyber-ui text-[11px] text-[var(--hud-muted)]">
                  {entry.summary}
                </p>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
