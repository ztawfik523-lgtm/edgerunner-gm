import { useEffect, useState } from "react";
import { BookOpen, FileText, Plus, Search, Sparkles, Trash2 } from "lucide-react";
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
    <div className="flex h-full flex-col p-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-2 h-3.5 w-3.5 text-slate-400" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter weapons, programs, vehicles, mooks, screamsheets, streetslang..."
            className="w-full rounded-md border border-slate-700 bg-slate-950 py-1.5 pl-8 pr-3 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
          />
        </div>

        {campaignId && (
          <button
            type="button"
            onClick={() => setCreating((v) => !v)}
            className="inline-flex items-center gap-1 rounded-md border border-amber-500/40 bg-amber-500/10 px-2.5 py-1.5 text-xs font-medium text-amber-300 hover:bg-amber-500/20"
          >
            <Plus className="h-3.5 w-3.5" />
            Homebrew
          </button>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <select
          aria-label="Category filter"
          value={category}
          onChange={(e) => setCategory(e.target.value as LibraryCategory | "")}
          className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200"
        >
          <option value="">All categories</option>
          {LIBRARY_CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {categoryLabel(c)}
            </option>
          ))}
        </select>

        {(["all", "corebook", "homebrew"] as const).map((src) => (
          <button
            key={src}
            type="button"
            onClick={() => setSourceFilter(src)}
            className={`rounded px-2 py-1 text-xs capitalize ${
              sourceFilter === src
                ? "bg-cyan-600 text-white"
                : "border border-slate-700 bg-slate-900 text-slate-400 hover:text-slate-200"
            }`}
          >
            {src}
          </button>
        ))}
      </div>

      {creating && (
        <form
          onSubmit={handleCreateHomebrew}
          onKeyDown={(e) => {
            if (e.key === "Escape") setCreating(false);
          }}
          className="space-y-2.5 rounded-lg border border-amber-500/40 bg-[#131928] p-3"
        >
          <div className="text-xs font-semibold text-amber-300">New Campaign Homebrew</div>
          <div className="grid grid-cols-2 gap-2">
            <input
              type="text"
              required
              value={hbName}
              onChange={(e) => setHbName(e.target.value)}
              placeholder="Entry name (item, NPC, faction, location, rule)"
              className="rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100"
            />
            <select
              value={hbCat}
              onChange={(e) => setHbCat(e.target.value as LibraryCategory)}
              className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-100"
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
            className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100"
          />
          <textarea
            rows={2}
            value={hbDesc}
            onChange={(e) => setHbDesc(e.target.value)}
            placeholder="Full mechanics & flavor description..."
            className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100"
          />
          <div className="grid grid-cols-3 gap-2">
            <input
              type="number"
              min={0}
              value={hbCost}
              onChange={(e) => setHbCost(e.target.value)}
              placeholder="Cost (eb)"
              className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
            />
            <input
              type="text"
              value={hbDamage}
              onChange={(e) => setHbDamage(e.target.value)}
              placeholder="Damage (e.g. 3d6)"
              className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
            />
            <input
              type="text"
              value={hbStat}
              onChange={(e) => setHbStat(e.target.value)}
              placeholder="Skill Stat (e.g. TECH)"
              className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
            />
          </div>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setCreating(false)}
              className="px-2.5 py-1 text-xs text-slate-400"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={busy}
              className="rounded bg-amber-600 px-3 py-1 text-xs font-semibold text-white hover:bg-amber-500"
            >
              Save Homebrew
            </button>
          </div>
        </form>
      )}

      {selectedEntry && (
        <div className="rounded-lg border border-cyan-500/40 bg-[#11192b] p-3 space-y-2">
          <div className="flex items-start justify-between gap-2">
            <div>
              <div className="flex items-center gap-2">
                <h4 className="text-sm font-bold text-slate-100">{selectedEntry.name}</h4>
                <span className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[10px] uppercase text-cyan-300">
                  {selectedEntry.category}
                </span>
                {selectedEntry.printed_page && (
                  <span className="font-mono text-[11px] text-slate-400">
                    p.{selectedEntry.printed_page}
                  </span>
                )}
              </div>
              <p className="mt-1 text-xs text-slate-300">{selectedEntry.description || selectedEntry.summary}</p>
            </div>

            <div className="flex items-center gap-1">
              {selectedEntry.source === "homebrew" && (
                confirmDeleteId === selectedEntry.id ? (
                  <div className="inline-flex items-center gap-1.5 rounded border border-rose-500/40 bg-rose-500/10 px-1.5 py-0.5 font-mono text-[10px]">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => {
                        setConfirmDeleteId(null);
                        void handleDeleteHomebrew(selectedEntry);
                      }}
                      className="font-semibold text-rose-300 hover:text-rose-200 disabled:opacity-40"
                    >
                      Delete
                    </button>
                    <button
                      type="button"
                      onClick={() => setConfirmDeleteId(null)}
                      className="text-slate-400 hover:text-slate-200"
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => setConfirmDeleteId(selectedEntry.id)}
                    title="Delete homebrew entry"
                    aria-label="Delete homebrew entry"
                    className="rounded p-1 text-slate-400 hover:text-rose-400 disabled:opacity-40"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                )
              )}
              <button
                type="button"
                onClick={() => onSelectEntry(null)}
                aria-label="Close entry details"
                className="rounded px-1.5 py-0.5 text-xs text-slate-400 hover:text-slate-200"
              >
                Close
              </button>
            </div>
          </div>

          {Object.keys(selectedEntry.stats ?? {}).length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(selectedEntry.stats).map(([k, v]) => (
                <span
                  key={k}
                  className="rounded border border-slate-700 bg-slate-900 px-2 py-0.5 font-mono text-[11px] text-slate-200"
                >
                  {k}: {String(v)}
                </span>
              ))}
            </div>
          )}

          {rulesIndexed && selectedEntry.printed_page && (
            <div>
              <button
                type="button"
                disabled={pageLoading}
                onClick={() => handleLoadPage(selectedEntry.printed_page!)}
                className="inline-flex items-center gap-1 text-xs text-cyan-400 hover:text-cyan-300"
              >
                <FileText className="h-3.5 w-3.5" />
                {pageLoading ? "Loading page..." : `Read Corebook p.${selectedEntry.printed_page}`}
              </button>
              {pageText && (
                <pre className="mt-2 max-h-48 overflow-y-auto whitespace-pre-wrap rounded border border-slate-800 bg-slate-950 p-2.5 font-mono text-[11px] text-slate-300">
                  {pageText}
                </pre>
              )}
            </div>
          )}
        </div>
      )}

      <div className="flex-1 overflow-y-auto space-y-1.5 pr-1">
        {loading && (
          <div className="py-6 text-center text-xs text-slate-400">Loading library...</div>
        )}
        {!loading && items.length === 0 && (
          <div className="rounded-lg border border-slate-800 bg-[#111726] p-4 text-center text-xs text-slate-400">
            {rulesIndexed
              ? "No entries matched your filter."
              : "No Corebook PDF uploaded yet. You can upload your PDF in Settings → Corebook PDF, or add custom homebrew entries above."}
          </div>
        )}
        {items.map((entry) => (
          <button
            key={entry.id}
            type="button"
            onClick={() => onSelectEntry(entry)}
            className={`w-full rounded-lg border px-3 py-2 text-left transition ${
              selectedEntry?.id === entry.id
                ? "border-cyan-500/60 bg-cyan-950/30"
                : "border-slate-800 bg-[#111726] hover:border-slate-700"
            }`}
          >
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-1.5 min-w-0">
                {entry.source === "homebrew" ? (
                  <Sparkles className="h-3.5 w-3.5 shrink-0 text-amber-400" />
                ) : (
                  <BookOpen className="h-3.5 w-3.5 shrink-0 text-cyan-400" />
                )}
                <span className="truncate text-xs font-semibold text-slate-100">{entry.name}</span>
              </div>
              <div className="flex items-center gap-1.5 shrink-0">
                <span className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[10px] uppercase text-slate-300">
                  {entry.category}
                </span>
                {entry.printed_page && (
                  <span className="font-mono text-[10px] text-slate-400">
                    p.{entry.printed_page}
                  </span>
                )}
              </div>
            </div>
            {entry.summary && (
              <p className="mt-1 line-clamp-1 text-[11px] text-slate-400">{entry.summary}</p>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}
