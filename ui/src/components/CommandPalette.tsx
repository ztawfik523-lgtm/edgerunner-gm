import { Command } from "cmdk";
import { useEffect, useState } from "react";
import { BookOpen, Search, Sparkles, X } from "lucide-react";
import { searchLibrary } from "../api";
import type { LibraryEntry } from "../types";
import { classifyWeaponTiers, getWeaponTierTheme } from "../utils/weaponQuality";

interface CommandPaletteProps {
  open: boolean;
  campaignId: string | null;
  onClose: () => void;
  onSelectEntry: (entry: LibraryEntry) => void;
}

export function CommandPalette({ open, campaignId, onClose, onSelectEntry }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<LibraryEntry[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    const timer = setTimeout(() => {
      searchLibrary({
        q: query,
        campaignId: campaignId ?? undefined,
        limit: 25,
      })
        .then((res) => {
          if (!cancelled) setItems(res);
        })
        .catch(() => {
          if (!cancelled) setItems([]);
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 120);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [open, query, campaignId]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/70 pt-20 p-4 backdrop-blur-xs"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl overflow-hidden rounded-xl border border-slate-700 bg-[#0e1420] shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <Command shouldFilter={false} className="w-full">
          <div className="flex items-center border-b border-slate-800 px-3.5">
            <Search className="mr-2.5 h-4 w-4 text-cyan-400" />
            <Command.Input
              autoFocus
              value={query}
              onValueChange={setQuery}
              placeholder="Search Corebook skills, weapons, cyberware, or homebrew..."
              className="w-full bg-transparent py-3.5 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none"
            />
            <button
              type="button"
              onClick={onClose}
              className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-slate-200"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <Command.List className="max-h-96 overflow-y-auto p-2">
            {loading && (
              <div className="px-3 py-6 text-center text-xs text-slate-400">
                Searching rulebook library...
              </div>
            )}
            {!loading && items.length === 0 && (
              <Command.Empty className="px-3 py-8 text-center text-xs text-slate-400">
                No matching Corebook or homebrew entries found.
              </Command.Empty>
            )}
            {items.map((entry) => {
              const wTier = entry.category === "weapon" ? classifyWeaponTiers(entry) : null;
              const wTheme = wTier && wTier.primaryTier !== "other" ? getWeaponTierTheme(wTier.primaryTier) : null;
              return (
              <Command.Item
                key={entry.id}
                value={entry.id}
                onSelect={() => {
                  onSelectEntry(entry);
                  onClose();
                }}
                className="flex cursor-pointer items-start justify-between gap-3 rounded-lg px-3 py-2.5 text-sm text-slate-200 aria-selected:bg-slate-800/80 aria-selected:text-white hover:bg-slate-800/60"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    {entry.source === "homebrew" ? (
                      <Sparkles className="h-3.5 w-3.5 shrink-0 text-amber-400" />
                    ) : (
                      <BookOpen className="h-3.5 w-3.5 shrink-0 text-cyan-400" />
                    )}
                    <span className="truncate font-semibold">{entry.name}</span>
                    {wTheme && (
                      <span className={`rounded px-1.5 py-0.5 font-mono text-[9px] font-bold ${wTheme.badgeClass}`}>
                        {wTheme.label}
                      </span>
                    )}
                    <span className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[10px] uppercase text-slate-300">
                      {entry.category}
                    </span>
                  </div>
                  <p className="mt-0.5 line-clamp-1 text-xs text-slate-400">{entry.summary}</p>
                </div>
                <div className="shrink-0 text-right font-mono text-[11px] text-slate-400">
                  {entry.printed_page ? `p.${entry.printed_page}` : entry.source}
                </div>
              </Command.Item>
              );
            })}
          </Command.List>
        </Command>
      </div>
    </div>
  );
}
