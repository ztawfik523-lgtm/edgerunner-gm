import type { CSSProperties } from "react";

export interface CharacterColorTheme {
  label: string;
  hex: string;
  dotClass: string;
  nameBadgeClass: string;
  cardBorderClass: string;
  avatarRingClass: string;
}

export const CHARACTER_COLOR_THEMES: Record<string, CharacterColorTheme> = {
  cyan: {
    label: "Kiroshi Cyan",
    hex: "#22d3ee",
    dotClass: "bg-cyan-400",
    nameBadgeClass: "border-cyan-400/60 bg-cyan-500/20 text-cyan-200 shadow-[0_0_10px_rgba(34,211,238,0.2)]",
    cardBorderClass: "border-cyan-500/40 bg-[#0b1624]/90",
    avatarRingClass: "ring-cyan-400/70",
  },
  rose: {
    label: "Samurai Crimson",
    hex: "#f43f5e",
    dotClass: "bg-rose-500",
    nameBadgeClass: "border-rose-400/60 bg-rose-500/20 text-rose-200 shadow-[0_0_10px_rgba(244,63,94,0.2)]",
    cardBorderClass: "border-rose-500/40 bg-[#1c0d18]/90",
    avatarRingClass: "ring-rose-400/70",
  },
  amber: {
    label: "Cyber Yellow",
    hex: "#fbbf24",
    dotClass: "bg-amber-400",
    nameBadgeClass: "border-amber-400/60 bg-amber-500/20 text-amber-200 shadow-[0_0_10px_rgba(251,191,36,0.2)]",
    cardBorderClass: "border-amber-500/40 bg-[#1b160b]/90",
    avatarRingClass: "ring-amber-400/70",
  },
  emerald: {
    label: "Biotechnica Green",
    hex: "#34d399",
    dotClass: "bg-emerald-400",
    nameBadgeClass: "border-emerald-400/60 bg-emerald-500/20 text-emerald-200 shadow-[0_0_10px_rgba(52,211,153,0.2)]",
    cardBorderClass: "border-emerald-500/40 bg-[#0a1a17]/90",
    avatarRingClass: "ring-emerald-400/70",
  },
  violet: {
    label: "NetWatch Violet",
    hex: "#a78bfa",
    dotClass: "bg-violet-400",
    nameBadgeClass: "border-violet-400/60 bg-violet-500/20 text-violet-200 shadow-[0_0_10px_rgba(167,139,250,0.2)]",
    cardBorderClass: "border-violet-500/40 bg-[#141024]/90",
    avatarRingClass: "ring-violet-400/70",
  },
  magenta: {
    label: "Mox Magenta",
    hex: "#e879f9",
    dotClass: "bg-fuchsia-400",
    nameBadgeClass: "border-fuchsia-400/60 bg-fuchsia-500/20 text-fuchsia-200 shadow-[0_0_10px_rgba(232,121,249,0.2)]",
    cardBorderClass: "border-fuchsia-500/40 bg-[#1d0e22]/90",
    avatarRingClass: "ring-fuchsia-400/70",
  },
};

export function isHexColor(value: string | undefined | null): value is string {
  return typeof value === "string" && /^#[0-9a-fA-F]{6}$/.test(value.trim());
}

export function normalizeColorHex(color: string | undefined | null): string {
  if (!color) return CHARACTER_COLOR_THEMES.cyan.hex;
  const trimmed = color.trim();
  if (isHexColor(trimmed)) return trimmed.toLowerCase();
  return CHARACTER_COLOR_THEMES[trimmed]?.hex ?? CHARACTER_COLOR_THEMES.cyan.hex;
}

function hexToRgb(hex: string): [number, number, number] {
  const clean = hex.replace("#", "");
  const r = parseInt(clean.slice(0, 2), 16);
  const g = parseInt(clean.slice(2, 4), 16);
  const b = parseInt(clean.slice(4, 6), 16);
  return [r, g, b];
}

function brightenForDarkBg(r: number, g: number, b: number): string {
  // Blend slightly toward light slate so very dark hex colors remain readable as badge text on #0b101b
  const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  if (lum >= 0.48) return `rgb(${r}, ${g}, ${b})`;
  const mix = 0.55;
  return `rgb(${Math.round(r + (241 - r) * mix)}, ${Math.round(g + (245 - g) * mix)}, ${Math.round(b + (249 - b) * mix)})`;
}

export interface ResolvedCharacterColor {
  id: string;
  hex: string;
  isHex: boolean;
  preset?: CharacterColorTheme;
  dotClass: string;
  dotStyle?: CSSProperties;
  nameBadgeClass: string;
  nameBadgeStyle?: CSSProperties;
  cardBorderClass: string;
  cardBorderStyle?: CSSProperties;
  avatarRingClass: string;
  avatarRingStyle?: CSSProperties;
}

export function resolveCharacterColor(colorId?: string | null): ResolvedCharacterColor {
  const trimmed = typeof colorId === "string" ? colorId.trim() : "";
  const preset = CHARACTER_COLOR_THEMES[trimmed];
  if (preset) {
    return {
      id: trimmed,
      hex: preset.hex,
      isHex: false,
      preset,
      dotClass: preset.dotClass,
      nameBadgeClass: preset.nameBadgeClass,
      cardBorderClass: preset.cardBorderClass,
      avatarRingClass: preset.avatarRingClass,
    };
  }
  if (isHexColor(trimmed)) {
    const hex = trimmed.toLowerCase();
    const [r, g, b] = hexToRgb(hex);
    const readableText = brightenForDarkBg(r, g, b);
    return {
      id: hex,
      hex,
      isHex: true,
      dotClass: "",
      dotStyle: { backgroundColor: hex },
      nameBadgeClass: "",
      nameBadgeStyle: {
        borderColor: `rgba(${r}, ${g}, ${b}, 0.65)`,
        backgroundColor: `rgba(${r}, ${g}, ${b}, 0.2)`,
        color: readableText,
        boxShadow: `0 0 10px rgba(${r}, ${g}, ${b}, 0.22)`,
      },
      cardBorderClass: "",
      cardBorderStyle: {
        borderColor: `rgba(${r}, ${g}, ${b}, 0.45)`,
        backgroundColor: `rgba(${Math.round(r * 0.16 + 10)}, ${Math.round(g * 0.16 + 14)}, ${Math.round(b * 0.16 + 22)}, 0.92)`,
      },
      avatarRingClass: "",
      avatarRingStyle: {
        boxShadow: `0 0 0 2px rgba(${r}, ${g}, ${b}, 0.78)`,
      },
    };
  }
  return resolveCharacterColor("cyan");
}
