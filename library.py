"""Organized Rulebook Library and campaign-scoped homebrew catalog."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import unicodedata
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from campaign import CampaignStore, STAT_NAMES, _json
from index_lock import index_lock
from memory import CampaignMemory
import sourcecatalog

ALLOWED_CATEGORIES = frozenset(
    {
        "skill",
        "weapon",
        "armor",
        "cyberware",
        "program",
        "hardware",
        "gear",
        "fashion",
        "role",
        "rule",
        "npc",
        "faction",
        "location",
        "vehicle",
        "drug",
        "ammo",
        "attachment",
        "housing",
        "service",
        "streetslang",
        "mook",
        "encounter",
        "screamsheet",
    }
)
ROLE_NAMES = frozenset(
    {"solo", "netrunner", "tech", "medtech", "media", "exec", "lawman", "fixer", "nomad", "rockerboy"}
)
_DICE_RE = re.compile(r"^\d{1,2}d(?:6|10)(?:\s*[+-]\s*\d{1,2})?$", re.I)
_CATEGORY_ALIASES = {
    "skills": "skill",
    "weapons": "weapon",
    "armors": "armor",
    "cyberwares": "cyberware",
    "programs": "program",
    "roles": "role",
    "rules": "rule",
    "npcs": "npc",
    "factions": "faction",
    "locations": "location",
    "vehicles": "vehicle",
    "drugs": "drug",
    "ammos": "ammo",
    "ammunition": "ammo",
    "attachments": "attachment",
    "housings": "housing",
    "services": "service",
    "streetslangs": "streetslang",
    "slang": "streetslang",
    "mooks": "mook",
    "opponent": "mook",
    "opponents": "mook",
    "encounters": "encounter",
    "screamsheets": "screamsheet",
    "exotic": "weapon",
    "exotics": "weapon",
}

_CACHE_LOCK = threading.Lock()
_MEMORY_CACHE: dict[tuple[str, int, int, str], list[dict[str, Any]]] = {}


def _slug(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-") or "entry"


def normalize_category(category: str | None) -> str | None:
    if category is None:
        return None
    if not isinstance(category, str):
        raise ValueError("category must be a string")
    value = _CATEGORY_ALIASES.get(category.strip().casefold(), category.strip().casefold())
    if value not in ALLOWED_CATEGORIES:
        raise ValueError(f"Unsupported library category: {category!r}")
    return value


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def _summarize(text: str, limit: int = 180) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return ""
    sentence = re.split(r"(?<=[.!?])\s+", cleaned, maxsplit=1)[0]
    chosen = sentence if len(sentence) <= limit else cleaned
    if len(chosen) <= limit:
        return chosen
    return chosen[: limit - 1].rstrip() + "…"


def _clean_prose(lines: list[str]) -> str:
    joined = "\n".join(line.strip() for line in lines if line.strip())
    joined = re.sub(r"(\w)-\n(\w)", r"\1\2", joined)
    joined = re.sub(r"\s*\n+\s*", " ", joined)
    return re.sub(r"\s+", " ", joined).strip()


def _extract_skill_entries(
    pages: list[sqlite3.Row], digest: str
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen_norm: set[str] = set()
    current: dict[str, Any] | None = None
    body_lines: list[str] = []

    def flush() -> None:
        nonlocal current, body_lines
        if current is None:
            return
        desc = _clean_prose(body_lines)
        stat = current["stat"]
        cost = current["cost"]
        specializable = current["specializable"]
        if not desc:
            spec_note = " Specializable skill." if specializable else ""
            cost_note = " (2x Improvement Point cost)" if cost == 2 else ""
            desc = f"{current['name']} ({stat}){cost_note}.{spec_note}".strip()
        tags = ["skill", stat.lower()]
        if cost == 2:
            tags.append("x2")
        if specializable:
            tags.append("specializable")
        entries.append(
            {
                "id": f"corebook:skill:{_slug(current['name'])}",
                "name": current["name"],
                "norm_name": sourcecatalog._normalize(current["name"]),
                "category": "skill",
                "source": "corebook",
                "summary": _summarize(desc),
                "description": desc,
                "stats": {
                    "stat": stat,
                    "cost_multiplier": cost,
                    "specializable": specializable,
                },
                "tags": tags,
                "pdf_page": current["pdf_page"],
                "printed_page": current["printed_page"],
                "section_id": None,
                "source_sha256": digest,
            }
        )
        current = None
        body_lines = []

    for row in pages:
        printed = row["printed_page"]
        if printed is None:
            printed = next(
                (int(line.strip()) for line in str(row["text"]).splitlines()[:4]
                 if re.fullmatch(r"8[2-5]", line.strip())),
                None,
            )
        if printed is None or not 82 <= int(printed) <= 85:
            continue
        for raw_line in str(row["text"]).splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped == str(printed):
                continue
            match = sourcecatalog._HEADER.fullmatch(stripped)
            if match:
                raw_name, stat = match.groups()
                cost = 2 if re.search(r"\(\s*x\s*2\s*\)\s*$", raw_name, re.I) else 1
                name = re.sub(r"\s*\(\s*x\s*2\s*\)\s*$", "", raw_name, flags=re.I)
                name = re.sub(r"[.\s]+$", "", name).strip()
                norm = sourcecatalog._normalize(name)
                flush()
                if norm in seen_norm:
                    continue
                seen_norm.add(norm)
                current = {
                    "name": name,
                    "norm_name": norm,
                    "stat": stat.upper(),
                    "cost": cost,
                    "specializable": norm in sourcecatalog._SPECIALIZABLE,
                    "pdf_page": int(row["pdf_page"]),
                    "printed_page": int(printed),
                }
            elif current is not None:
                if stripped.startswith("Supplemental extracted table rows"):
                    continue
                body_lines.append(stripped)
    flush()
    return entries


def _parse_hl_int(raw: Any) -> int:
    if isinstance(raw, int) and not isinstance(raw, bool):
        return max(0, raw)
    if isinstance(raw, str):
        m = re.match(r"^\s*(\d+)", raw.strip())
        if m:
            return int(m.group(1))
    return 0


def _parse_item_stats(headers: list[str], cells: list[str], cost_eb: int) -> tuple[dict[str, Any], list[str]]:
    stats: dict[str, Any] = {"cost_eb": cost_eb}
    notes: list[str] = []
    skip_cols = (sourcecatalog._NAME_HEADER_KEYS | sourcecatalog._COST_HEADER_KEYS) - {"style", "garment"}
    for idx, header in enumerate(headers):
        if idx >= len(cells):
            break
        val = cells[idx].strip()
        if not val:
            continue
        norm_h = re.sub(r"[^a-z]", "", header.casefold())
        if norm_h in skip_cols:
            if norm_h in {"rent", "renteb", "rentebmo", "monthlyeb"}:
                parsed_rent = sourcecatalog._cost(val, allow_bare_int=True)
                if parsed_rent is not None:
                    stats["rent_eb_mo"] = parsed_rent
            continue
        if norm_h in {"description", "notes", "effect", "data", "details", "examples", "summary"}:
            notes.append(val)
            continue
        if norm_h in {"dmg", "damage"}:
            stats["damage"] = val
        elif norm_h == "rof":
            stats["rof"] = int(val) if val.isdigit() else val
        elif norm_h in {"sp", "stoppingpower"}:
            stats["sp"] = int(val) if val.isdigit() else val
        elif norm_h in {"penalty", "armorpenalty"}:
            stats["armor_penalty"] = int(val) if re.fullmatch(r"-?\d+", val) else val
        elif norm_h in {"hl", "humanityloss"}:
            stats["humanity_loss"] = int(val) if val.isdigit() else val
            stats["hl"] = _parse_hl_int(val)
        elif norm_h in {"install", "installation"}:
            stats["install"] = val
        elif norm_h in {"skill", "weaponskill"}:
            stats["skill"] = val
        elif norm_h in {"magazine", "mag", "capacity"}:
            stats["magazine"] = int(val) if val.isdigit() else val
        elif norm_h in {"hands", "handsrequired"}:
            stats["hands"] = int(val) if val.isdigit() else val
        elif norm_h in {"concealable", "conceal", "concealability"}:
            low = val.casefold()
            stats["concealable"] = True if low in {"yes", "true", "y"} else (False if low in {"no", "false", "n"} else val)
        elif norm_h in {"buy", "buyeb"}:
            parsed_buy = sourcecatalog._cost(val, allow_bare_int=True)
            stats["buy_eb"] = parsed_buy if parsed_buy is not None else val
        elif norm_h in {"atk", "per", "def", "spd", "rez", "class", "sdp", "seats", "interface", "netactions", "combatnumber", "ablation", "resistdv", "bodyreq", "slots", "slotsrequired"}:
            key_map = {
                "netactions": "net_actions",
                "combatnumber": "combat_number",
                "resistdv": "resist_dv",
                "bodyreq": "body_req",
            }
            out_key = key_map.get(norm_h, norm_h)
            stats[out_key] = int(val) if re.fullmatch(r"-?\d+", val) else val
        else:
            key = re.sub(r"[^a-z0-9]+", "_", header.strip().casefold()).strip("_")
            if key:
                stats[key] = val
    return stats, notes


def _extract_item_entries(
    conn: sqlite3.Connection, pages: list[sqlite3.Row], digest: str
) -> list[dict[str, Any]]:
    stored: dict[int, list[list[list[str]]]] = {}
    if _table_exists(conn, "source_tables"):
        for row in conn.execute("SELECT pdf_page,ordinal,cells_json FROM source_tables ORDER BY pdf_page,ordinal"):
            stored.setdefault(int(row["pdf_page"]), []).append(sourcecatalog._cell_rows(row["cells_json"]))

    entries: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for page in pages:
        printed = sourcecatalog._page_number(page)
        pdf_page = int(page["pdf_page"])
        for table_no, rows in enumerate(sourcecatalog._tables_for_page(page, stored.get(pdf_page, [])), 1):
            if len(rows) < 2:
                continue
            header_index = next(
                (i for i, r in enumerate(rows)
                 if any(re.sub(r"[^a-z]", "", c.casefold()) in sourcecatalog._COST_HEADER_KEYS for c in r)),
                None,
            )
            if header_index is None:
                continue
            headers = rows[header_index]
            norm_headers = [re.sub(r"[^a-z]", "", h.casefold()) for h in headers]
            name_col = next(
                (i for i, h in enumerate(norm_headers) if h in sourcecatalog._NAME_HEADER_KEYS),
                None,
            )
            cost_col = next(
                (i for i, h in enumerate(norm_headers) if h in sourcecatalog._COST_HEADER_KEYS),
                None,
            )
            if name_col is None or cost_col is None:
                continue
            allow_bare = norm_headers[cost_col] in sourcecatalog._EB_HEADER_KEYS
            category = sourcecatalog._category(headers)
            for row_no, cells in enumerate(rows[header_index + 1:], header_index + 1):
                if max(name_col, cost_col) >= len(cells):
                    continue
                name = cells[name_col].strip()
                cost_eb = sourcecatalog._cost(cells[cost_col], allow_bare_int=allow_bare)
                if not name or cost_eb is None:
                    continue
                stats, notes = _parse_item_stats(headers, cells, cost_eb)
                stat_bits = [f"{k}={v}" for k, v in stats.items() if k != "cost_eb"]
                desc = " ".join(notes).strip()
                if not desc:
                    details = f" ({', '.join(stat_bits)})" if stat_bits else ""
                    desc = f"{name}: {category} priced at {cost_eb}eb{details}."
                elif stat_bits:
                    desc = f"{desc} [{', '.join(stat_bits)}, cost {cost_eb}eb]"
                base_id = f"corebook:{category}:{_slug(name)}"
                entry_id = base_id if base_id not in used_ids else f"{base_id}-p{pdf_page}-t{table_no}-r{row_no}"
                used_ids.add(entry_id)
                tags = [category, f"{cost_eb}eb"]
                if "lifestyle" in " ".join(norm_headers) or name.casefold().startswith("lifestyle:"):
                    tags.append("lifestyle")
                entries.append(
                    {
                        "id": entry_id,
                        "name": name,
                        "norm_name": sourcecatalog._normalize(name),
                        "category": category,
                        "source": "corebook",
                        "summary": _summarize(desc),
                        "description": desc,
                        "stats": stats,
                        "tags": tags,
                        "pdf_page": pdf_page,
                        "printed_page": printed,
                        "section_id": None,
                        "source_sha256": digest,
                    }
                )
    return entries


_LIFEPATH_TABLE_ALIASES: dict[str, tuple[str, ...]] = {
    "personality": ("personality",),
    "clothing_style": ("clothing style", "clothing"),
    "hairstyle": ("hairstyle", "hair style"),
    "affectation": ("affectation", "affectations"),
    "value_most": ("what do you value most", "value most"),
    "feelings_about_people": ("how do you feel about most people", "feelings about people"),
    "valued_person": ("most valued person", "valued person"),
    "valued_possession": ("most valued possession", "valued possession"),
    "original_background": ("original background", "family background"),
    "childhood_environment": ("childhood environment",),
    "family_crisis": ("family crisis",),
    "life_goals": ("life goals",),
    "friend_relationship": ("friend relationship", "friends", "who is this friend"),
    "enemy_who": ("enemy who", "who is this enemy"),
    "enemy_cause": ("enemy cause", "what caused it"),
    "enemy_backup": ("enemy backup", "what can they throw at you"),
    "sweet_revenge": ("sweet revenge", "what are you gonna do"),
    "tragic_love": ("tragic love", "tragic love affairs"),
}


def _match_lifepath_key(label: str) -> str | None:
    low = re.sub(r"[^a-z0-9 ]+", " ", label.casefold()).strip()
    for key, aliases in _LIFEPATH_TABLE_ALIASES.items():
        if any(alias in low for alias in aliases):
            return key
    return None


def _extract_structured_table_entries(
    conn: sqlite3.Connection, pages: list[sqlite3.Row], digest: str
) -> list[dict[str, Any]]:
    stored: dict[int, list[list[list[str]]]] = {}
    if _table_exists(conn, "source_tables"):
        for row in conn.execute("SELECT pdf_page,ordinal,cells_json FROM source_tables ORDER BY pdf_page,ordinal"):
            stored.setdefault(int(row["pdf_page"]), []).append(sourcecatalog._cell_rows(row["cells_json"]))

    entries: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for page in pages:
        printed = sourcecatalog._page_number(page)
        pdf_page = int(page["pdf_page"])
        page_lines = [ln.strip() for ln in str(page["text"]).splitlines() if ln.strip()]
        page_heading = page_lines[1] if len(page_lines) > 1 and page_lines[0].isdigit() else (page_lines[0] if page_lines else "")

        for table_no, rows in enumerate(sourcecatalog._tables_for_page(page, stored.get(pdf_page, [])), 1):
            if len(rows) < 2:
                continue
            headers = rows[0]
            norm_headers = [re.sub(r"[^a-z0-9]", "", h.casefold()) for h in headers]

            # 1. Cultural Regions table
            if "region" in norm_headers and any("language" in h for h in norm_headers):
                reg_col = norm_headers.index("region")
                lang_col = next(i for i, h in enumerate(norm_headers) if "language" in h)
                regions = []
                for cells in rows[1:]:
                    if max(reg_col, lang_col) >= len(cells):
                        continue
                    reg = cells[reg_col].strip()
                    langs = [x.strip() for x in re.split(r"[,;/]", cells[lang_col]) if x.strip()]
                    if reg and langs:
                        regions.append({"region": reg, "languages": langs})
                if regions:
                    entries.append({
                        "id": f"corebook:rule:lifepath-cultural-regions-p{pdf_page}-t{table_no}",
                        "name": "Cultural Regions",
                        "norm_name": "cultural regions",
                        "category": "rule",
                        "source": "corebook",
                        "summary": f"Cultural regions and languages ({len(regions)} regions).",
                        "description": ", ".join(r["region"] for r in regions),
                        "stats": {"table_key": "cultural_regions", "regions": regions},
                        "tags": ["rule", "lifepath", "cultural_regions"],
                        "pdf_page": pdf_page,
                        "printed_page": printed,
                        "section_id": None,
                        "source_sha256": digest,
                    })
                continue

            # 2. Districts / Locations table
            if any(h in {"district", "districtname", "sector", "location"} for h in norm_headers):
                d_col = next(i for i, h in enumerate(norm_headers) if h in {"district", "districtname", "sector", "location"})
                zt_col = next((i for i, h in enumerate(norm_headers) if h in {"zonetype", "zone"}), None)
                tr_col = next((i for i, h in enumerate(norm_headers) if h in {"threatrating", "threat"}), None)
                sum_col = next((i for i, h in enumerate(norm_headers) if h in {"summary", "description", "notes"}), None)
                for row_no, cells in enumerate(rows[1:], 1):
                    if d_col >= len(cells) or not cells[d_col].strip():
                        continue
                    name = cells[d_col].strip()
                    zt = cells[zt_col].strip() if zt_col is not None and zt_col < len(cells) else ""
                    tr = cells[tr_col].strip() if tr_col is not None and tr_col < len(cells) else ""
                    desc = cells[sum_col].strip() if sum_col is not None and sum_col < len(cells) else f"{name} ({zt or 'District'})."
                    eid = f"corebook:location:{_slug(name)}"
                    if eid in used_ids:
                        eid = f"{eid}-p{pdf_page}-r{row_no}"
                    used_ids.add(eid)
                    entries.append({
                        "id": eid,
                        "name": name,
                        "norm_name": sourcecatalog._normalize(name),
                        "category": "location",
                        "source": "corebook",
                        "summary": _summarize(desc),
                        "description": desc,
                        "stats": {"zone_type": zt, "threat_rating": tr},
                        "tags": ["location", "district"] + ([_slug(zt)] if zt else []),
                        "pdf_page": pdf_page,
                        "printed_page": printed,
                        "section_id": None,
                        "source_sha256": digest,
                    })
                continue

            # 3. Factions table
            if any(h in {"faction", "factionname", "corporation", "gang", "organization"} for h in norm_headers):
                f_col = next(i for i, h in enumerate(norm_headers) if h in {"faction", "factionname", "corporation", "gang", "organization"})
                t_col = next((i for i, h in enumerate(norm_headers) if h in {"type", "factiontype", "kind", "category"}), None)
                sum_col = next((i for i, h in enumerate(norm_headers) if h in {"summary", "description", "notes"}), None)
                for row_no, cells in enumerate(rows[1:], 1):
                    if f_col >= len(cells) or not cells[f_col].strip():
                        continue
                    name = cells[f_col].strip()
                    ftype = cells[t_col].strip() if t_col is not None and t_col < len(cells) else "Faction"
                    desc = cells[sum_col].strip() if sum_col is not None and sum_col < len(cells) else f"{name} ({ftype})."
                    eid = f"corebook:faction:{_slug(name)}"
                    if eid in used_ids:
                        eid = f"{eid}-p{pdf_page}-r{row_no}"
                    used_ids.add(eid)
                    entries.append({
                        "id": eid,
                        "name": name,
                        "norm_name": sourcecatalog._normalize(name),
                        "category": "faction",
                        "source": "corebook",
                        "summary": _summarize(desc),
                        "description": desc,
                        "stats": {"type": ftype},
                        "tags": ["faction", _slug(ftype)],
                        "pdf_page": pdf_page,
                        "printed_page": printed,
                        "section_id": None,
                        "source_sha256": digest,
                    })
                continue

            # 4. Zone Types / Threat Ratings / Caper Styles / Screamsheets
            if "zonetype" in norm_headers and any(h in {"summary", "description"} for h in norm_headers):
                zt_col = norm_headers.index("zonetype")
                sum_col = next(i for i, h in enumerate(norm_headers) if h in {"summary", "description"})
                for row_no, cells in enumerate(rows[1:], 1):
                    if max(zt_col, sum_col) >= len(cells) or not cells[zt_col].strip():
                        continue
                    name = cells[zt_col].strip()
                    desc = cells[sum_col].strip()
                    entries.append({
                        "id": f"corebook:rule:zone-type-{_slug(name)}-p{pdf_page}-r{row_no}",
                        "name": name,
                        "norm_name": sourcecatalog._normalize(name),
                        "category": "rule",
                        "source": "corebook",
                        "summary": _summarize(desc),
                        "description": desc,
                        "stats": {"zone_type": name},
                        "tags": ["rule", "zone-type"],
                        "pdf_page": pdf_page,
                        "printed_page": printed,
                        "section_id": None,
                        "source_sha256": digest,
                    })
                continue

            if "threatrating" in norm_headers and any(h in {"summary", "description", "ncpdresponse"} for h in norm_headers):
                tr_col = norm_headers.index("threatrating")
                resp_col = next((i for i, h in enumerate(norm_headers) if h in {"ncpdresponse", "response"}), None)
                sum_col = next((i for i, h in enumerate(norm_headers) if h in {"summary", "description"}), None)
                for row_no, cells in enumerate(rows[1:], 1):
                    if tr_col >= len(cells) or not cells[tr_col].strip():
                        continue
                    name = cells[tr_col].strip()
                    resp = cells[resp_col].strip() if resp_col is not None and resp_col < len(cells) else ""
                    desc = cells[sum_col].strip() if sum_col is not None and sum_col < len(cells) else resp
                    entries.append({
                        "id": f"corebook:rule:threat-rating-{_slug(name)}-p{pdf_page}-r{row_no}",
                        "name": name,
                        "norm_name": sourcecatalog._normalize(name),
                        "category": "rule",
                        "source": "corebook",
                        "summary": _summarize(desc),
                        "description": desc,
                        "stats": {"threat_rating": name, "ncpd_response": resp},
                        "tags": ["rule", "threat-rating"],
                        "pdf_page": pdf_page,
                        "printed_page": printed,
                        "section_id": None,
                        "source_sha256": digest,
                    })
                continue

            if any(h in {"caperstyle", "caper"} for h in norm_headers) or ({"hook", "climax", "resolution"} <= set(norm_headers)):
                name_col = next((i for i, h in enumerate(norm_headers) if h in {"caperstyle", "caper", "name", "title"}), None)
                sum_col = next((i for i, h in enumerate(norm_headers) if h in {"summary", "description"}), None)
                beat_cols = {b: norm_headers.index(b) for b in ("hook", "developments", "cliffhanger", "climax", "resolution") if b in norm_headers}
                for row_no, cells in enumerate(rows[1:], 1):
                    name = cells[name_col].strip() if name_col is not None and name_col < len(cells) else f"Caper Style {row_no}"
                    if not name:
                        continue
                    beats = {b: cells[idx].strip() for b, idx in beat_cols.items() if idx < len(cells) and cells[idx].strip()}
                    desc = cells[sum_col].strip() if sum_col is not None and sum_col < len(cells) else "; ".join(f"{k}: {v}" for k, v in beats.items())
                    entries.append({
                        "id": f"corebook:rule:caper-{_slug(name)}-p{pdf_page}-r{row_no}",
                        "name": name,
                        "norm_name": sourcecatalog._normalize(name),
                        "category": "rule",
                        "source": "corebook",
                        "summary": _summarize(desc),
                        "description": desc,
                        "stats": {"caper_id": _slug(name), "default_beats": beats},
                        "tags": ["rule", "caper-style", "beat-chart"],
                        "pdf_page": pdf_page,
                        "printed_page": printed,
                        "section_id": None,
                        "source_sha256": digest,
                    })
                continue

            if "headline" in norm_headers:
                hl_col = norm_headers.index("headline")
                dist_col = next((i for i, h in enumerate(norm_headers) if h in {"district", "location"}), None)
                fac_col = next((i for i, h in enumerate(norm_headers) if h in {"factions", "faction"}), None)
                pay_col = next((i for i, h in enumerate(norm_headers) if h in {"payout", "payouteb", "reward"}), None)
                sum_col = next((i for i, h in enumerate(norm_headers) if h in {"summary", "hook", "description"}), None)
                for row_no, cells in enumerate(rows[1:], 1):
                    if hl_col >= len(cells) or not cells[hl_col].strip():
                        continue
                    headline = cells[hl_col].strip()
                    dist = cells[dist_col].strip() if dist_col is not None and dist_col < len(cells) else ""
                    facs = [x.strip() for x in re.split(r"[,;/]", cells[fac_col]) if x.strip()] if fac_col is not None and fac_col < len(cells) else []
                    pay = sourcecatalog._cost(cells[pay_col], allow_bare_int=True) if pay_col is not None and pay_col < len(cells) else None
                    desc = cells[sum_col].strip() if sum_col is not None and sum_col < len(cells) else headline
                    entries.append({
                        "id": f"corebook:screamsheet:{_slug(headline)}-p{pdf_page}-r{row_no}",
                        "name": headline,
                        "norm_name": sourcecatalog._normalize(headline),
                        "category": "screamsheet",
                        "source": "corebook",
                        "summary": _summarize(desc),
                        "description": desc,
                        "stats": {"headline": headline, "district": dist, "factions": facs, "payout_eb": pay or 0},
                        "tags": ["screamsheet"],
                        "pdf_page": pdf_page,
                        "printed_page": printed,
                        "section_id": None,
                        "source_sha256": digest,
                    })
                continue

            # 5. Rollable Lifepath tables
            roll_col = next((i for i, h in enumerate(norm_headers) if h in {"roll", "d10", "1d10", "d6", "1d6"}), None)
            if roll_col is not None and len(headers) >= 2:
                val_col = next((i for i in range(len(headers)) if i != roll_col), None)
                if val_col is not None:
                    lp_key = _match_lifepath_key(headers[val_col]) or _match_lifepath_key(page_heading)
                    if lp_key:
                        options = [
                            cells[val_col].strip()
                            for cells in rows[1:]
                            if val_col < len(cells) and cells[val_col].strip()
                        ]
                        if options:
                            entries.append({
                                "id": f"corebook:rule:lifepath-{lp_key}-p{pdf_page}-t{table_no}",
                                "name": f"Lifepath: {headers[val_col].strip()}",
                                "norm_name": sourcecatalog._normalize(f"lifepath {lp_key}"),
                                "category": "rule",
                                "source": "corebook",
                                "summary": f"Lifepath table {lp_key} ({len(options)} entries).",
                                "description": "; ".join(options[:6]),
                                "stats": {"table_key": lp_key, "options": options},
                                "tags": ["rule", "lifepath", lp_key],
                                "pdf_page": pdf_page,
                                "printed_page": printed,
                                "section_id": None,
                                "source_sha256": digest,
                            })
    return entries


def _extract_section_entries(
    conn: sqlite3.Connection, pages_by_pdf: dict[int, sqlite3.Row], digest: str
) -> list[dict[str, Any]]:
    if not _table_exists(conn, "source_sections"):
        return []
    entries: list[dict[str, Any]] = []
    rows = conn.execute(
        "SELECT id,title,start_pdf,end_pdf,printed_start FROM source_sections ORDER BY start_pdf,id"
    ).fetchall()
    for row in rows:
        title = str(row["title"]).strip()
        if not title:
            continue
        start_pdf = int(row["start_pdf"])
        end_pdf = int(row["end_pdf"])
        printed_start = row["printed_start"]
        raw_lines: list[str] = []
        for pno in range(start_pdf, min(end_pdf, start_pdf + 2) + 1):
            page_row = pages_by_pdf.get(pno)
            if page_row is not None:
                raw_lines.extend(
                    ln.strip()
                    for ln in str(page_row["text"]).splitlines()
                    if ln.strip() and not ln.strip().startswith("Supplemental extracted table rows")
                )
        excerpt = _clean_prose(raw_lines[:24])
        lower_title = title.casefold()
        is_role = any(re.search(rf"\b{role}\b", lower_title) for role in ROLE_NAMES)
        is_location = any(kw in lower_title for kw in ("district", "combat zone", "hot zone", "corporate center", "executive zone", "moderate zone", "badlands", "open road"))
        is_faction = any(kw in lower_title for kw in ("faction", "corporation", "megacorp", "gang", "nomad nation"))
        category = "role" if is_role else ("location" if is_location else ("faction" if is_faction else "rule"))
        stats: dict[str, Any] = {"start_pdf": start_pdf, "end_pdf": end_pdf}
        if is_role and raw_lines:
            joined_raw = "\n".join(raw_lines)
            m_ability = re.search(r"(?:Role|Special)\s+Ability\s*:\s*([^\n.;]+)", joined_raw, re.I)
            if m_ability:
                stats["role_ability"] = m_ability.group(1).strip()
            m_stats = re.search(r"Key\s+STATs?\s*:\s*([^\n]+)", joined_raw, re.I)
            if m_stats:
                stats["key_stats"] = [s.strip().upper() for s in re.split(r"[,/\s]+", m_stats.group(1)) if s.strip().upper() in STAT_NAMES]
        desc = excerpt or f"{title} (pages {start_pdf}–{end_pdf})."
        entries.append(
            {
                "id": f"corebook:{category}:{row['id']}",
                "name": title,
                "norm_name": sourcecatalog._normalize(title),
                "category": category,
                "source": "corebook",
                "summary": _summarize(desc),
                "description": desc[:2000],
                "stats": stats,
                "tags": [category, str(row["id"])],
                "pdf_page": start_pdf,
                "printed_page": int(printed_start) if printed_start is not None else None,
                "section_id": str(row["id"]),
                "source_sha256": digest,
            }
        )
    return entries


def _extract_all_entries(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    old_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        meta = dict(conn.execute("SELECT key,value FROM metadata"))
        digest = meta.get("source_sha256")
        if not digest:
            raise ValueError("Rules index has no source_sha256 metadata")
        pages = conn.execute("SELECT pdf_page,printed_page,text FROM pages ORDER BY pdf_page").fetchall()
        pages_by_pdf = {int(r["pdf_page"]): r for r in pages}
        entries: list[dict[str, Any]] = []
        try:
            entries.extend(_extract_skill_entries(pages, digest))
        except ValueError:
            pass
        entries.extend(_extract_item_entries(conn, pages, digest))
        entries.extend(_extract_structured_table_entries(conn, pages, digest))
        entries.extend(_extract_section_entries(conn, pages_by_pdf, digest))

        deduped: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for entry in entries:
            if entry["id"] in seen_ids:
                continue
            seen_ids.add(entry["id"])
            deduped.append(entry)
        return deduped
    finally:
        conn.row_factory = old_factory


def build_library(conn: sqlite3.Connection) -> int:
    """Materialize rule_entries and rule_entries_fts inside an open writable rules SQLite connection."""
    conn.executescript(
        """
        DROP TABLE IF EXISTS rule_entries_fts;
        DROP TABLE IF EXISTS rule_entries;
        CREATE TABLE rule_entries (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            norm_name TEXT NOT NULL,
            category TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'corebook',
            summary TEXT NOT NULL,
            description TEXT NOT NULL,
            stats_json TEXT NOT NULL,
            tags_json TEXT NOT NULL,
            pdf_page INTEGER,
            printed_page INTEGER,
            section_id TEXT,
            source_sha256 TEXT NOT NULL
        );
        CREATE INDEX rule_entries_cat_idx ON rule_entries(category);
        CREATE INDEX rule_entries_norm_idx ON rule_entries(norm_name);
        CREATE VIRTUAL TABLE rule_entries_fts USING fts5(
            entry_id UNINDEXED,
            name,
            category,
            summary,
            description,
            tags_text,
            tokenize='porter unicode61'
        );
        """
    )
    entries = _extract_all_entries(conn)
    for entry in entries:
        conn.execute(
            """
            INSERT INTO rule_entries(
                id, name, norm_name, category, source, summary, description,
                stats_json, tags_json, pdf_page, printed_page, section_id, source_sha256
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                entry["id"],
                entry["name"],
                entry["norm_name"],
                entry["category"],
                entry["source"],
                entry["summary"],
                entry["description"],
                _json(entry["stats"]),
                _json(entry["tags"]),
                entry["pdf_page"],
                entry["printed_page"],
                entry["section_id"],
                entry["source_sha256"],
            ),
        )
        stats_text = " ".join(f"{k} {v}" for k, v in entry["stats"].items())
        conn.execute(
            "INSERT INTO rule_entries_fts(entry_id, name, category, summary, description, tags_text) VALUES (?,?,?,?,?,?)",
            (
                entry["id"],
                entry["name"],
                entry["category"],
                entry["summary"],
                entry["description"],
                " ".join([*entry["tags"], stats_text]).strip(),
            ),
        )
    return len(entries)


def materialize_library(db_path: str | Path) -> dict[str, Any]:
    """One-time safe materialization of the organized library on an existing rules index."""
    path = Path(db_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Rules index not found: {path}")
    with index_lock(path):
        conn = sqlite3.connect(path)
        try:
            conn.row_factory = sqlite3.Row
            with conn:
                count = build_library(conn)
        finally:
            conn.close()
    with _CACHE_LOCK:
        stale = [k for k in _MEMORY_CACHE if k[0] == str(path)]
        for k in stale:
            _MEMORY_CACHE.pop(k, None)
    return {"db": str(path), "entries": count}


def _row_to_entry(row: sqlite3.Row, *, campaign_id: str | None = None) -> dict[str, Any]:
    keys = set(row.keys())
    return {
        "id": row["id"],
        "name": row["name"],
        "category": row["category"],
        "source": row["source"],
        "created_by": row["created_by"] if "created_by" in keys else "corebook",
        "summary": row["summary"],
        "description": row["description"],
        "stats": json.loads(row["stats_json"]),
        "tags": json.loads(row["tags_json"]),
        "pdf_page": row["pdf_page"] if "pdf_page" in keys else None,
        "printed_page": row["printed_page"] if "printed_page" in keys else None,
        "section_id": row["section_id"] if "section_id" in keys else None,
        "source_sha256": row["source_sha256"] if "source_sha256" in keys else None,
        "campaign_id": row["campaign_id"] if "campaign_id" in keys else campaign_id,
    }


def _load_corebook_entries(rules_path: str | Path, conn: sqlite3.Connection) -> list[dict[str, Any]]:
    resolved = Path(rules_path).expanduser().resolve()
    st = resolved.stat()
    meta_row = conn.execute("SELECT value FROM metadata WHERE key='source_sha256'").fetchone()
    digest = meta_row[0] if meta_row else ""
    cache_key = (str(resolved), st.st_mtime_ns, st.st_size, digest)
    with _CACHE_LOCK:
        cached = _MEMORY_CACHE.get(cache_key)
    if cached is not None:
        return [dict(item) for item in cached]
    built = _extract_all_entries(conn)
    for item in built:
        item.setdefault("created_by", "corebook")
        item.setdefault("campaign_id", None)
    with _CACHE_LOCK:
        _MEMORY_CACHE[cache_key] = [dict(item) for item in built]
    return built


_STOPWORDS = frozenset(
    {
        "i", "me", "my", "we", "you", "your", "our", "they", "them", "their", "he", "him", "his", "she", "her",
        "a", "an", "the", "and", "or", "but", "with", "to", "of", "in", "on", "at", "by", "for", "is", "are",
        "was", "were", "be", "been", "being", "it", "its", "this", "that", "these", "those", "from", "into",
        "yo", "hey", "hi", "hello", "sup", "yes", "no", "ok", "okay", "yeah", "yep", "nah",
        "want", "wanna", "have", "has", "had", "do", "does", "did", "dont", "didnt", "doesnt",
        "wasnt", "werent", "isnt", "arent", "havent", "cant", "wont", "couldnt", "wouldnt", "shouldnt",
        "make", "made", "what", "why", "who", "where", "when", "how", "even", "there", "here", "already",
        "just", "now", "then", "some", "any", "all", "more", "very", "really", "actually", "something",
        "anything", "nothing", "smth", "idk", "wait", "tell", "ask", "asked", "asking", "look", "looking",
        "see", "saw", "seen", "get", "got", "go", "going", "went", "come", "came", "say", "said", "says",
        "talk", "talked", "talking", "question", "questions", "character", "characters", "can", "could",
        "would", "should", "will", "shall", "may", "might", "must", "not", "im", "ive", "ill", "youre",
        "thats", "about", "around", "like", "know", "think", "mean", "use", "using", "used", "try", "trying",
    }
)


def _query_tokens(query: str, *, include_fallback: bool = True) -> list[str]:
    raw = [t.casefold() for t in re.findall(r"[A-Za-z0-9]+", query) if t]
    meaningful = [t for t in raw if t not in _STOPWORDS and len(t) > 1]
    if meaningful:
        return meaningful[:12]
    return raw[:12] if include_fallback else []


def _fts_query(tokens: list[str]) -> str:
    return " OR ".join(f'"{t}"*' for t in tokens[:10])


def _matches_strict_name(entry: dict[str, Any], norm_q: str, tokens: list[str]) -> bool:
    norm_name = sourcecatalog._normalize(entry["name"])
    if len(norm_name) >= 3 and norm_q:
        if norm_q == norm_name or re.search(rf"\b{re.escape(norm_name)}\b", norm_q):
            return True
    name_words = set(re.findall(r"[a-z0-9]+", norm_name))
    tag_words = {
        w
        for t in (entry.get("tags") or [])
        for w in re.findall(r"[a-z0-9]+", sourcecatalog._normalize(str(t)))
    }
    strict_toks = [t for t in tokens if len(t) >= 3 and t not in _STOPWORDS]
    return any(tok in name_words or tok in tag_words for tok in strict_toks)


def _entry_haystack(entry: dict[str, Any]) -> str:
    stats_text = " ".join(f"{k} {v}" for k, v in (entry.get("stats") or {}).items())
    return " ".join(
        [entry["name"], entry["summary"], entry["description"], " ".join(entry.get("tags") or []), stats_text]
    ).casefold()


def _rank_entry(entry: dict[str, Any], norm_q: str, tokens: list[str]) -> tuple[int, int, int, str]:
    norm_name = sourcecatalog._normalize(entry["name"])
    hay = _entry_haystack(entry)
    name_hits = sum(1 for tok in tokens if tok in norm_name)
    hay_hits = sum(1 for tok in tokens if tok in hay)
    if norm_q and norm_name == norm_q:
        tier = 0
    elif norm_q and norm_name.startswith(norm_q):
        tier = 1
    elif norm_q and (norm_q in norm_name or (len(norm_name) >= 3 and re.search(rf"\b{re.escape(norm_name)}\b", norm_q))):
        tier = 2
    elif tokens and all(tok in norm_name for tok in tokens):
        tier = 3
    elif name_hits > 0:
        tier = 4
    else:
        tier = 5
    page = entry.get("printed_page")
    page_key = int(page) if isinstance(page, int) else 999999
    return (tier, -(name_hits * 3 + hay_hits), page_key, norm_name)


def validate_entry_payload(
    *,
    name: Any,
    category: Any,
    summary: Any = "",
    description: Any = "",
    stats: Any = None,
    tags: Any = None,
    created_by: Any = "user",
) -> dict[str, Any]:
    """Validate campaign homebrew entries against Cyberpunk RED universe bounds."""
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
        raise ValueError("name must be a nonempty string of at most 120 characters")
    clean_name = name.strip()
    clean_cat = normalize_category(category)
    if clean_cat is None:
        raise ValueError("category is required")
    if not isinstance(created_by, str) or created_by not in {"user", "gm", "ai"}:
        raise ValueError("created_by must be one of: user, gm, ai")
    if not isinstance(description, str) or len(description) > 4000:
        raise ValueError("description must be a string of at most 4000 characters")
    clean_desc = description.strip() or f"{clean_name} ({clean_cat})."
    if not isinstance(summary, str) or len(summary) > 400:
        raise ValueError("summary must be a string of at most 400 characters")
    clean_summary = summary.strip() or _summarize(clean_desc)

    if stats is None:
        stats = {}
    if not isinstance(stats, dict):
        raise ValueError("stats must be an object")
    clean_stats: dict[str, Any] = {}
    for key, val in stats.items():
        if not isinstance(key, str) or not key.strip() or len(key) > 64:
            raise ValueError("stat keys must be nonempty strings of at most 64 characters")
        if key == "stat":
            if not isinstance(val, str) or val.upper() not in STAT_NAMES:
                raise ValueError(f"stat must be one of: {', '.join(STAT_NAMES)}")
            clean_stats["stat"] = val.upper()
        elif key == "cost_multiplier":
            if isinstance(val, bool) or val not in (1, 2):
                raise ValueError("cost_multiplier must be 1 or 2")
            clean_stats["cost_multiplier"] = val
        elif key == "cost_eb":
            if isinstance(val, bool) or not isinstance(val, int) or not 0 <= val <= 1_000_000:
                raise ValueError("cost_eb must be an integer between 0 and 1,000,000")
            clean_stats["cost_eb"] = val
        elif key == "rof":
            if isinstance(val, bool) or not isinstance(val, int) or not 1 <= val <= 4:
                raise ValueError("rof must be an integer between 1 and 4")
            clean_stats["rof"] = val
        elif key == "sp":
            if isinstance(val, bool) or not isinstance(val, int) or not 0 <= val <= 25:
                raise ValueError("sp must be an integer between 0 and 25")
            clean_stats["sp"] = val
        elif key == "armor_penalty":
            if isinstance(val, bool) or not isinstance(val, int) or not -10 <= val <= 0:
                raise ValueError("armor_penalty must be an integer between -10 and 0")
            clean_stats["armor_penalty"] = val
        elif key == "hands":
            if isinstance(val, bool) or not isinstance(val, int) or not 1 <= val <= 2:
                raise ValueError("hands must be 1 or 2")
            clean_stats["hands"] = val
        elif key == "magazine":
            if isinstance(val, bool) or not isinstance(val, int) or not 1 <= val <= 200:
                raise ValueError("magazine must be an integer between 1 and 200")
            clean_stats["magazine"] = val
        elif key == "damage":
            if not isinstance(val, str) or not _DICE_RE.fullmatch(val.strip()):
                raise ValueError("damage must be a valid dice formula like 2d6 or 4d6")
            clean_stats["damage"] = val.strip().lower()
        elif key in {"hl", "humanity_loss"}:
            if isinstance(val, int) and not isinstance(val, bool):
                if not 0 <= val <= 60:
                    raise ValueError("humanity_loss must be between 0 and 60 or a dice formula")
                clean_stats[key] = val
            elif isinstance(val, str) and _DICE_RE.fullmatch(val.strip()):
                clean_stats[key] = val.strip().lower()
            else:
                raise ValueError("humanity_loss must be an integer (0..60) or dice formula like 2d6")
        else:
            if not isinstance(val, (str, int, float, bool)) or isinstance(val, str) and len(val) > 200:
                raise ValueError(f"Unsupported or oversized stat value for {key!r}")
            clean_stats[key] = val

    if clean_cat == "skill" and "stat" in clean_stats and clean_stats["stat"] not in STAT_NAMES:
        raise ValueError("Skill stat must be a valid Cyberpunk RED STAT")

    if tags is None:
        tags = []
    if not isinstance(tags, list) or len(tags) > 12 or any(not isinstance(t, str) or not t.strip() or len(t) > 40 for t in tags):
        raise ValueError("tags must be a list of at most 12 short strings")
    clean_tags = [t.strip() for t in tags]

    return {
        "name": clean_name,
        "norm_name": sourcecatalog._normalize(clean_name),
        "category": clean_cat,
        "summary": clean_summary,
        "description": clean_desc,
        "stats": clean_stats,
        "tags": clean_tags,
        "created_by": created_by,
    }


class CampaignLibrary:
    """Manage campaign-scoped homebrew / AI-created rulebook entries in campaign.sqlite."""

    def __init__(self, campaign_or_store: CampaignStore | str | Path, rules_path: str | Path | None = None):
        if isinstance(campaign_or_store, CampaignStore):
            self.store = campaign_or_store
        else:
            self.store = CampaignStore(campaign_or_store)
        self.memory = CampaignMemory(self.store)
        self.rules_path = Path(rules_path).expanduser().resolve() if rules_path else None
        if self.rules_path and self.rules_path == self.store.path.expanduser().resolve():
            raise ValueError("Campaign storage must be separate from the rules index")
        with closing(self.store._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS campaign_library (
                    id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL REFERENCES campaigns(id),
                    name TEXT NOT NULL,
                    norm_name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'homebrew',
                    created_by TEXT NOT NULL DEFAULT 'user',
                    summary TEXT NOT NULL,
                    description TEXT NOT NULL,
                    stats_json TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    operation_id TEXT UNIQUE NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_campaign_library_camp ON campaign_library(campaign_id, category, norm_name)"
            )

    def _reject_cross_table_op(self, conn: sqlite3.Connection, operation_id: str) -> None:
        self.store._reject_roll_id(conn, operation_id)
        if conn.execute("SELECT 1 FROM audit WHERE operation_id=?", (operation_id,)).fetchone():
            raise ValueError("operation_id was already used for a character change")

    def add_entry(
        self,
        campaign_id: str,
        *,
        name: str,
        category: str,
        operation_id: str,
        summary: str = "",
        description: str = "",
        stats: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        created_by: str = "user",
        allow_variant: bool = False,
    ) -> dict[str, Any]:
        """Create a campaign homebrew/dossier library entry, rejecting duplicates unless allow_variant=True."""
        return self._write_entry(
            campaign_id,
            name=name,
            category=category,
            operation_id=operation_id,
            summary=summary,
            description=description,
            stats=stats,
            tags=tags,
            created_by=created_by,
            allow_variant=allow_variant,
            upsert=False,
        )

    def upsert_entry(
        self,
        campaign_id: str,
        *,
        name: str,
        category: str,
        operation_id: str,
        summary: str = "",
        description: str = "",
        stats: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        created_by: str = "ai",
        allow_variant: bool = False,
    ) -> dict[str, Any]:
        """Create or update an existing campaign entry matching (campaign_id, category, norm_name)."""
        return self._write_entry(
            campaign_id,
            name=name,
            category=category,
            operation_id=operation_id,
            summary=summary,
            description=description,
            stats=stats,
            tags=tags,
            created_by=created_by,
            allow_variant=allow_variant,
            upsert=True,
        )

    def _write_entry(
        self,
        campaign_id: str,
        *,
        name: str,
        category: str,
        operation_id: str,
        summary: str,
        description: str,
        stats: dict[str, Any] | None,
        tags: list[str] | None,
        created_by: str,
        allow_variant: bool,
        upsert: bool,
    ) -> dict[str, Any]:
        if not isinstance(operation_id, str) or not operation_id.strip() or len(operation_id) > 200:
            raise ValueError("operation_id must be a nonempty string of at most 200 characters")
        cleaned = validate_entry_payload(
            name=name,
            category=category,
            summary=summary,
            description=description,
            stats=stats,
            tags=tags,
            created_by=created_by,
        )
        action_name = "upsert_homebrew" if upsert else "add_homebrew"
        payload = _json({"action": action_name, "campaign_id": campaign_id, **cleaned})

        if (
            not allow_variant
            and cleaned["category"] not in {"npc", "faction", "location"}
            and self.rules_path
            and self.rules_path.is_file()
        ):
            existing = search_library(
                self.rules_path,
                q=cleaned["name"],
                category=cleaned["category"],
                include_corebook=True,
                include_homebrew=False,
                limit=50,
            )
            if any(sourcecatalog._normalize(item["name"]) == cleaned["norm_name"] for item in existing):
                raise ValueError(
                    f"Cannot overwrite official Corebook {cleaned['category']} '{cleaned['name']}'; choose a distinct name or set allow_variant=True"
                )

        now = datetime.now(timezone.utc).isoformat()
        with closing(self.store._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            self._reject_cross_table_op(conn, operation_id)
            prior = conn.execute("SELECT * FROM campaign_library WHERE operation_id=?", (operation_id,)).fetchone()
            if prior is not None:
                prior_record = _row_to_entry(prior)
                prior_payload = _json(
                    {
                        "action": action_name,
                        "campaign_id": prior["campaign_id"],
                        "name": prior["name"],
                        "norm_name": prior["norm_name"],
                        "category": prior["category"],
                        "summary": prior["summary"],
                        "description": prior["description"],
                        "stats": json.loads(prior["stats_json"]),
                        "tags": json.loads(prior["tags_json"]),
                        "created_by": prior["created_by"],
                    }
                )
                if prior_payload != payload:
                    raise ValueError("operation_id was already used for a different homebrew entry")
                return prior_record
            if not conn.execute("SELECT 1 FROM campaigns WHERE id=?", (campaign_id,)).fetchone():
                raise ValueError(f"campaign not found: {campaign_id}")
            dup = conn.execute(
                "SELECT * FROM campaign_library WHERE campaign_id=? AND category=? AND norm_name=?",
                (campaign_id, cleaned["category"], cleaned["norm_name"]),
            ).fetchone()
            if dup is not None and upsert:
                existing_stats = json.loads(dup["stats_json"])
                merged_stats = {**existing_stats, **cleaned["stats"]}
                existing_tags = json.loads(dup["tags_json"])
                merged_tags = list(dict.fromkeys([*existing_tags, *cleaned["tags"]]))[:12]
                conn.execute(
                    """
                    UPDATE campaign_library
                    SET name=?, summary=?, description=?, stats_json=?, tags_json=?, revision=revision+1, operation_id=?
                    WHERE id=?
                    """,
                    (
                        cleaned["name"],
                        cleaned["summary"],
                        cleaned["description"],
                        _json(merged_stats),
                        _json(merged_tags),
                        operation_id,
                        dup["id"],
                    ),
                )
                row = conn.execute("SELECT * FROM campaign_library WHERE id=?", (dup["id"],)).fetchone()
                return _row_to_entry(row)
            if dup and not allow_variant:
                raise ValueError(
                    f"Campaign already has homebrew {cleaned['category']} '{cleaned['name']}'"
                )
            base_id = f"homebrew:{campaign_id[:8]}:{cleaned['category']}:{_slug(cleaned['name'])}"
            entry_id = base_id
            suffix = 2
            while conn.execute("SELECT 1 FROM campaign_library WHERE id=?", (entry_id,)).fetchone():
                entry_id = f"{base_id}-{suffix}"
                suffix += 1
            conn.execute(
                """
                INSERT INTO campaign_library(
                    id, campaign_id, name, norm_name, category, source, created_by,
                    summary, description, stats_json, tags_json, revision, operation_id, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    entry_id,
                    campaign_id,
                    cleaned["name"],
                    cleaned["norm_name"],
                    cleaned["category"],
                    "homebrew",
                    cleaned["created_by"],
                    cleaned["summary"],
                    cleaned["description"],
                    _json(cleaned["stats"]),
                    _json(cleaned["tags"]),
                    1,
                    operation_id,
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM campaign_library WHERE id=?", (entry_id,)).fetchone()
            return _row_to_entry(row)

    def list_entries(self, campaign_id: str, *, category: str | None = None) -> list[dict[str, Any]]:
        clean_cat = normalize_category(category)
        with closing(self.store._connect()) as conn:
            if clean_cat:
                rows = conn.execute(
                    "SELECT * FROM campaign_library WHERE campaign_id=? AND category=? ORDER BY name COLLATE NOCASE, id",
                    (campaign_id, clean_cat),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM campaign_library WHERE campaign_id=? ORDER BY category, name COLLATE NOCASE, id",
                    (campaign_id,),
                ).fetchall()
            return [_row_to_entry(r) for r in rows]

    def get_entry(self, campaign_id: str, entry_id: str) -> dict[str, Any] | None:
        with closing(self.store._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM campaign_library WHERE campaign_id=? AND id=?",
                (campaign_id, entry_id),
            ).fetchone()
            return _row_to_entry(row) if row else None

    def remove_entry(self, campaign_id: str, entry_id: str) -> bool:
        if isinstance(entry_id, str) and entry_id.startswith("corebook:"):
            raise ValueError("Official Corebook entries cannot be deleted")
        with closing(self.store._connect()) as conn, conn:
            cur = conn.execute(
                "DELETE FROM campaign_library WHERE campaign_id=? AND id=?",
                (campaign_id, entry_id),
            )
            return cur.rowcount > 0


def search_library(
    rules_path: str | Path | None,
    *,
    q: str = "",
    category: str | None = None,
    campaign_path: str | Path | None = None,
    campaign_id: str | None = None,
    include_corebook: bool = True,
    include_homebrew: bool = True,
    strict_names: bool = False,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Search unified Corebook and campaign homebrew entries, ranked for lookup and autocomplete."""
    clean_cat = normalize_category(category)
    query = q.strip() if isinstance(q, str) else ""
    norm_q = sourcecatalog._normalize(query) if query else ""
    tokens = _query_tokens(query, include_fallback=not strict_names)
    if strict_names and not tokens:
        return []
    bound_limit = max(1, min(int(limit), 100))

    results: list[dict[str, Any]] = []
    if include_corebook and rules_path is not None:
        resolved = Path(rules_path).expanduser().resolve()
        if resolved.is_file():
            conn = sqlite3.connect(resolved.as_uri() + "?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            try:
                has_entries = (
                    _table_exists(conn, "rule_entries")
                    and conn.execute("SELECT 1 FROM rule_entries LIMIT 1").fetchone() is not None
                )
                if has_entries:
                    if query and _table_exists(conn, "rule_entries_fts"):
                        fts = (
                            " OR ".join(f'"{t}"' for t in tokens[:10])
                            if strict_names
                            else _fts_query(tokens)
                        )
                        sql = (
                            "SELECT e.* FROM rule_entries_fts f "
                            "JOIN rule_entries e ON e.id = f.entry_id "
                            "WHERE rule_entries_fts MATCH ?"
                        )
                        params: list[Any] = [fts]
                        if clean_cat:
                            sql += " AND e.category = ?"
                            params.append(clean_cat)
                        sql += " ORDER BY rank LIMIT ?"
                        params.append(max(bound_limit * 6, 60))
                        try:
                            rows = conn.execute(sql, params).fetchall() if fts else []
                        except sqlite3.OperationalError:
                            rows = []
                        if not rows and not strict_names:
                            like = f"%{query}%"
                            like_sql = "SELECT * FROM rule_entries WHERE (name LIKE ? OR summary LIKE ? OR description LIKE ?)"
                            like_params: list[Any] = [like, like, like]
                            if clean_cat:
                                like_sql += " AND category = ?"
                                like_params.append(clean_cat)
                            like_sql += " LIMIT ?"
                            like_params.append(max(bound_limit * 4, 40))
                            rows = conn.execute(like_sql, like_params).fetchall()
                    elif clean_cat:
                        rows = conn.execute(
                            "SELECT * FROM rule_entries WHERE category=? ORDER BY name COLLATE NOCASE LIMIT ?",
                            (clean_cat, max(bound_limit * 4, 80)),
                        ).fetchall()
                    else:
                        rows = conn.execute(
                            "SELECT * FROM rule_entries ORDER BY category, name COLLATE NOCASE LIMIT ?",
                            (max(bound_limit * 4, 80),),
                        ).fetchall()
                    results.extend(_row_to_entry(r) for r in rows)
                else:
                    cached = _load_corebook_entries(resolved, conn)
                    for item in cached:
                        if clean_cat and item["category"] != clean_cat:
                            continue
                        if tokens:
                            hay = _entry_haystack(item)
                            if not any(tok in hay for tok in tokens):
                                continue
                        results.append(item)
            finally:
                conn.close()

    if include_homebrew and campaign_path is not None and campaign_id:
        lib = CampaignLibrary(campaign_path, rules_path=rules_path)
        for item in lib.list_entries(campaign_id, category=clean_cat):
            if tokens:
                hay = _entry_haystack(item)
                if not any(tok in hay for tok in tokens):
                    continue
            results.append(item)

    if strict_names:
        results = [item for item in results if _matches_strict_name(item, norm_q, tokens)]

    results.sort(key=lambda item: _rank_entry(item, norm_q, tokens))
    deduped: list[dict[str, Any]] = []
    seen_keys: set[tuple[Any, Any, str]] = set()
    for item in results:
        key = (
            item.get("source"),
            item.get("category"),
            sourcecatalog._normalize(str(item.get("name") or "")),
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(item)
        if len(deduped) >= bound_limit:
            break
    return deduped


def get_library_entry(
    entry_id: str,
    *,
    rules_path: str | Path | None = None,
    campaign_path: str | Path | None = None,
    campaign_id: str | None = None,
) -> dict[str, Any] | None:
    if not isinstance(entry_id, str) or not entry_id.strip():
        return None
    if entry_id.startswith("corebook:") and rules_path is not None:
        resolved = Path(rules_path).expanduser().resolve()
        if not resolved.is_file():
            return None
        conn = sqlite3.connect(resolved.as_uri() + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            has_entries = (
                _table_exists(conn, "rule_entries")
                and conn.execute("SELECT 1 FROM rule_entries LIMIT 1").fetchone() is not None
            )
            if has_entries:
                row = conn.execute("SELECT * FROM rule_entries WHERE id=?", (entry_id,)).fetchone()
                return _row_to_entry(row) if row else None
            for item in _load_corebook_entries(resolved, conn):
                if item["id"] == entry_id:
                    return item
        finally:
            conn.close()
        return None
    if campaign_path is not None and campaign_id:
        return CampaignLibrary(campaign_path, rules_path=rules_path).get_entry(campaign_id, entry_id)
    return None


def load_corebook_entries(rules_path: str | Path | None) -> list[dict[str, Any]]:
    """Return all rule_entries from rules.sqlite (or extract on the fly if unmaterialized)."""
    if rules_path is None:
        return []
    resolved = Path(rules_path).expanduser().resolve()
    if not resolved.is_file():
        return []
    conn = sqlite3.connect(resolved.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        has_entries = (
            _table_exists(conn, "rule_entries")
            and conn.execute("SELECT 1 FROM rule_entries LIMIT 1").fetchone() is not None
        )
        if has_entries:
            rows = conn.execute("SELECT * FROM rule_entries ORDER BY category, name").fetchall()
            return [_row_to_entry(r) for r in rows]
        return _load_corebook_entries(resolved, conn)
    finally:
        conn.close()


def query_roles_data(rules_path: str | Path | None) -> dict[str, dict[str, Any]]:
    """Return role summaries/abilities extracted from rules.sqlite keyed by canonical role title."""
    entries = load_corebook_entries(rules_path)
    out: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if entry.get("category") != "role":
            continue
        name = str(entry.get("name") or "").strip()
        matched_role = next((r.title() for r in ROLE_NAMES if re.search(rf"\b{r}\b", name, re.I)), None)
        if not matched_role:
            continue
        stats = entry.get("stats") if isinstance(entry.get("stats"), dict) else {}
        out.setdefault(
            matched_role,
            {
                "name": matched_role,
                "ability": str(stats.get("role_ability") or ""),
                "ability_summary": str(entry.get("summary") or ""),
                "description": str(entry.get("description") or ""),
                "key_stats": list(stats.get("key_stats") or []),
                "printed_page": entry.get("printed_page"),
            },
        )
    return out


def query_lifepath_data(rules_path: str | Path | None) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """Return (cultural_regions, lifepath_tables) extracted from rules.sqlite."""
    entries = load_corebook_entries(rules_path)
    cultural_regions: list[dict[str, Any]] = []
    lifepath_tables: dict[str, list[str]] = {}
    for entry in entries:
        if entry.get("category") != "rule":
            continue
        tags = set(entry.get("tags") or [])
        if "lifepath" not in tags:
            continue
        stats = entry.get("stats") if isinstance(entry.get("stats"), dict) else {}
        tkey = stats.get("table_key")
        if tkey == "cultural_regions" and isinstance(stats.get("regions"), list):
            cultural_regions = list(stats["regions"])
        elif isinstance(tkey, str) and isinstance(stats.get("options"), list):
            lifepath_tables[tkey] = [str(opt) for opt in stats["options"] if str(opt).strip()]
    return cultural_regions, lifepath_tables


def query_campaign_presets(rules_path: str | Path | None) -> dict[str, Any]:
    """Return districts, factions, caper styles, zone types, threat ratings, and screamsheets from rules.sqlite."""
    entries = load_corebook_entries(rules_path)
    districts: list[dict[str, Any]] = []
    factions: list[dict[str, Any]] = []
    caper_styles: list[dict[str, Any]] = []
    zone_types: list[dict[str, Any]] = []
    threat_ratings: list[dict[str, Any]] = []
    screamsheets: list[dict[str, Any]] = []
    screamsheet_hooks: list[str] = []

    for entry in entries:
        cat = entry.get("category")
        stats = entry.get("stats") if isinstance(entry.get("stats"), dict) else {}
        tags = set(entry.get("tags") or [])
        if cat == "location":
            districts.append({
                "name": entry["name"],
                "zone_type": str(stats.get("zone_type") or ""),
                "threat_rating": str(stats.get("threat_rating") or ""),
                "summary": entry.get("summary") or "",
                "printed_page": entry.get("printed_page"),
            })
        elif cat == "faction":
            factions.append({
                "name": entry["name"],
                "type": str(stats.get("type") or "Faction"),
                "summary": entry.get("summary") or "",
                "printed_page": entry.get("printed_page"),
            })
        elif cat == "screamsheet":
            hook_text = str(entry.get("description") or entry.get("summary") or "")
            screamsheets.append({
                "id": entry["id"],
                "headline": str(stats.get("headline") or entry["name"]),
                "district": str(stats.get("district") or ""),
                "factions": list(stats.get("factions") or []),
                "payout_eb": int(stats.get("payout_eb") or 0),
                "summary": entry.get("summary") or "",
                "hook": hook_text,
            })
            if hook_text:
                screamsheet_hooks.append(hook_text)
        elif cat == "rule":
            if "zone-type" in tags:
                zone_types.append({
                    "name": entry["name"],
                    "printed_page": entry.get("printed_page"),
                    "summary": entry.get("summary") or "",
                })
            elif "threat-rating" in tags:
                threat_ratings.append({
                    "name": entry["name"],
                    "ncpd_response": str(stats.get("ncpd_response") or ""),
                    "summary": entry.get("summary") or "",
                })
            elif "caper-style" in tags or "beat-chart" in tags:
                caper_styles.append({
                    "id": str(stats.get("caper_id") or _slug(entry["name"])),
                    "name": entry["name"],
                    "printed_page": entry.get("printed_page"),
                    "summary": entry.get("summary") or "",
                    "default_beats": dict(stats.get("default_beats") or {}),
                })

    return {
        "districts": districts,
        "factions": factions,
        "caper_styles": caper_styles,
        "screamsheet_hooks": screamsheet_hooks,
        "zone_types": zone_types,
        "threat_ratings": threat_ratings,
        "screamsheets": screamsheets,
    }
