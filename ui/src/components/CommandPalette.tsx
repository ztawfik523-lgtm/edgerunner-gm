import { Command } from "cmdk";
import { useEffect, useState } from "react";
import { BookOpen, Search, Sparkles, X } from "lucide-react";
import { searchLibrary } from "../api";
import type { LibraryEntry } from "../types";
import { useModalFocus } from "../utils/useModalFocus";
import { classifyWeaponTiers, getWeaponTierTheme } from "../utils/weaponQuality";
import { CyberFrame, HudButton } from "./cyber";

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
  const dialogRef = useModalFocus(open, onClose);

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
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/75 p-4 pt-16 backdrop-blur-xs sm:pt-20 outline-none"
      role="dialog"
      aria-modal="true"
      aria-label="Rulebook & Library Search"
      onClick={onClose}
      ref={dialogRef}
      tabIndex={-1}
    >
      <CyberFrame
        variant="modal"
        className="w-full max-w-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[var(--hud-line)] bg-[#5a0b1c]/55 px-4 py-3 sm:px-5">
          <div className="flex items-center gap-2">
            <BookOpen className="h-4 w-4 shrink-0 text-[var(--hud-accent)]" />
            <h2
              data-text="Rulebook & Library Search"
              className="cp-glitch font-cyber-display text-xs font-semibold uppercase tracking-wider text-[var(--hud-text)] sm:text-sm"
            >
              Rulebook &amp; Library Search
            </h2>
          </div>
          <HudButton
            variant="tactical"
            size="xs"
            onClick={onClose}
            aria-label="Close search"
            className="px-2 py-1"
          >
            <X className="h-4 w-4" />
          </HudButton>
        </div>

        <Command shouldFilter={false} className="w-full">
          <div className="flex items-center border-b border-[var(--hud-line-soft)] bg-black/50 px-3.5">
            <Search className="mr-2.5 h-4 w-4 shrink-0 text-[var(--hud-accent)]" />
            <Command.Input
              autoFocus
              value={query}
              onValueChange={setQuery}
              placeholder="Search Corebook skills, weapons, cyberware, or homebrew..."
              className="w-full bg-transparent py-3 font-cyber-ui text-sm text-[var(--hud-text)] placeholder:text-[var(--hud-muted)]/70 focus:outline-none"
            />
          </div>

          <Command.List className="max-h-96 overflow-y-auto p-2 space-y-1">
            {loading && (
              <div className="px-3 py-6 text-center font-cyber-ui text-xs text-[var(--hud-muted)]">
                Searching rulebook library...
              </div>
            )}
            {!loading && items.length === 0 && (
              <Command.Empty className="px-3 py-8 text-center font-cyber-ui text-xs text-[var(--hud-muted)]">
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
                  className="flex cursor-pointer items-start justify-between gap-3 border border-transparent bg-[var(--hud-row)]/60 px-3 py-2.5 font-cyber-ui text-sm text-[var(--hud-text)] transition aria-selected:border-[var(--hud-accent-line)] aria-selected:bg-[var(--hud-accent-navy)] aria-selected:text-[var(--hud-accent)] hover:border-[var(--hud-line-soft)] hover:bg-[var(--hud-row)]"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      {entry.source === "homebrew" ? (
                        <Sparkles className="h-3.5 w-3.5 shrink-0 text-[var(--hud-warn)]" />
                      ) : (
                        <BookOpen className="h-3.5 w-3.5 shrink-0 text-[var(--hud-accent)]" />
                      )}
                      <span className="truncate font-semibold">{entry.name}</span>
                      {wTheme && (
                        <span className={`px-1.5 py-0.5 font-cyber-data text-[9px] font-bold ${wTheme.badgeClass}`}>
                          {wTheme.label}
                        </span>
                      )}
                      <span className="border border-[var(--hud-line-soft)] bg-black/50 px-1.5 py-0.5 font-cyber-data text-[10px] uppercase text-[var(--hud-muted)]">
                        {entry.category}
                      </span>
                    </div>
                    <p className="mt-0.5 line-clamp-1 font-cyber-ui text-xs text-[var(--hud-muted)]">
                      {entry.summary}
                    </p>
                  </div>
                  <div className="shrink-0 text-right font-cyber-data text-[11px] text-[var(--hud-muted)]">
                    {entry.printed_page ? `p.${entry.printed_page}` : entry.source}
                  </div>
                </Command.Item>
              );
            })}
          </Command.List>
        </Command>
      </CyberFrame>
    </div>
  );
}
