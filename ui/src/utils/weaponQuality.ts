export type WeaponTierFilter = "poor" | "standard" | "excellent" | "exotic";
export type WeaponTier = WeaponTierFilter | "exotic_excellent" | "other";
export type WeaponGenre = "pistols" | "rifles" | "heavy" | "melee" | "attachment" | "ammo";

export interface WeaponTierClassification {
  primaryTier: WeaponTier;
  tiers: WeaponTierFilter[];
  sortRank: number;
}

export interface WeaponTierTheme {
  label: string;
  cardClass: string;
  badgeClass: string;
  dotClass: string;
  pillActiveClass: string;
}

const TIER_THEMES: Record<WeaponTier, WeaponTierTheme> = {
  poor: {
    label: "POOR",
    cardClass: "cyber-card",
    badgeClass: "border border-stone-500/50 bg-stone-800/70 text-stone-300",
    dotClass: "bg-stone-400",
    pillActiveClass: "border-stone-400/70 bg-stone-600/30 text-stone-100",
  },
  standard: {
    label: "STANDARD",
    cardClass: "cyber-card",
    badgeClass: "border border-sky-500/45 bg-sky-500/15 text-sky-300",
    dotClass: "bg-sky-400",
    pillActiveClass: "border-sky-400/70 bg-sky-500/20 text-sky-100",
  },
  excellent: {
    label: "EXCELLENT +1",
    cardClass: "cyber-card",
    badgeClass: "border border-emerald-400/55 bg-emerald-500/20 text-emerald-200",
    dotClass: "bg-emerald-400",
    pillActiveClass: "border-emerald-400/70 bg-emerald-500/25 text-emerald-100",
  },
  exotic: {
    label: "EXOTIC",
    cardClass: "cyber-card",
    badgeClass: "border border-fuchsia-400/60 bg-fuchsia-500/25 text-fuchsia-200",
    dotClass: "bg-fuchsia-400",
    pillActiveClass: "border-fuchsia-400/75 bg-fuchsia-500/25 text-fuchsia-100",
  },
  exotic_excellent: {
    label: "EXOTIC · +1 HIT",
    cardClass: "cyber-card",
    badgeClass: "border border-amber-400/65 bg-amber-500/20 text-amber-200",
    dotClass: "bg-amber-400",
    pillActiveClass: "border-amber-400/75 bg-amber-500/25 text-amber-100",
  },
  other: {
    label: "MOD / AMMO",
    cardClass: "cyber-card",
    badgeClass: "border border-slate-700 bg-slate-800/70 text-slate-300",
    dotClass: "bg-slate-400",
    pillActiveClass: "border-cyan-400/60 bg-cyan-500/20 text-cyan-100",
  },
};

export function getWeaponTierTheme(tier: WeaponTier): WeaponTierTheme {
  return TIER_THEMES[tier] ?? TIER_THEMES.other;
}

export function classifyWeaponTiers(
  item: { name: string; category?: string; summary?: string; description?: string; stats?: Record<string, unknown> },
): WeaponTierClassification {
  const stats = item.stats ?? {};
  const q = String(stats.quality ?? "").toLowerCase();
  const st = String(stats.subtype ?? "").toLowerCase();
  const cat = String(item.category ?? "").toLowerCase();
  const text = `${item.name} ${item.summary ?? ""} ${item.description ?? ""}`.toLowerCase();

  if (
    cat === "attachment" ||
    cat === "ammo" ||
    st === "attachment" ||
    st.includes("ammo") ||
    st.includes("ammunition") ||
    q === "attachment"
  ) {
    return { primaryTier: "other", tiers: [], sortRank: 99 };
  }

  const isExotic =
    String(stats.weapon_class ?? "").toLowerCase() === "exotic" ||
    st.includes("exotic") ||
    q.includes("exotic") ||
    /\bexotic\b/i.test(item.name);
  const isExcellent = q.includes("excellent") || st.includes("excellent") || /\bexcellent\b/i.test(item.name);
  const isPoor = q.includes("poor") || st.includes("poor") || /\bpoor\b/i.test(item.name);

  if (isExotic && isExcellent) {
    return { primaryTier: "exotic_excellent", tiers: ["exotic", "excellent"], sortRank: 5 };
  }
  if (isExotic) {
    return { primaryTier: "exotic", tiers: ["exotic"], sortRank: 4 };
  }
  if (isExcellent) {
    return { primaryTier: "excellent", tiers: ["excellent"], sortRank: 3 };
  }
  if (isPoor) {
    return { primaryTier: "poor", tiers: ["poor"], sortRank: 1 };
  }
  if (q.includes("standard") || st.includes("standard") || text.includes("standard") || cat === "weapon") {
    return { primaryTier: "standard", tiers: ["standard"], sortRank: 2 };
  }
  return { primaryTier: "other", tiers: [], sortRank: 99 };
}

export function classifyWeaponGenre(
  item: { name: string; category?: string; summary?: string; description?: string; stats?: Record<string, unknown> },
): WeaponGenre {
  const stats = item.stats ?? {};
  const cat = String(item.category ?? "").toLowerCase();
  const st = String(stats.subtype ?? "").toLowerCase();
  const wc = String(stats.weapon_class ?? "").toLowerCase();
  const sk = String(stats.skill ?? "").toLowerCase();
  const text = `${item.name} ${item.summary ?? ""} ${item.description ?? ""}`.toLowerCase();

  if (cat === "attachment" || st.includes("attachment") || wc === "attachment" || sk === "weapon mod") {
    return "attachment";
  }
  if (cat === "ammo" || st.includes("ammo") || st.includes("ammunition") || wc === "ammo") {
    return "ammo";
  }
  if (
    wc === "heavy" ||
    sk.includes("heavy weapons") ||
    /grenade launcher|rocket launcher|flamethrower|railgun|cowboy/i.test(text)
  ) {
    return "heavy";
  }
  if (
    wc === "melee" ||
    wc === "brawling" ||
    sk.includes("melee") ||
    sk.includes("brawling") ||
    st === "melee" ||
    /knife|tomahawk|machete|baseball bat|katana|sword|spiked bat|naginata|chainsaw|sledgehammer|stun baton|kendachi mono-three|battleglove/i.test(
      text,
    )
  ) {
    return "melee";
  }
  if (
    wc === "pistol" ||
    wc === "smg" ||
    sk.includes("handgun") ||
    /pistol|\bsmg\b|microwaver|dartgun|shrieker|stun gun|malorian/i.test(text)
  ) {
    return "pistols";
  }
  if (
    wc === "rifle" ||
    wc === "shotgun" ||
    wc === "bow" ||
    sk.includes("shoulder arms") ||
    sk.includes("archery") ||
    sk.includes("autofire") ||
    /rifle|shotgun|crossbow|\bbow\b|hurricane|helix/i.test(text)
  ) {
    return "rifles";
  }
  return "pistols";
}

export function inferWeaponTierFromName(name: string): WeaponTier | null {
  const n = (name || "").toLowerCase();
  if (!n) return null;
  if (
    /\b(ammo|ammunition|shells?|rounds?|slugs?|arrows?|bolts?|magazine|drum|clip|holster|scope|sight|suppressor|silencer|bayonet|sling|smartgun link|laser|battery|pack|pad|pads|armor|armorjack|kevlar|leathers|helmet|shield|cyberdeck|program|chip|agent|medtech|stim|grenade pouch)\b/i.test(
      n,
    )
  ) {
    return null;
  }
  const isExotic =
    /\bexotic\b|microwaver|shrieker|dartgun|air pistol|stun gun|stun baton|flamethrower|battleglove|malorian|kendachi mono-three|hurricane|cowboy|railgun|helix/i.test(
      n,
    );
  const isExcellent =
    /\bexcellent\b|avenger|cityhunter|boomer buster|minami 10|viper|bulldog|dragon|sniper system|bearcat|scorpion|type-18|hotshot|masterwork|malorian|kendachi mono-three/i.test(
      n,
    );
  const isPoor =
    /\bpoor\b|dai lung|super chief|tech-assault|city reaper|home defender|jungle reaper|snipe-star|sherwood|gunmart|towa manufacturing/i.test(
      n,
    );
  if (isExotic && isExcellent) return "exotic_excellent";
  if (isExotic) return "exotic";
  if (isExcellent) return "excellent";
  if (isPoor) return "poor";
  if (
    /\b(pistol|smg|rifle|shotgun|bow|crossbow|launcher|knife|tomahawk|machete|bat|katana|sword|naginata|chainsaw|sledgehammer)\b/i.test(
      n,
    )
  ) {
    return "standard";
  }
  return null;
}
