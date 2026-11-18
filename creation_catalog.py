"""Corebook Armory, Exotic Weapons, Quality Brands, Armor Pieces, Hardware, and AI Assist."""
from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Any

import corebook_gm_data
from corebook_gm_data import (
    ROLE_HUSTLES_60,
    MARTIAL_ARTS_MOVES,
    DV_TABLE,
    REPAIR_TABLE,
    CRITICAL_INJURIES_TABLE,
    BEAT_CHART_63,
    PLAYSTYLE_IP_TABLE,
    build_corebook_net_catalog,
    build_corebook_cyberware_additions,
    build_corebook_ammo_attachments_exotics,
    build_corebook_services_housing_fashion,
    build_corebook_mooks_and_encounters,
    build_corebook_opponents,
    build_corebook_encounters,
    build_corebook_rules_reference,
)


def build_all_gm_data_entries() -> list[dict[str, Any]]:
    """Return all 368 canonical Corebook GM data entries."""
    if (
        hasattr(corebook_gm_data, "build_all_gm_data_entries")
        and corebook_gm_data.build_all_gm_data_entries != build_all_gm_data_entries
    ):
        return corebook_gm_data.build_all_gm_data_entries()
    entries: list[dict[str, Any]] = []
    entries.extend(build_corebook_net_catalog())
    entries.extend(build_corebook_cyberware_additions())
    entries.extend(build_corebook_ammo_attachments_exotics())
    entries.extend(build_corebook_services_housing_fashion())
    entries.extend(build_corebook_mooks_and_encounters())
    entries.extend(build_corebook_rules_reference())
    return entries


if not hasattr(corebook_gm_data, "build_all_gm_data_entries"):
    corebook_gm_data.build_all_gm_data_entries = build_all_gm_data_entries


_EXOTIC_WEAPON_CANONICAL = {
    "air pistol": "Air Pistol",
    "battleglove": "Battleglove",
    "constitution arms hurricane assault weapon": "Constitution Arms Hurricane Assault Weapon",
    "dartgun": "Dartgun",
    "flamethrower": "Flamethrower",
    "kendachi mono-three": "Kendachi Mono-Three",
    "malorian arms 3516": "Malorian Arms 3516",
    "microwaver": "Microwaver",
    "militech cowboy u-56 grenade launcher": "Militech Cowboy U-56 Grenade Launcher",
    "rhinemetall emg-86 railgun": "Rhinemetall EMG-86 Railgun",
    "shrieker": "Shrieker",
    "stun baton": "Stun Baton",
    "stun gun": "Stun Gun",
    "tsunami arms helix": "Tsunami Arms Helix",
}


def _get_exotic_key(name: str) -> str | None:
    import sourcecatalog

    clean = re.sub(r"\s*\(Exotic[^)]*\)", "", name, flags=re.I).replace('"', "").replace("'", "")
    norm = sourcecatalog._normalize(clean)
    norm = re.sub(r"[\s\-]+", " ", norm).strip()
    for k in _EXOTIC_WEAPON_CANONICAL:
        k_norm = re.sub(r"[\s\-]+", " ", k).strip()
        if norm == k_norm:
            return k
    return None


def _dedup_key(cat: str, name: str) -> tuple[str, str]:
    import sourcecatalog

    exotic = _get_exotic_key(name)
    if exotic and cat in ("weapon", "gear"):
        return ("weapon", exotic)
    clean = re.sub(r"\s*\((?:Attachment|Cyberdeck|Standard Brand)[^)]*\)", "", name, flags=re.I)
    clean = re.sub(r"\s*\(x\d+\s+Rounds\)", "", clean, flags=re.I)
    norm = sourcecatalog._normalize(clean.strip())
    return (cat, norm)


def parse_hl_int(raw: Any) -> int:
    """Extract numeric Humanity Loss integer from Corebook values like '7 (2d6)'."""
    if isinstance(raw, int) and not isinstance(raw, bool):
        return max(0, raw)
    if isinstance(raw, str):
        m = re.match(r"\s*(\d+)", raw)
        if m:
            return int(m.group(1))
    return 0


def parse_sp_int(raw: Any) -> int:
    """Extract integer Stopping Power from strings like '11', 'SP 18', or '13 (Body)'."""
    if isinstance(raw, int) and not isinstance(raw, bool):
        return max(0, raw)
    if isinstance(raw, str):
        if "hp" in raw.lower():
            return 0
        m = re.search(r"(\d+)", raw)
        if m:
            return int(m.group(1))
    return 0


def _weapon_item(
    slug: str,
    name: str,
    cost_eb: int,
    *,
    subtype: str,
    skill: str,
    damage: str,
    rof: int,
    hands: int,
    concealable: bool,
    mag: str,
    quality: str,
    printed_page: int,
    summary: str,
    description: str,
) -> dict[str, Any]:
    return {
        "id": f"corebook:weapon:{slug}",
        "name": name,
        "category": "weapon",
        "cost_eb": cost_eb,
        "summary": summary,
        "description": description,
        "printed_page": printed_page,
        "stats": {
            "subtype": subtype,
            "quality": quality,
            "skill": skill,
            "single_shot_damage": damage,
            "rate_of_fire_rof": rof,
            "hands": hands,
            "can_be_concealed": "YES" if concealable else "NO",
            "standard_magazine": mag,
            "cost_eb": cost_eb,
        },
    }


def build_corebook_weapons() -> list[dict[str, Any]]:
    """Return Corebook named brand quality variants, melee examples, exotic weapons, attachments, and ammo."""
    items: list[dict[str, Any]] = []

    # Ranged Brand Examples (Corebook p. 341-342)
    ranged_specs = [
        ("Medium Pistol", "Handgun", "2d6", 2, 1, True, "12 (M Pistol)", 50, 20, 100,
         "Dai Lung Streetmaster", "Federated Arms X-9mm", 'Militech "Avenger"'),
        ("Heavy Pistol", "Handgun", "3d6", 2, 1, True, "8 (H Pistol)", 100, 50, 500,
         "Dai Lung Magnum", 'Mustang Arms "Mark III"', 'Nova "Cityhunter"'),
        ("Very Heavy Pistol", "Handgun", "4d6", 1, 1, False, "8 (VH Pistol)", 100, 50, 500,
         'Federated Arms "Super Chief"', "Sternmeyer P-35", 'Militech "Boomer Buster"'),
        ("SMG", "Handgun / Autofire", "2d6 (AF x3)", 1, 1, True, "30 (M Pistol)", 100, 50, 500,
         "Federated Arms Tech-Assault III", 'Militech "Mini-Gat"', 'Arasaka "Minami 10"'),
        ("Heavy SMG", "Handgun / Autofire", "3d6 (AF x3)", 1, 1, False, "40 (H Pistol)", 100, 50, 500,
         'Chadran Arms "City Reaper"', "Sternmeyer SMG-21", 'Militech "Viper"'),
        ("Shotgun", "Shoulder Arms", "5d6 (or 3d6 Shells)", 1, 2, False, "4 (Slug/Shell)", 500, 100, 1000,
         'GunMart "Home Defender"', 'Arasaka "Rapid Assault"', 'Militech "Bulldog"'),
        ("Assault Rifle", "Shoulder Arms / Autofire", "5d6 (AF x4)", 1, 2, False, "25 (Rifle)", 500, 100, 1000,
         'Chadran Arms "Jungle Reaper"', 'Militech "Ronin"', 'Militech "Dragon"'),
        ("Sniper Rifle", "Shoulder Arms", "5d6", 1, 2, False, "4 (Rifle)", 500, 100, 1000,
         'GunMart "Snipe-Star"', 'Nomad "Long Rifle"', "Arasaka WSSA Sniper System"),
        ("Bow", "Archery", "4d6", 1, 2, False, "Arrow", 100, 50, 500,
         'GunMart "Sherwood"', 'Eagletech "Tomcat"', 'Eagletech "Bearcat"'),
        ("Crossbow", "Archery", "4d6", 1, 2, False, "Arrow", 100, 50, 500,
         'GunMart "Hunter"', 'Eagletech "Striker"', 'Eagletech "Scorpion"'),
        ("Grenade Launcher", "Heavy Weapons", "6d6 (Blast)", 1, 2, False, "2 (Grenade)", 500, 100, 1000,
         "Towa Manufacturing Type-G", 'Militech "Mini-Grenade"', "Tsunami Arms Type-18"),
        ("Rocket Launcher", "Heavy Weapons", "8d6 (Blast)", 1, 2, False, "1 (Rocket)", 500, 100, 1000,
         "Towa Manufacturing Type-R", 'Militech "Urban"', 'Militech "Hotshot"'),
    ]

    for (
        base_class, skill, dmg, rof, hands, conceal, mag,
        std_cost, poor_cost, exc_cost, poor_name, std_name, exc_name
    ) in ranged_specs:
        is_heavy = skill == "Heavy Weapons"
        slug_base = re.sub(r"[^a-z0-9]+", "-", base_class.lower()).strip("-")
        items.append(_weapon_item(
            f"{slug_base}-std",
            f"{std_name} ({base_class})",
            std_cost,
            subtype="Heavy Weapon" if is_heavy else "Standard Brand",
            skill=skill, damage=dmg, rof=rof, hands=hands, concealable=conceal, mag=mag,
            quality="Standard", printed_page=342,
            summary=f"Standard {base_class} · {dmg} · ROF {rof} · {skill}",
            description=f"{std_name} is a reliable Standard Quality {base_class} ({skill}). Deals {dmg} damage, ROF {rof}, {mag} mag, {hands}H.",
        ))
        items.append(_weapon_item(
            f"{slug_base}-exc",
            f"{exc_name} (Excellent {base_class})",
            exc_cost,
            subtype="Heavy Weapon" if is_heavy else "Excellent (+1 Hit)",
            skill=skill, damage=dmg, rof=rof, hands=hands, concealable=conceal, mag=mag,
            quality="Excellent (+1 Attack)", printed_page=342,
            summary=f"+1 Attack Check · Excellent {base_class} · {dmg} · ROF {rof}",
            description=f"{exc_name} is an Excellent Quality {base_class} ({skill}, Corebook p. 342). Grants +1 to every Attack Check made with it. {dmg}, ROF {rof}, {mag}.",
        ))
        items.append(_weapon_item(
            f"{slug_base}-poor",
            f"{poor_name} (Poor {base_class})",
            poor_cost,
            subtype="Heavy Weapon" if is_heavy else "Poor / Budget",
            skill=skill, damage=dmg, rof=rof, hands=hands, concealable=conceal, mag=mag,
            quality="Poor (Jams on 1)", printed_page=342,
            summary=f"Budget {base_class} · {dmg} · Jams on Crit Fail (1)",
            description=f"{poor_name} is a cheap Poor Quality {base_class} ({skill}). Same damage ({dmg}), but jams on a Critical Failure (rolling a 1 on Attack Check), costing an Action to clear.",
        ))

    # Named Melee Weapons (Corebook p. 340)
    melee_examples = [
        ("combat-knife", "Combat Knife (Light Melee)", 50, "1d6", 2, 1, True, "Standard", "Concealable 1d6 Light Melee blade (ignores half SP)."),
        ("tomahawk", "Tomahawk (Light Melee)", 50, "1d6", 2, 1, True, "Standard", "Lightweight throwing/close-quarters 1d6 Light Melee weapon (ignores half SP)."),
        ("machete", "Street Machete (Medium Melee)", 50, "2d6", 2, 1, False, "Standard", "Heavy street-chopper blade: 2d6 ROF 2 Medium Melee (ignores half SP)."),
        ("baseball-bat", "Reinforced Baseball Bat (Medium Melee)", 50, "2d6", 2, 2, False, "Standard", "Classic Night City street thumper: 2d6 ROF 2 Medium Melee (ignores half SP)."),
        ("katana-std", "Street Katana / Sword (Heavy Melee)", 100, "3d6", 2, 1, False, "Standard", "Fast 3d6 ROF 2 Heavy Melee blade that halves target armor SP."),
        ("katana-exc", "Arasaka Masterwork Katana (Excellent Heavy Melee)", 500, "3d6", 2, 1, False, "Excellent (+1 Attack)", "+1 Attack Check · Excellent Quality 3d6 ROF 2 Heavy Melee sword."),
        ("spiked-bat", "Spiked Bat (Heavy Melee)", 100, "3d6", 2, 2, False, "Standard", "Heavy Melee weapon (3d6 ROF 2, halves armor SP)."),
        ("naginata", "Naginata Polearm (Very Heavy Melee)", 500, "4d6", 1, 2, False, "Standard", "Long-reach 4d6 Very Heavy Melee blade (ROF 1, halves armor SP)."),
        ("chainsaw", "Ripper Chainsaw (Very Heavy Melee)", 500, "4d6", 1, 2, False, "Standard", "Brutal 4d6 ROF 1 Very Heavy Melee weapon (halves armor SP)."),
        ("sledgehammer", "Demolition Sledgehammer (Very Heavy Melee)", 500, "4d6", 1, 2, False, "Standard", "Massive 4d6 ROF 1 Very Heavy Melee weapon (halves armor SP)."),
    ]
    for slug, name, cost, dmg, rof, hands, conceal, qual, desc in melee_examples:
        items.append(_weapon_item(
            slug, name, cost,
            subtype="Excellent (+1 Hit)" if "Excellent" in qual else "Melee",
            skill="Melee Weapon", damage=dmg, rof=rof, hands=hands, concealable=conceal, mag="Melee",
            quality=qual, printed_page=340, summary=f"{dmg} Melee (halves SP) · ROF {rof}" + (" · +1 Hit" if "Excellent" in qual else ""),
            description=desc,
        ))

    # All 14 Corebook Exotic Weapons (pp. 347-350)
    exotics = [
        ("air-pistol", "Air Pistol (Exotic)", 100, "Handgun", "0 (Acid -1 SP)", 2, 1, False, "12 (Paint/Acid)", 347,
         "Exotic Medium Pistol · Acid paintballs ablate SP -1 without HP damage."),
        ("dartgun", "Dartgun (Exotic)", 100, "Handgun", "Arrow Effect", 1, 1, False, "8 Arrows", 348,
         "Exotic Very Heavy Pistol · Fires 8 Poison/Sleep/Biotoxin arrows silently."),
        ("stun-baton", "Stun Baton (Exotic)", 100, "Melee Weapon", "2d6 Non-Lethal", 2, 1, False, "Charge", 349,
         "Exotic Medium Melee · Drops targets to Unconscious at 1 HP; no Crit or SP ablation."),
        ("stun-gun", "Stun Gun (Exotic)", 100, "Handgun", "3d6 Non-Lethal", 2, 1, True, "8 Shots (Battery)", 349,
         "Exotic Heavy Pistol · Non-lethal shock (Unconscious at 1 HP); rechargeable battery."),
        ("flamethrower", "Flamethrower (Exotic Heavy)", 500, "Heavy Weapons", "Shotgun Fire + 4HP/turn", 1, 2, False, "4 (Incendiary)", 348,
         "Exotic Heavy Weapon · Uses Heavy Weapons skill; sets targets ablaze (4 HP/turn)."),
        ("microwaver", "Microwaver (Exotic)", 500, "Handgun", "Disabled Cyberware", 1, 1, False, "8 Shots (Battery)", 348,
         "Exotic Very Heavy Pistol · DV 15 Cybertech save or 2 cyberware items shut down for 1 min."),
        ("shrieker", "Shrieker (Exotic)", 500, "Handgun", "Damaged Ear Crit", 1, 1, False, "8 Shots (Battery)", 349,
         "Exotic Very Heavy Pistol · Sonic blast inflicts Damaged Ear Critical Injury (DV 15 save)."),
        ("battleglove", "Battleglove (Exotic Cyberarm Gauntlet)", 1000, "Brawling / Cyberware", "Holds 3 Cyberarm Slots", 2, 1, False, "3 Option Slots", 347,
         "Exotic heavy armored gauntlet with 3 Cyberarm Option Slots for un-chromed arms."),
        ("constitution-hurricane", "Constitution Arms Hurricane Assault Weapon", 5000, "Shoulder Arms", "5d6 / 3d6 Shells (ROF 2!)", 2, 2, False, "16-Shot Drum", 348,
         "Exotic ROF 2 Assault Shotgun! Requires BODY 11+ (or mount). 16-shell drum."),
        ("kendachi-mono-three", "Kendachi Mono-Three", 5000, "Melee Weapon", "4d6 (Ignores SP < 11)", 1, 2, False, "Biometric Key", 348,
         "Excellent (+1 Hit) Exotic Crystal Katana · Ignores target armor entirely if SP < 11!"),
        ("militech-cowboy", 'Militech "Cowboy" U-56 Grenade Launcher', 5000, "Heavy Weapons", "6d6 (ROF 2 Grenades!)", 2, 2, False, "4 Grenades", 349,
         "Exotic ROF 2 Drum Grenade Launcher! Fires any grenade ammo. Requires BODY 11+."),
        ("rhinemetall-railgun", "Rhinemetall EMG-86 Railgun", 5000, "Heavy Weapons", "5d6 (Ignores SP < 11)", 1, 2, False, "4 Slugs", 349,
         "Exotic electromagnetic Heavy Weapon · Completely ignores armor below SP 11. Requires BODY 11+."),
        ("tsunami-helix", "Tsunami Arms Helix", 5000, "Autofire", "2d6 × margin (up to ×5!)", 1, 2, False, "40 (20/burst)", 349,
         "Exotic Gatling Autofire Rifle · Up to x5 multiplier! Requires BODY 11+ or mount."),
        ("malorian-3516", "Malorian Arms 3516", 10000, "Handgun", "5d6", 1, 1, False, "4 (VH Pistol)", 348,
         "Legendary Johnny Silverhand Excellent (+1 Hit) Exotic Pistol · 5d6 damage, Smartgun Link, non-concealable."),
    ]
    for slug, name, cost, skill, dmg, rof, hands, conceal, mag, pg, desc in exotics:
        items.append(_weapon_item(
            slug, name, cost,
            subtype="Exotic Heavy" if (cost >= 5000 or skill == "Heavy Weapons") else "Exotic",
            skill=skill, damage=dmg, rof=rof, hands=hands, concealable=conceal, mag=mag,
            quality="Excellent (+1 Attack)" if ("Malorian" in name or "Kendachi" in name) else "Exotic",
            printed_page=pg,
            summary=f"Exotic · {dmg} · {skill}",
            description=desc,
        ))

    # Weapon Attachments (Corebook pp. 343-344)
    attachments = [
        ("att-bayonet", "Bayonet (Attachment)", 100, 343, "Shoulder Arms weapon doubles as a 1d6 Light Melee Weapon (makes gun non-concealable)."),
        ("att-ext-mag", "Extended Magazine (Attachment)", 100, 343, "Increases weapon magazine capacity by ~50% (cannot conceal weapon)."),
        ("att-sniping-scope", "Sniping Scope (Attachment)", 100, 344, "+1 to Single Shot or Aimed Shots at 51m+ distance (up to 800m optics)."),
        ("att-drum-mag", "Drum Magazine (Attachment)", 500, 343, "Huge drum magazine (e.g. 28 pistol / 45 rifle / 60 SMG rounds; non-concealable)."),
        ("att-ir-scope", "Infrared Nightvision Scope (Attachment)", 500, 343, "Negates darkness, smoke, and fog penalties down to 0."),
        ("att-smartgun-link", "Smartgun Link (Attachment · 2 Slots)", 500, 344, "+1 to Ranged Attack Checks when linked via Neural Link + Subdermal Grip or Interface Plugs."),
        ("att-ub-shotgun", "Shotgun Underbarrel (Attachment · 2 Slots)", 500, 343, "Adds a 2-shot Shotgun directly underneath a Shoulder Arms longarm."),
        ("att-ub-grenade", "Grenade Launcher Underbarrel (Attachment · 2 Slots)", 500, 343, "Adds a 1-shot Grenade Launcher underneath a Shoulder Arms longarm."),
    ]
    for slug, name, cost, pg, desc in attachments:
        items.append(_weapon_item(
            slug, name, cost,
            subtype="Attachment", skill="Weapon Mod", damage="Mod", rof=1, hands=0, concealable=False, mag="Attachment",
            quality="Attachment", printed_page=pg, summary=desc, description=desc,
        ))

    # Ammunition & Grenades (Corebook pp. 344-347)
    ammo_rows = [
        ("ammo-basic", "Basic Ammunition (x10 Rounds)", 10, 345, "Standard lead rounds (box of 10: specify Pistol, Rifle, Shotgun Slug/Shell, or Arrow)."),
        ("ammo-ap", "Armor-Piercing Ammunition (x10 Rounds)", 100, 345, "Ablates target armor SP by 2 instead of 1 when damaging through armor."),
        ("ammo-expansive", "Expansive Ammunition (x10 Rounds)", 100, 345, "Inflicts the Foreign Object Critical Injury twice if any Crit occurs."),
        ("ammo-incendiary", "Incendiary Ammunition (x10 Rounds)", 100, 346, "Sets target's clothes/body ablaze (2 HP/turn until extinguished)."),
        ("ammo-rubber", "Rubber Ammunition (x10 Rounds)", 10, 346, "Non-lethal rounds: leaves targets Unconscious at 1 HP, never causes Crits or ablation."),
        ("ammo-smart", "Smart Ammunition (x10 Rounds)", 500, 347, "Self-guided rounds: if you miss by 4 or less, second roll at Base 10 (requires Targeting Scope)."),
        ("ammo-grenade-ap", "Armor-Piercing Grenade (x1)", 100, 345, "Explosive 6d6 blast grenade (10m×10m) that ablates armor SP by 2."),
        ("ammo-grenade-flashbang", "Flashbang Grenade (x1)", 100, 346, "Concussion grenade inflicting Damaged Eye & Damaged Ear Crits on failed DV 15 Resist."),
        ("ammo-grenade-smoke", "Smoke Grenade (x1)", 50, 347, "Obscures a 10m×10m area with thick smoke for 1 minute (-4 penalty through smoke)."),
        ("ammo-grenade-teargas", "Teargas Grenade (x1)", 50, 347, "Chemical cloud causing Damaged Eye Crit for 1 minute on failed DV 13 Resist."),
        ("ammo-grenade-emp", "EMP Grenade (x1)", 500, 345, "Disables 2 cyberware/electronics in 10m×10m blast on failed DV 15 Cybertech check."),
    ]
    for slug, name, cost, pg, desc in ammo_rows:
        items.append(_weapon_item(
            slug, name, cost,
            subtype="Ammo", skill="Ammunition", damage="Ammo", rof=1, hands=0, concealable=True, mag="Consumable",
            quality="Ammo", printed_page=pg, summary=desc, description=desc,
        ))
    return items


def build_corebook_armor() -> list[dict[str, Any]]:
    """Return Corebook Body Armor, Head Armor / Helmets, Bodyweight Suit, and Shields with exact SP & penalties."""
    # Corebook p. 350: Head and Body pieces are purchased separately at the listed cost (except Bodyweight Suit)
    specs = [
        ("leathers", "Leathers", 4, "None", 20, "Thin hardened leather favored by Nomads and street punks."),
        ("kevlar", "Kevlar®", 7, "None", 50, "Sleek ballistic fiber woven into corporate blazers, vests, and street clothes."),
        ("light-armorjack", "Light Armorjack", 11, "None", 100, "Kevlar and flexible plastic plates—zero movement penalty, gold-standard Edgerunner protection."),
        ("medium-armorjack", "Medium Armorjack", 12, "-2 REF, DEX, and MOVE", 100, "Solid polycarbonate plating over dense Kevlar mesh (-2 REF/DEX/MOVE penalty)."),
        ("heavy-armorjack", "Heavy Armorjack", 13, "-2 REF, DEX, and MOVE", 500, "Thick layered tactical Kevlar and ceramic-polymer plates (-2 REF/DEX/MOVE penalty)."),
        ("flak", "Flak", 15, "-4 REF, DEX, and MOVE", 500, "Heavy military blast armor designed against grenades and high-caliber rifles (-4 penalty)."),
        ("metalgear", "Metalgear®", 18, "-4 REF, DEX, and MOVE", 5000, "Walking tank full-plate armor capable of stopping extreme rifle fire (-4 penalty)."),
    ]
    items: list[dict[str, Any]] = []
    for slug, label, sp, penalty, cost, blurb in specs:
        pen_tag = "No Penalty" if penalty == "None" else penalty
        items.append({
            "id": f"corebook:armor:{slug}-body",
            "name": f"{label} Body Armor (SP {sp})",
            "category": "armor",
            "cost_eb": cost,
            "summary": f"Body Slot · SP {sp} · {pen_tag}",
            "description": f"{label} Body Armor (Corebook p. 350): Covers torso/arms/legs with SP {sp}. Armor Penalty: {penalty}. {blurb}",
            "printed_page": 350,
            "stats": {
                "sp": sp,
                "damage_stopping_power_sp": str(sp),
                "location": "Body",
                "armor_penalty_minimum_0": penalty,
                "cost_eb": cost,
            },
        })
        items.append({
            "id": f"corebook:armor:{slug}-head",
            "name": f"{label} Head Armor / Helmet (SP {sp})",
            "category": "armor",
            "cost_eb": cost,
            "summary": f"Head Slot · SP {sp} · {pen_tag}",
            "description": f"{label} Helmet / Headwear (Corebook p. 350): Protects against headshots (2x damage!) with SP {sp}. Armor Penalty: {penalty}.",
            "printed_page": 350,
            "stats": {
                "sp": sp,
                "damage_stopping_power_sp": str(sp),
                "location": "Head",
                "armor_penalty_minimum_0": penalty,
                "cost_eb": cost,
            },
        })
    items.append({
        "id": "corebook:armor:bodyweight-suit",
        "name": "Bodyweight Suit (Head & Body SP 11)",
        "category": "armor",
        "cost_eb": 1000,
        "summary": "Head + Body SP 11 · +1 Cyberdeck Hardware Slot · No Penalty",
        "description": "Full-body armorgel skinsuit covering BOTH Head and Body (SP 11 each), storing your Cyberdeck + Interface Plugs and adding 1 bonus Cyberdeck Hardware Slot (Corebook p. 350).",
        "printed_page": 350,
        "stats": {
            "sp": 11,
            "damage_stopping_power_sp": "11",
            "location": "Body & Head",
            "armor_penalty_minimum_0": "None",
            "cost_eb": 1000,
        },
    })
    items.append({
        "id": "corebook:armor:bulletproof-shield",
        "name": "Bulletproof Shield (10 HP)",
        "category": "armor",
        "cost_eb": 100,
        "summary": "Shield (1 Arm) · Absorbs 10 HP before breaking",
        "description": "Transparent polycarbonate tactical shield carried in one arm; takes up to 10 HP of incoming attack damage (Corebook pp. 183, 351).",
        "printed_page": 350,
        "stats": {
            "sp": 0,
            "damage_stopping_power_sp": "10 HP shield",
            "location": "Shield",
            "armor_penalty_minimum_0": "Requires 1 arm",
            "cost_eb": 100,
        },
    })
    return items


def build_corebook_hardware() -> list[dict[str, Any]]:
    """Return Corebook Cyberdeck Hardware & Cyberdeck tiers (pp. 351, 368)."""
    hw = [
        ("hw-backup-drive", "Backup Drive (Cyberdeck · 2 Slots)", 100, 368, "Saves destroyed Non-Black ICE Attacker/Defender/Booster programs so you can reinstall them later."),
        ("hw-dna-lock", "DNA Lock (Cyberdeck · 2 Slots)", 100, 368, "Biometrically locks your Cyberdeck against unauthorized Netrunners (DV 17 Security Tech to bypass)."),
        ("hw-hardened-circuitry", "Hardened Circuitry (Cyberdeck · 1 Slot)", 100, 368, "Renders your Cyberdeck immune to EMP pulses and hardware-disabling Non-Black ICE effects."),
        ("hw-insulated-wiring", "Insulated Wiring (Cyberdeck · 1 Slot)", 100, 368, "Prevents your Cyberdeck or clothing from catching fire due to Black ICE / Program effects."),
        ("hw-krash-barrier", "KRASH Barrier (Cyberdeck · 2 Slots)", 100, 368, "Protects you from Program Effects that forcibly Jack Out the Netrunner."),
        ("hw-range-upgrade", "Range Upgrade (Cyberdeck · 1 Slot)", 100, 368, "Increases NET Access Point wireless connection range to 8 meters instead of 6 meters."),
        ("deck-poor", "Cyberdeck (Poor Quality · 5 Slots)", 100, 351, "Entry-level 5-slot Cyberdeck for Netrunners on a budget."),
        ("deck-std", "Cyberdeck (Standard Quality · 7 Slots)", 500, 351, "Reliable 7-slot Cyberdeck for holding Programs and Hardware upgrades."),
        ("deck-exc", "Cyberdeck (Excellent Quality · 9 Slots)", 1000, 351, "High-capacity 9-slot Cyberdeck built for serious NET runs."),
    ]
    return [
        {
            "id": f"corebook:hardware:{slug}",
            "name": name,
            "category": "hardware",
            "cost_eb": cost,
            "summary": desc,
            "description": desc,
            "printed_page": pg,
            "stats": {"cost_eb": cost},
        }
        for slug, name, cost, pg, desc in hw
    ]


def build_corebook_vehicles() -> list[dict[str, Any]]:
    """Return official Cyberpunk RED Corebook vehicles (pp. 190-191)."""
    specs = [
        ("roadbike", "Roadbike", "Land", 20000, 35, 2, "20 MOVE / 100 MPH", 190, "Common CHOOH2 powered bike: nimble in traffic and standard Nomad starter pick."),
        ("superbike", "Superbike", "Land", 100000, 35, 2, "60 MOVE / 300 MPH", 190, "Exotic CHOOH2 streetbike capable of extreme speeds up to 300 MPH."),
        ("compact-groundcar", "Compact Groundcar", "Land", 30000, 50, 4, "20 MOVE / 100 MPH", 190, "Common CHOOH2 powered passenger sedan or Nomad compact cruiser."),
        ("high-perf-groundcar", "High Performance Groundcar", "Land", 50000, 50, 4, "40 MOVE / 200 MPH", 190, "CHOOH2 powered sportscar: tuned coupe or interceptor cruiser with 40 MOVE combat speed."),
        ("super-groundcar", "Super Groundcar", "Land", 100000, 50, 2, "60 MOVE / 300 MPH", 190, "Exotic CHOOH2 hypercar capable of extreme speeds up to 300 MPH favored by high-rollers."),
        ("nomad-kombi", "Nomad Kombi", "Land", 31000, 70, 4, "20 MOVE / 100 MPH", 165, "Customized live-in Nomad family groundcar (Compact Groundcar base + Heavy Chassis + Housing Capacity)."),
        ("jetski", "Jetski", "Sea", 20000, 35, 2, "20 MOVE / 60 MPH", 190, "Common CHOOH2 powered personal watercraft for rapid maneuvering along Night City waterways."),
        ("speedboat", "Speedboat", "Sea", 30000, 50, 4, "20 MOVE / 60 MPH", 190, "CHOOH2 powered speedboat: reliable 4-seat craft for open water transit or harbor smuggling."),
        ("cabin-cruiser", "Cabin Cruiser", "Sea", 60000, 60, 4, "10 MOVE / 15 MPH", 190, "Luxury CHOOH2 powerboat with room to provide accommodations (30,000eb per room below deck, min 2 rooms = 60,000eb)."),
        ("yacht", "Yacht", "Sea", 200000, 100, 16, "10 MOVE / 15 MPH", 190, "Luxury CHOOH2 pleasurecraft providing accommodations and entertainment (50,000eb per room, min 4 rooms = 200,000eb)."),
        ("gyrocopter", "Gyrocopter", "Air", 20000, 35, 2, "20 MOVE / 100 MPH", 191, "Tiny CHOOH2 powered rotorcraft favored by flying enthusiasts for Badlands recon and rooftop drops."),
        ("helicopter", "Helicopter", "Air", 40000, 60, 4, "40 MOVE / 200 MPH", 191, "Full-featured CHOOH2 powered helicopter capable of sustained flight and tactical air mobility."),
        ("av-4", "AV-4 Multipurpose Aerodyne", "Air", 50000, 100, 6, "40 MOVE / 200 MPH", 191, "Highly advanced CHOOH2 vertical thrust engine powered flying vehicle used by Trauma Team and Corp security."),
        ("av-9", "AV-9 Super Aerodyne", "Air", 100000, 60, 2, "60 MOVE / 300 MPH", 191, "Exotic CHOOH2 vertical thrust engine flying vehicle capable of extreme speeds hitting 300 MPH."),
        ("aerozep", "Aerozep", "Air", 60000, 100, 4, "20 MOVE / 100 MPH", 191, "Modern cargo blimp with customized rooms for long-range transport (30,000eb per room below deck, min 2 rooms = 60,000eb)."),
    ]
    return [
        {
            "id": f"corebook:vehicle:{slug}",
            "name": name,
            "category": "vehicle",
            "cost_eb": cost,
            "summary": f"{vtype} · {sdp} SDP · {seats} Seats · {speed}",
            "description": f"{desc} ({vtype} Vehicle, {sdp} SDP, {seats} Seats, Speed: {speed}, Corebook pp. 190-191.)",
            "printed_page": pg,
            "stats": {
                "subtype": f"{vtype} Vehicle",
                "sdp": sdp,
                "seats": seats,
                "speed": speed,
                "cost_eb": cost,
            },
        }
        for slug, name, vtype, cost, sdp, seats, speed, pg, desc in specs
    ]


def build_corebook_drugs() -> list[dict[str, Any]]:
    """Return Corebook Street Drugs (pp. 228-230, 357) and Medtech Pharmaceuticals (p. 150)."""
    street_drugs = [
        ("black-lace", "Black Lace (Street Drug)", 50, 357, "24 hours", "DV 17",
         "Ignore Seriously Wounded penalties for 24h; deals 2d6 Humanity Loss immediately. Secondary (DV 17): -2 REF while sober.",
         "Heavy combat narcotic smoked or injected in an Airhypo. User ignores Seriously Wounded state for 24 hours, but suffers 2d6 Humanity Loss per dose. Failing Resist Torture/Drugs DV 17 addicts the user (-2 REF whenever not high)."),
        ("blue-glass", "Blue Glass (Street Drug)", 20, 357, "4 hours", "DV 15",
         "Hallucinogenic Club/NET party drug causing vivid flashing colors (4h); Secondary (DV 15) causes addiction.",
         "Psychedelic party drug distributed around Night City clubs. Primary effect floods vision with hypnotic flashing colors for 4 hours (GM may call Concentration checks). Failing DV 15 causes psychological addiction."),
        ("boost", "Boost (Street Drug)", 50, 357, "24 hours", "DV 17",
         "+2 INT for 24 hours. Secondary (DV 17): -2 INT permanent addiction penalty.",
         "Synthetic nootropic favored by Netrunners and Techs. Grants +2 INT for 24 hours. Failing Resist Torture/Drugs DV 17 inflicts chronic dependency (-2 INT penalty)."),
        ("smash", "Smash (Street Drug)", 10, 357, "4 hours", "DV 15",
         "+2 to Dance, Contortionist, Conversation, Human Perception, Persuasion & Acting for 4h; Secondary (DV 15): -2 to those skills.",
         "Cheap Time-of-the-Red euphoriant drunk or inhaled at clubs. Adds +2 to six social/performative skills for 4 hours. Failing DV 15 brings crashing social withdrawal (-2 to those skills)."),
        ("synthcoke", "Synthcoke (Street Drug)", 20, 357, "4 hours", "DV 15",
         "+1 REF and paranoid ideation for 4h. Secondary (DV 15): -2 REF whenever not dosing.",
         "Synthetic stimulant granting +1 REF and hyper-vigilant paranoia for 4 hours. Failing Resist Torture/Drugs DV 15 creates severe physical dependence (-2 REF when sober)."),
    ]
    medtech_pharma = [
        ("antibiotic", "Antibiotic (Medtech Pharmaceutical)", 0, 150, "1 week", "Medtech",
         "Target heals an additional +2 HP per day of natural rest for 1 full week (Medical Tech synthesis).",
         "Synthesized via Medtech Medical Tech (200 eb materials = doses equal to Medical Tech rank). Boosts natural recovery by +2 HP/day for 7 days."),
        ("rapidetox", "Rapidetox (Medtech Pharmaceutical)", 0, 150, "Instant", "Medtech",
         "Immediately purges all active drugs, toxins, and poisons from an affected patient (p. 150).",
         "Synthesized via Medtech Medical Tech. Applied with an Airhypo to immediately neutralize Street Drugs, biotoxins, or poison effects."),
        ("speedheal", "Speedheal (Medtech Pharmaceutical)", 0, 150, "1 day", "Medtech",
         "Immediately restores HP equal to patient's BODY + WILL (usable once per day, p. 150).",
         "Emergency trauma stabilizer synthesized via Medtech Medical Tech. Patient immediately regains HP equal to BODY + WILL. Once per day limit."),
        ("stim", "Stim (Medtech Pharmaceutical)", 0, 150, "1 hour", "Medtech",
         "Eliminates all Seriously Wounded penalties for 1 full hour cleanly without Humanity loss (p. 150).",
         "Clinical-grade combat stimulant synthesized via Medtech Medical Tech. Negates Seriously Wounded penalties for 1 hour without Black Lace's Humanity Loss."),
        ("surge", "Surge (Medtech Pharmaceutical)", 0, 150, "24 hours", "Medtech",
         "Removes fatigue and allows target to stay sharp for 24 hours without sleep (once per week, p. 150).",
         "Alertness formula synthesized via Medtech Medical Tech. Eliminates sleep deprivation penalties for 24 hours; safe up to once per week."),
    ]
    out: list[dict[str, Any]] = []
    for slug, name, cost, pg, dur, dv, summary, desc in street_drugs + medtech_pharma:
        is_pharma = dv == "Medtech"
        out.append({
            "id": f"corebook:drug:{slug}",
            "name": name,
            "category": "drug",
            "cost_eb": cost,
            "summary": summary,
            "description": desc,
            "printed_page": pg,
            "stats": {
                "subtype": "Medtech Pharmaceutical" if is_pharma else "Street Drug",
                "duration": dur,
                "addiction_dv": dv,
                "cost_eb": cost,
            },
        })
    return out


def build_corebook_gear() -> list[dict[str, Any]]:
    """Return canonical general gear items (pp. 351-353) not covered by specialized catalogs."""
    gear_items = [
        ("airhypo", "Airhypo", 50, 351, "Compressed-gas needleless injector for clean administration of Street Drugs or Medtech Pharmaceuticals.", "Standard pocket pneumatic injector (p. 351). Delivers single doses of Street Drugs or Pharmaceuticals quickly without messy IV prep."),
        ("vial-poison", "Vial of Poison", 100, 351, "Vial of concentrated poison applied to melee weapons or loaded into dartgun/arrows.", "Concentrated chemical poison (p. 351). DV 13 Resist Torture/Drugs or suffer 2d6 direct damage to HP."),
        ("vial-biotoxin", "Vial of Biotoxin", 500, 351, "Vial of lethal military-grade biotoxin applied to weapons or darts.", "Military-grade synthetic biotoxin (p. 351). DV 15 Resist Torture/Drugs or suffer 3d6 direct damage to HP."),
        ("agent", "Agent", 100, 351, "AI-powered pocket communications and computing assistant with adaptive learning.", "Standard personal smartphone and digital assistant with adaptive personality and lifestyle monitoring (p. 351)."),
        ("cryopump", "Cryopump", 5000, 351, "Portable cryo-stabilization bag placing a dying patient into stasis for up to 1 week.", "Suitcase medical pump operated by Medtechs to put mortally wounded targets into stasis, halting Death Saves (p. 351)."),
        ("cryotank", "Cryotank", 5000, 351, "Full-immersion medical stasis tank providing double natural healing rate.", "Heavy medical clinic stasis tank requiring Medtech operation, doubling natural healing rate (p. 351)."),
        ("linear-frame-sigma", "Linear Frame ∑ (Sigma)", 1000, 351, "Powered external exoskeleton boosting user BODY to 12 (requires Interface Plugs).", "External hydraulic skeleton raising user BODY to 12 without changing HP or Death Saves (p. 351)."),
        ("linear-frame-beta", "Linear Frame ß (Beta)", 5000, 351, "Heavy military external exoskeleton boosting user BODY to 14 (requires 2 Interface Plugs).", "Heavy hydraulic frame raising user BODY to 14 without changing HP or Death Saves (p. 351)."),
    ]
    return [
        {
            "id": f"corebook:gear:{slug}",
            "name": name,
            "category": "gear",
            "cost_eb": cost,
            "summary": summary,
            "description": desc,
            "printed_page": pg,
            "stats": {"cost_eb": cost},
        }
        for slug, name, cost, pg, summary, desc in gear_items
    ]


def build_corebook_roles() -> list[dict[str, Any]]:
    """Return official summaries for all 10 Cyberpunk RED Roles (pp. 29-39, 142-184)."""
    roles = [
        ("solo", "Solo", 146, "Combat Awareness", "Peacekeeper, bodyguard, assassin, or merc. Allocates Combat Awareness points across Damage Deflection, Fumble Recovery, Initiative Reaction, Precision Attack, Spot Weakness, and Threat Detection."),
        ("netrunner", "Netrunner", 147, "Interface", "Cybernetic master hacker running NET Architectures via Cyberdeck & Interface rank to breach Control Nodes, dodge Black ICE, and extract data."),
        ("tech", "Tech", 147, "Maker", "Gearhead, armsmith, and cybertech. Splits Maker points across Field Expertise, Upgrade Expertise, Fabrication, and Invention Expertise."),
        ("medtech", "Medtech", 149, "Medicine", "Trauma surgeon and street doc. Allocates Medicine into Surgery, Pharmaceuticals (crafting Speedheal/Stim/etc.), and Cryosystem Operation."),
        ("media", "Media", 151, "Credibility", "Investigative reporter or scream-streamer whose Credibility swings public opinion, turns rumors into leads, and topples corrupt Corps."),
        ("exec", "Exec", 153, "Teamwork", "Corporate power broker with a Company Conapt, Trauma Team/Health perks, and loyal Team minions (drivers, covert operatives, bodyguards)."),
        ("lawman", "Lawman", 158, "Backup", "NCPD officer, sheriff, or badge who radios in escalating Backup squads (from Beat Cops up to Heavy MAX-TAC / SWAT) under fire."),
        ("fixer", "Fixer", 159, "Operator", "Street dealmaker, Fence, and Night Market host. Uses Operator Reach & Grease to source rare gear and haggle prices down."),
        ("nomad", "Nomad", 161, "Moto", "Road warrior and smuggler connected to a Nomad Family Motorpool, starting with customizable family vehicles and vehicular upgrades."),
        ("rockerboy", "Rockerboy", 144, "Charismatic Impact", "Rebel artist, idol, or activist using Charismatic Impact to sway crowds from small club venues up to riotous stadium mobs."),
    ]
    return [
        {
            "id": f"corebook:role:{slug}",
            "name": name,
            "category": "role",
            "printed_page": pg,
            "summary": f"Role Ability: {ability}. {desc}",
            "description": f"{name} — Corebook Role (p. {pg}). Role Ability: {ability}. {desc}",
            "stats": {"role_ability": ability},
            "tags": ["role", slug],
        }
        for slug, name, pg, ability, desc in roles
    ]


def build_corebook_locations() -> list[dict[str, Any]]:
    """Return empty list; locations are strictly Bring-Your-Own-Corebook."""
    return []


def build_corebook_factions() -> list[dict[str, Any]]:
    """Return empty list; factions are strictly Bring-Your-Own-Corebook."""
    return []


def build_corebook_rules_highlights() -> list[dict[str, Any]]:
    """Return missing high-value Corebook Rules & Martial Arts entries (pp. 168-230, 377-378)."""
    entries = [
        ("martial-arts-aikido", "Aikido (Martial Art)", 178,
         "Defensive throws, joint locks, and disarming Special Moves (x2 DEX skill). Corebook p. 178."),
        ("martial-arts-judo", "Judo (Martial Art)", 178,
         "Grab escapes, armored throws bypassing half SP, and counter-grapples (x2 DEX skill). Corebook p. 178."),
        ("martial-arts-karate", "Karate (Martial Art)", 179,
         "Armor-breaking strikes and Skull Cracker / Bone Breaking Blow combos (x2 DEX skill). Corebook p. 179."),
        ("martial-arts-taekwondo", "Taekwondo (Martial Art)", 179,
         "Acrobatic Flying Kick and Pressure Point strikes (x2 DEX skill). Corebook p. 179."),
        ("humanity-therapy", "Humanity Loss & Therapy", 230,
         "Standard Therapy (500 eb / 7 days, +2d6 Humanity) or Extreme Therapy (1,000 eb / 7 days, +4d6 Humanity). Corebook p. 230."),
        ("housing-lifestyle", "Housing, Rent & Lifestyle (Month 1 Free)", 377,
         "Every new Edgerunner starts Month 1 in a Cargo Container with Kibble Lifestyle; monthly rent & upkeep trigger at Month 2. Corebook pp. 377-378."),
        ("aimed-shots-autofire", "Aimed Shots, Autofire & Suppressive Fire", 173,
         "Aimed Shots take -8 penalty for head/held-item x2 damage; Autofire uses 10 rounds vs range DV table; Suppressive Fire forces WILL+Concentration vs DV. Corebook pp. 173-174."),
        ("beat-chart-campaign", "Beat Chart Campaign Structure", 395,
         "GMs structure gigs in 5 Beat types: Hook, Developments, Cliffhanger, Climax, and Resolution with clear eddies/IP payoffs. Corebook pp. 395-405."),
    ]
    return [
        {
            "id": f"corebook:rule:{slug}",
            "name": name,
            "category": "rule",
            "printed_page": pg,
            "summary": desc,
            "description": desc,
            "tags": ["rule", "corebook"],
        }
        for slug, name, pg, desc in entries
    ]


def build_campaign_presets() -> dict[str, Any]:
    """Return structured Cyberpunk RED Corebook Campaign Creator presets (pp. 298-317, 393-434)."""
    return {
        "districts": [
            {
                "name": "The Hot Zone",
                "zone_type": "Hot Zone",
                "threat_rating": "Combat",
                "summary": "Irradiated nuclear ground zero in central Night City, filled with twisted skyscrapers and deadly scavvers.",
                "printed_page": 298,
            },
            {
                "name": "Rebuilding Urban Center (Upper Marina & Little Europe)",
                "zone_type": "Rebuilding Urban Center",
                "threat_rating": "Corporate",
                "summary": "Densely packed city sectors escaping the worst destruction where new Corporate towers, marinas, and megabuildings rise.",
                "printed_page": 298,
            },
            {
                "name": "Watson Development",
                "zone_type": "Rebuilding Urban Center",
                "threat_rating": "Moderate",
                "summary": "Sprawling high-density reconstruction sector housing thousands of war refugees in rising megabuildings and Kabuki.",
                "printed_page": 298,
            },
            {
                "name": "Old Combat Zone",
                "zone_type": "Combat Zones",
                "threat_rating": "Combat",
                "summary": "Lawless urban warzone south of the Hot Zone ruled by violent boostergangs where NCPD never patrols.",
                "printed_page": 300,
            },
            {
                "name": "Heywood",
                "zone_type": "Moderate Zone",
                "threat_rating": "Moderate",
                "summary": "Sprawling working-class residential sprawl south of Downtown, packed with cargo container blocks and street markets.",
                "printed_page": 301,
            },
            {
                "name": "New Westbrook",
                "zone_type": "Moderate Zone",
                "threat_rating": "Moderate",
                "summary": "Entertainment and residential sector encompassing Japantown nightlife, capsule hotels, and luxury executive hill estates.",
                "printed_page": 302,
            },
            {
                "name": "Pacifica Playground",
                "zone_type": "Combat Zones",
                "threat_rating": "Combat",
                "summary": "Bankrupt half-finished vacation paradise turned combat playground for combat gangers, private mercs, and scavvers.",
                "printed_page": 299,
            },
            {
                "name": "Executive Zone (Beaverville)",
                "zone_type": "Executive Zone",
                "threat_rating": "Executive",
                "summary": "Walled, gated suburban enclave reserved exclusively for corporate executives, guarded by private military forces.",
                "printed_page": 295,
            },
            {
                "name": "The Open Road / Badlands",
                "zone_type": "The Open Road",
                "threat_rating": "Outskirts",
                "summary": "Vast red-dust desert highways and ruins outside Night City traveled by Nomad convoys and hunted by gogangs.",
                "printed_page": 295,
            },
        ],
        "factions": [
            {"name": "Arasaka", "type": "Megacorp", "summary": "Global security & banking titan covertly operating cutouts in Night City.", "printed_page": 267},
            {"name": "Militech", "type": "Megacorp", "summary": "Weapons manufacturing & PMC superpower garrisoned at NorCal Military Base.", "printed_page": 272},
            {"name": "Danger Gal", "type": "Megacorp", "summary": "Elite private investigation & bodyguard agency founded by Michiko Sanderson.", "printed_page": 270},
            {"name": "Trauma Team International", "type": "Megacorp", "summary": "Armored AV-4 rapid-response tactical paramedical extraction corporation.", "printed_page": 276},
            {"name": "Biotechnica", "type": "Megacorp", "summary": "CHOOH2 fuel patent holder and genetic engineering & cloned species giant.", "printed_page": 268},
            {"name": "Continental Brands", "type": "Megacorp", "summary": "Food conglomerate dominating packaged food, dry Kibble, and Oasis Megamarts.", "printed_page": 269},
            {"name": "NetWatch", "type": "Agency", "summary": "Global NET policing agency patrolling Data Pools and hunting rogue AIs and illegal Netrunners.", "printed_page": 273},
            {"name": "Maelstrom", "type": "Combat Gang", "summary": "Cyberware-obsessed boostergang operating out of the Old Combat Zone.", "printed_page": 308},
            {"name": "Tyger Claws", "type": "Combat Gang", "summary": "Asian street syndicate controlling Kabuki, Japantown, and nightlife protection rackets.", "printed_page": 309},
            {"name": "6th Street", "type": "Combat Gang", "summary": "Patriotic military-veteran neighborhood militia patrolling Heywood and Santo Domingo.", "printed_page": 308},
            {"name": "Voodoo Boys", "type": "Netrunner Gang", "summary": "Insular Netrunner gang operating out of Pacifica Playground and old ruins.", "printed_page": 309},
            {"name": "Red Chrome Legion", "type": "Combat Gang", "summary": "Vicious neo-fascist boostergang operating hate rallies and rail ambushes.", "printed_page": 309},
            {"name": "Inquisitors", "type": "Cult Gang", "summary": "Fanatical anti-cyberware cult tearing cyberware out of chromed victims.", "printed_page": 308},
            {"name": "Bozos", "type": "Prankster Gang", "summary": "Biosculpted killer-clown boostergang executing lethal practical jokes.", "printed_page": 308},
            {"name": "Aldecaldos", "type": "Nomad Nation", "summary": "Premier Nomad Nation running transportation, shipping, and reconstruction convoys.", "printed_page": 68},
        ],
        "caper_styles": [
            {
                "id": "heist",
                "name": "Corporate Data / Cargo Heist",
                "printed_page": 395,
                "summary": "High-stakes infiltration, NET Extraction, and clean getaway against Corp security or rival syndicates.",
                "default_beats": {
                    "hook": "A Fixer brings blueprints and half up-front for a tight 48-hour window before convoy transfer.",
                    "developments": "Security patrols rotate early; an inside contact demands double or tips off a rival crew.",
                    "cliffhanger": "Lockdown traps the crew inside while Trauma Team or MAX-TAC approaches.",
                    "climax": "Running firefight across loading docks or NET vault shutdown under live fire.",
                    "resolution": "Clean fence payout at a Midnight Market, Reputation gain, and lingering Corp heat.",
                },
            },
            {
                "id": "street-turf",
                "name": "Street Turf & Night Market Hustle",
                "printed_page": 398,
                "summary": "Neighborhood survival, gang protection rackets, missing friends, and local Fixer politics in Moderate/Combat Zones.",
                "default_beats": {
                    "hook": "A neighborhood ripperdoc or Fixer begs for help after boostergangers seize their block's water/power node.",
                    "developments": "Local Lawmen refuse to cross into the block; a rival gang offers dirty arms for a cut.",
                    "cliffhanger": "Someone on the block sold out the stash house to a Scav crew.",
                    "climax": "Showdown at an abandoned warehouse or rooftop club over the turf boss.",
                    "resolution": "The neighborhood owes the crew favors and safer Night Market access.",
                },
            },
            {
                "id": "nomad-road",
                "name": "Badlands Convoy & Smuggling Run",
                "printed_page": 316,
                "summary": "High-speed Mad Max highway runs across the Red Badlands, border checkpoints, and Raffen Shiv ambushes.",
                "default_beats": {
                    "hook": "Cargo canisters must cross 80 miles of Red-dust highway before a Biotechnica embargo locks the gates.",
                    "developments": "Sandstorm knocks out comms; Raffen Shiv technicals shadow the convoy.",
                    "cliffhanger": "Bridge barricade holds an armored AV patrol demanding full manifest inspection.",
                    "climax": "Full vehicular pursuit and boarding fight along broken overpass.",
                    "resolution": "Delivery to Nomad Pack camp, vehicle repairs, and family Standing reward.",
                },
            },
            {
                "id": "corp-intrigue",
                "name": "Megacorp Extraction & Black Ops",
                "printed_page": 402,
                "summary": "Espionage, defector extractions, dirty Media leaks, and double-crosses in Westbrook & Corporate Center.",
                "default_beats": {
                    "hook": "A nervous junior Exec wants extraction plus wiping their lab's prototype backups before midnight.",
                    "developments": "Extraction window shifts to a crowded Masquerade club; Black ICE guards the lab subnet.",
                    "cliffhanger": "The defector isn't fleeing—they are bait for a Militech wetwork squad.",
                    "climax": "Negotiate, betray, or fight through elite mercenaries to a waiting Gyrocopter.",
                    "resolution": "Huge eddie payout or explosive Media Screamsheet fallout across Night City.",
                },
            },
        ],
        "screamsheet_hooks": [
            "BLACKOUT AT KABUKI PIER: A neighborhood clinic loses backup generator fuel during a rolling grid brownout and hires runners for 2,000 eb to recover a hijacked tanker.",
            "DEAD DROP ON LINE 4: A nervous courier vanishes inside an abandoned maglev maintenance tunnel carrying an encrypted biometric case worth 3,000 eb.",
            "WATER MAIN SQUEEZE: Rival street crews lock down a Rancho Coronado desalination valve; a local Night Market co-op pools 2,500 eb to break the blockade.",
            "GHOST BROADCAST: An unlicensed rooftop transmitter hijacks district Data Pool feeds with corporate shipping manifests, drawing a rapid strike team response.",
            "CHROME RECALL: A back-alley ripperdoc asks for discreet armed escort after discovering a batch of salvaged implants carries active tracking beacons.",
        ],
        "zone_types": [],
        "threat_ratings": [],
        "screamsheets": [],
    }


def _to_library_row(
    entry: dict[str, Any],
    digest: str,
    *,
    category_override: str | None = None,
    extra_tags: list[str] | None = None,
) -> dict[str, Any]:
    import sourcecatalog

    name = str(entry["name"])
    norm_name = sourcecatalog._normalize(name)
    cat = category_override or str(entry["category"])
    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-") or "item"
    stats = dict(entry.get("stats") or {})
    if "cost_eb" not in stats and isinstance(entry.get("cost_eb"), int):
        stats["cost_eb"] = entry["cost_eb"]
    tags = list(dict.fromkeys([*(entry.get("tags") or []), *(extra_tags or [])]))
    summary = str(entry.get("summary") or "")
    desc = str(entry.get("description") or summary)
    pg = entry.get("printed_page")
    return {
        "id": f"corebook:{cat}:{slug}",
        "name": name,
        "norm_name": norm_name,
        "category": cat,
        "source": "corebook",
        "summary": summary[:220],
        "description": desc,
        "stats": stats,
        "tags": tags,
        "pdf_page": pg,
        "printed_page": pg,
        "section_id": None,
        "source_sha256": digest,
    }


def build_library_corebook_entries(digest: str) -> list[dict[str, Any]]:
    """Build Corebook catalog entries formatted for library.py search indexing."""
    raw_rows: list[dict[str, Any]] = []

    # 1. Curated Weapons, Melee, Attachments, Ammo
    for item in build_corebook_weapons():
        sub = str((item.get("stats") or {}).get("subtype") or "").lower()
        override = "attachment" if sub == "attachment" else ("ammo" if sub == "ammo" else None)
        raw_rows.append(_to_library_row(item, digest, category_override=override, extra_tags=["weapon", sub] if sub else ["weapon"]))

    # 2. Curated Armor
    for item in build_corebook_armor():
        raw_rows.append(_to_library_row(item, digest, extra_tags=["armor"]))

    # 3. Curated Cyberdeck Hardware & Decks
    for item in build_corebook_hardware():
        raw_rows.append(_to_library_row(item, digest, extra_tags=["hardware", "netrunning"]))

    # 4. Curated Vehicles
    for item in build_corebook_vehicles():
        raw_rows.append(_to_library_row(item, digest, category_override="gear", extra_tags=["vehicle", "nomad", "moto"]))

    # 5. Curated Drugs
    for item in build_corebook_drugs():
        sub = str((item.get("stats") or {}).get("subtype") or "").lower().replace(" ", "-")
        raw_rows.append(_to_library_row(item, digest, category_override="gear", extra_tags=["drug", sub or "substance"]))

    # 6. General Gear (Airhypo, Vials of Poison/Biotoxin, Agent, Frames, Cryo)
    for item in build_corebook_gear():
        raw_rows.append(_to_library_row(item, digest, extra_tags=["gear"]))

    # 7. Roles
    for item in build_corebook_roles():
        raw_rows.append(_to_library_row(item, digest))

    # 8. Rules Highlights
    for item in build_corebook_rules_highlights():
        raw_rows.append(_to_library_row(item, digest))

    # 9. All Corebook GM Data Entries (programs/ICE/Demons, defenses, cyberware, ammo, attachments, exotics, services, housing, fashion, rules)
    for item in build_all_gm_data_entries():
        raw_rows.append(_to_library_row(item, digest))

    # Deduplicate cleanly by (category, norm_name) and id
    deduped: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    seen_ids: set[str] = set()

    for row in raw_rows:
        k = _dedup_key(row["category"], row["name"])
        rid = row["id"]
        if k in seen_keys or rid in seen_ids:
            continue
        seen_keys.add(k)
        seen_ids.add(rid)
        deduped.append(row)

    return deduped


def _strip_json_fences(raw: str) -> str:
    text = raw.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.I)
    if m:
        return m.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


_RNG = random.SystemRandom()

_SCRATCH_LOCALES = [
    "Little China ramen-stall alleyways and overcrowded megabuilding stairwells",
    "Santo Domingo Rancho Coronado scrapyard garages and diesel-fumed workshops",
    "Heywood Glen bodega basements and neighborhood block-party rooftops",
    "Watson Northside Industrial rusting shipping containers and flooded docks",
    "Pacifica half-sunken arcade piers and squatters' solar micro-grids",
    "Westbrook Japantown capsule hotels, pachinko basements, and rooftop gardens",
    "South Night City Combat Zone bombed-out transit hubs and barter markets",
    "Badlands Red Chrome border motels, dust-choked wind farms, and water cisterns",
    "University District cramped grad-lab sublets and black-market textbook printers",
    "Upper Marina cargo-barge houseboats and salt-corroded crane catwalks",
]

_SCRATCH_CONFLICTS = [
    "a courier run for grey-market water-purifier filters that turned out to be tagged with corp trackers",
    "covering a sibling's gambling tab at an illegal rooftop fight club",
    "salvaging a wrecked Continental Brands delivery van before scavengers stripped the cold-chain crates",
    "an unpaid ripperdoc installment plan after emergency street surgery",
    "a forged Night City resident permit that got flagged during a routine NCPD sweep",
    "a crooked landlord threatening to cut the block's pirated power tap unless paid in hard eddies",
    "a stolen braindance master tape featuring an embarrassing exec cameo",
    "moonlighting security on a black-market Night Market pop-up that got hit by rival boosters",
    "a Nomad clan barter deal that left half a shipment of Synthcoke-laced meds unaccounted for",
    "a botched data-wipe on a secondhand Cyberdeck that still held someone's blackmail ledger",
]

_SCRATCH_TONES = [
    "gritty blue-collar survivalism — messy debts, worn-out gear, fierce neighborhood loyalty",
    "dry streetwise gallows humor — cynical pragmatism, oddball associates, sharp banter",
    "tense hardboiled noir — quiet betrayals, half-truths, and tight-lipped favors",
    "scrappy up-and-comer hustle — ambitious, resourceful, always three days ahead of rent",
    "ramshackle found-family warmth — fiercely protective of a tiny circle in a brutal city",
]

_CAMPAIGN_TWISTS = [
    "a mid-level Continental Brands logistics clerk trying to defect with contaminated Kibble batch manifests",
    "a flooded sub-basement server vault under Rancho Coronado humming with pre-DataKrash firmware",
    "a stolen Trauma Team cryo-pod whose occupant is a witness everyone thinks is already dead",
    "a neighborhood Night Market co-op being squeezed by two rival gangs over a clean water main",
    "a disgraced Zhirafa drone rigger hiring local street talent to steal back their own prototype rig",
    "a phantom Screamsheet pirate broadcast hijacking local Data Pool feeds from an abandoned maglev tunnel",
    "a Nomad pack stranded outside the city wall with medical supplies the Combat Zone desperately needs",
    "an underground combat-cab syndicate fixing races to launder dirty Petrochem scrip",
]

_ANTI_CLICHE_RULE = (
    "CREATIVE VARIETY & ANTI-CLICHE RULES (CRITICAL):\n"
    "- Invent fresh, grounded, culturally varied Night City 2045 names (everyday names + street handles like 'Marek', 'Tala', 'DeShawn', 'Piotr', 'Sadia', 'Nori', 'Rafa', 'Bex', 'Oskar', 'Yuna' — NEVER use overused sci-fi cliché names like Vex, Nyx, Kael, Jax, Raven, Kira, Viktor, Zero, Razor, Ghost, Nova, or Thorne unless the user explicitly wrote them).\n"
    "- Do NOT default to 'ex-Trauma Team EMT', 'ex-Arasaka operative', 'Afterlife booth meeting', 'Maelstrom ambush', or 'rain-slicked neon alley' unless the user's guidance or character sheet explicitly asks for it.\n"
    "- Write vivid, specific, concrete 2045 details (rent in cargo containers, Kibble/Synthcoke/Smash, specific neighborhoods, real skill/gear hooks) instead of vague purple prose."
)

_BIO_FIELDS = {"concept", "summary", "established_history", "appearance"}
_CONTACT_FIELDS = {"friends", "enemies", "tragic_love_affairs"}
_CAMPAIGN_FIELDS = {
    "name",
    "summary",
    "opening_scene",
    "beat_chart",
    "beat_hook",
    "beat_developments",
    "beat_cliffhanger",
    "beat_climax",
    "beat_resolution",
    "npcs",
    "objectives",
    "gm_secrets",
    "opening_clock",
}

_BEAT_KEY_TO_FIELD = {
    "beat_hook": ("hook", "Inciting job / Screamsheet lead (Corebook p. 396)"),
    "beat_developments": ("developments", "1-2 mid-run complications or reveals (Corebook p. 397)"),
    "beat_cliffhanger": ("cliffhanger", "Major twist raising the stakes (Corebook p. 399)"),
    "beat_climax": ("climax", "Showdown or extraction payoff (Corebook p. 400)"),
    "beat_resolution": ("resolution", "Fallout, eddie payout, Rep & IP aftermath (Corebook p. 401)"),
}


def _sample_scratch_seed(target: str, cultural_origin: str = "") -> dict[str, str]:
    locale = _RNG.choice(_SCRATCH_LOCALES)
    conflict = _RNG.choice(_SCRATCH_CONFLICTS)
    tone = _RNG.choice(_SCRATCH_TONES)
    seed: dict[str, str] = {
        "suggested_locale": locale,
        "suggested_hook_angle": conflict,
        "tone_lens": tone,
    }
    if cultural_origin.strip():
        seed["naming_heritage_cue"] = f"Draw realistic NPC/handle inspiration from {cultural_origin.strip()} or diverse Night City street culture."
    if target == "campaign":
        seed["suggested_premise_spark"] = _RNG.choice(_CAMPAIGN_TWISTS)
    return seed


async def generate_creation_ai_assist(
    rules_path: str | Path | None,
    llm: Any,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Generate or expand character Backstory, Contacts, or Campaign setup grounded in sheet & Corebook lore."""
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object")

    target = str(payload.get("target") or "bio").strip().lower()
    if target not in {"bio", "contacts", "campaign"}:
        raise ValueError("target must be 'bio', 'contacts', or 'campaign'")

    mode = str(payload.get("mode") or "scratch").strip().lower()
    if mode not in {"scratch", "expand"}:
        raise ValueError("mode must be 'scratch' or 'expand'")

    raw_field = payload.get("field")
    field: str | None = str(raw_field).strip().lower() if isinstance(raw_field, str) and raw_field.strip() else None
    if field == "all":
        field = None
    if field is not None:
        allowed = (
            _BIO_FIELDS
            if target == "bio"
            else _CONTACT_FIELDS
            if target == "contacts"
            else _CAMPAIGN_FIELDS
        )
        if field not in allowed:
            raise ValueError(f"Unsupported field {field!r} for target {target!r}")

    char = payload.get("character") if isinstance(payload.get("character"), dict) else {}
    camp = payload.get("campaign") if isinstance(payload.get("campaign"), dict) else {}
    current = payload.get("current") if isinstance(payload.get("current"), dict) else {}
    guidance = str(payload.get("guidance") or "").strip()

    role_name = str(char.get("role") or "Edgerunner").strip()
    char_name = str(char.get("name") or "Unnamed Edgerunner").strip()
    stats = char.get("stats") if isinstance(char.get("stats"), dict) else {}
    skills = char.get("skills") if isinstance(char.get("skills"), dict) else {}
    lifepath = char.get("lifepath") if isinstance(char.get("lifepath"), dict) else {}
    starting_gear = char.get("starting_gear") if isinstance(char.get("starting_gear"), dict) else {}

    top_skills = sorted(
        [(str(k), int(v)) for k, v in skills.items() if isinstance(v, (int, float)) and v > 0],
        key=lambda kv: (-kv[1], kv[0]),
    )[:10]

    scratch_seed = (
        _sample_scratch_seed(target, str(lifepath.get("cultural_origin") or ""))
        if mode == "scratch"
        else None
    )

    # Ground in Corebook index when rules.sqlite exists
    lore_snippets: list[str] = []
    citations: list[dict[str, Any]] = []
    p = Path(rules_path).expanduser() if rules_path else None
    if p and p.is_file():
        from library import search_library
        from redkb import search_pages

        locale_hint = (scratch_seed or {}).get("suggested_locale", "").split()[0] if scratch_seed else ""
        query_terms = (
            [
                str(camp.get("district") or ""),
                *(str(f) for f in (camp.get("factions") or [])[:2]),
                str(camp.get("caper_style") or ""),
                locale_hint or "Night City",
            ]
            if target == "campaign"
            else [role_name, locale_hint or "Night City", str(lifepath.get("cultural_origin") or "")]
        )
        for q_term in query_terms:
            term = q_term.strip()
            if not term:
                continue
            try:
                hits = search_library(p, q=term, limit=2)
                for h in hits:
                    lore_snippets.append(f"[Library: {h['name']}] {h.get('summary') or h.get('description', '')[:220]}")
            except Exception:
                pass
        query_seed = (
            " ".join([str(camp.get("district") or ""), str(camp.get("caper_style") or ""), guidance[:120]]).strip()
            if target == "campaign"
            else " ".join([role_name, guidance[:120] or locale_hint]).strip()
        )
        if query_seed:
            try:
                pages = search_pages(p, query_seed, limit=2)
                for pg in pages:
                    excerpt = str(pg.get("excerpt") or "").strip()
                    if excerpt:
                        lore_snippets.append(f"[Corebook p.{pg.get('printed_page') or pg.get('pdf_page')}] {excerpt[:280]}")
                        citations.append({
                            "printed_page": pg.get("printed_page"),
                            "pdf_page": pg.get("pdf_page"),
                        })
            except Exception:
                pass

    sheet_brief = {
        "name": char_name,
        "pronouns": char.get("pronouns") or "",
        "age": char.get("age") or "",
        "role": f"{role_name} (Rank 4)",
        "method": char.get("method") or "streetrat",
        "stats": stats,
        "top_skills": [f"{k} +{v}" for k, v in top_skills],
        "equipped_weapon": starting_gear.get("equipped_weapon") or "",
        "equipped_armor": starting_gear.get("equipped_armor") or {},
        "cyberware": [
            c.get("name") if isinstance(c, dict) else str(c)
            for c in (starting_gear.get("cyberware") or [])
        ],
        "lifepath": {k: v for k, v in lifepath.items() if k not in {"friends", "enemies", "tragic_love_affairs"} and v},
    }

    system_prompt = (
        "You are a Cyberpunk RED (Year 2045, Time of the Red) Narrative Co-Writer.\n"
        "STRICT RULES:\n"
        "1. Adhere faithfully to the player's actual character sheet (Role Rank 4, STAT scores, trained Skills, installed Cyberware, Weapons/Armor, and Lifepath) or campaign setup.\n"
        "2. Never contradict the sheet (e.g., don't claim a low-TECH character is an elite surgeon, or give a character cyberware/stats they do not have).\n"
        "3. Stay grounded in official Cyberpunk RED Night City 2045 lore (Time of the Red scarcity, Night Markets, Fixers, Continental Brands, local gangs, Watson/Heywood/Westbrook/Santo Domingo/Pacifica/Combat Zone/Badlands).\n"
        f"{_ANTI_CLICHE_RULE}\n"
        "4. Return ONLY valid JSON matching the requested schema. No markdown prose outside the JSON."
    )

    lore_block = "\n".join(lore_snippets[:4]) if lore_snippets else "Setting: Night City 2045 (Time of the Red, post-4th Corporate War)."

    if target == "bio":
        full_schema = {
            "concept": "Short punchy one-line character tagline",
            "summary": "2-3 vivid paragraphs about origins, upbringing, family crisis, and why they became an Edgerunner",
            "established_history": "Concrete pre-Session-1 Night City history: past jobs, Fixers/crews, favors owed, local turf, hooks for the GM",
            "appearance": "Concise visual description matching their outfit, Lifepath style, armor, and visible cyberware",
        }
        current_draft = {
            "concept": current.get("concept") or "",
            "summary": current.get("summary") or "",
            "established_history": current.get("established_history") or "",
            "appearance": current.get("appearance") or "",
        }
        if field is not None:
            requested_schema = {field: full_schema[field]}
            mode_rule = (
                f"Generate ONLY the '{field}' field from scratch, tailored to the character sheet and creative seed, keeping consistency with any other fields already filled in current_draft."
                if mode == "scratch"
                else f"FOCUS EXCLUSIVELY ON THE '{field}' FIELD. Expand, enrich, and sharpen ONLY '{field}'—preserving every specific name, event, debt, and tone the player wrote in '{field}' (or drafting it to harmonize with their other fields in current_draft if '{field}' is currently brief/empty). Do NOT return other fields."
            )
        else:
            requested_schema = full_schema
            mode_rule = (
                "Write an original Concept tagline, Personal Backstory (2-3 crisp paragraphs), Established Night City History & Ties (concrete gigs, debts, hangouts, local turf, NPC hooks), and Signature Look & Mannerisms from scratch. Use the creative_seed angle unless user_guidance steers elsewhere."
                if mode == "scratch"
                else "The player has written draft notes. EXPAND, ENRICH, and POLISH their draft—preserving EVERY specific event, NPC name, debt, faction, and tone they wrote while weaving in sharper 2045 sensory details and sheet-faithful hooks."
            )
        user_payload: dict[str, Any] = {
            "task": "character_bio",
            "mode": mode,
            **({"target_field": field} if field else {}),
            "instruction": mode_rule,
            "user_guidance": guidance or "(none)",
            "sheet": sheet_brief,
            "current_draft": current_draft,
            "corebook_context": lore_block,
            "required_json_schema": requested_schema,
        }
        if scratch_seed:
            user_payload["creative_seed"] = scratch_seed
            prev_text = " | ".join(str(v)[:140] for v in current_draft.values() if isinstance(v, str) and v.strip())
            if prev_text:
                user_payload["avoid_repeating"] = f"Do NOT reuse names, locations, or plot beats from this prior draft: {prev_text[:320]}"

    elif target == "contacts":
        full_schema = {
            "friends": [{"name": "NPC Name", "relationship": "How you know them", "note": "Shared history / what favor or help they offer"}],
            "enemies": [{"who": "Role/Archetype (e.g. Ex-friend, Boosterganger, Corporate exec)", "name": "NPC Name", "wronged": "They wronged me or I wronged them", "cause": "What happened", "backup": "What resources/gang/corp they can throw at you", "revenge": "What you/they plan next"}],
            "tragic_love_affairs": [{"name": "NPC Name", "outcome": "What tore you apart and current status"}],
        }
        current_contacts = {
            "friends": current.get("friends") or [],
            "enemies": current.get("enemies") or [],
            "tragic_love_affairs": current.get("tragic_love_affairs") or [],
        }
        if field is not None:
            requested_schema = {field: full_schema[field]}
            mode_rule = (
                f"Generate ONLY the '{field}' list from scratch anchored in this character's Lifepath, Role, Skills, and existing bio."
                if mode == "scratch"
                else f"FOCUS EXCLUSIVELY ON '{field}'. PRESERVE all existing NPCs/names/relationships the player entered in '{field}', EXPAND thin or placeholder entries (like 'Ally #1' or 'Rival #1') into vivid Night City 2045 NPCs tied to their sheet & other contacts, and add 1 fitting entry only if '{field}' is currently empty. Do NOT return other contact categories."
            )
        else:
            requested_schema = full_schema
            mode_rule = (
                "Generate an original set of pre-campaign NPCs from scratch anchored in this character's Lifepath, Role, Skills, and Night City 2045: 2 Friends, 2 Enemies, and 1 Tragic Love Affair. Give every NPC a distinctive everyday/street name and concrete hook."
                if mode == "scratch"
                else "The player already has draft Friends, Enemies, and/or Tragic Love Affairs. PRESERVE all existing NPCs/names/relationships they entered, EXPAND thin/generic entries into memorable Night City 2045 NPCs tied to their sheet & Lifepath, and add 1 missing ally/rival/ex only if a category is empty."
            )
        user_payload = {
            "task": "character_contacts",
            "mode": mode,
            **({"target_field": field} if field else {}),
            "instruction": mode_rule,
            "user_guidance": guidance or "(none)",
            "sheet": sheet_brief,
            "current_contacts": current_contacts,
            "existing_bio": {
                "summary": current.get("summary") or "",
                "established_history": current.get("established_history") or "",
            },
            "corebook_context": lore_block,
            "required_json_schema": requested_schema,
        }
        if scratch_seed:
            user_payload["creative_seed"] = scratch_seed
            existing_names = [
                str(e.get("name"))
                for lst in current_contacts.values()
                for e in (lst if isinstance(lst, list) else [])
                if isinstance(e, dict) and e.get("name")
            ]
            if existing_names:
                user_payload["avoid_repeating"] = f"Use completely new NPCs and dynamics; do NOT repeat these names: {', '.join(existing_names[:8])}"

    else:
        camp_brief = payload.get("campaign") if isinstance(payload.get("campaign"), dict) else {}
        full_schema: dict[str, Any] = {
            "name": "Evocative campaign title",
            "summary": "2 concise paragraphs: campaign premise, district mood, central conflict, and stakes",
            "opening_scene": "1 vivid playable opening scene right before Turn 1: sensory details, where the crew is, and the immediate hook",
            "npcs": {"NPC Name (Faction/Role)": "Who they are, motive, and immediate offer or threat"},
            "objectives": {"Objective Title": "What the crew needs to accomplish first"},
            "beat_chart": {
                "hook": "Inciting job/Screamsheet lead (p. 396)",
                "developments": "1-2 complications or reveals mid-run (p. 397)",
                "cliffhanger": "Major twist raising the stakes (p. 399)",
                "climax": "Showdown or heist extraction payoff (p. 400)",
                "resolution": "Fallout, eddie payout, Reputation & IP aftermath (p. 401)",
            },
            "gm_secrets": "Hidden truth behind the patron, double-cross, or corporate agenda for the AI GM only",
            "opening_clock": {"name": "Countdown name (e.g. Corp Response / Gang Heat)", "segments": 4, "note": "What happens when the clock fills"},
        }
        current_draft = {
            "name": camp_brief.get("name") or current.get("name") or "",
            "summary": current.get("summary") or "",
            "opening_scene": current.get("opening_scene") or "",
            "gm_secrets": current.get("gm_secrets") or "",
            "beats": current.get("beats") or {},
            "npcs": current.get("npcs") or {},
            "objectives": current.get("objectives") or {},
            "opening_clock": current.get("opening_clock") or {},
        }
        if field is not None:
            if field in _BEAT_KEY_TO_FIELD:
                beat_key, beat_desc = _BEAT_KEY_TO_FIELD[field]
                requested_schema = {"beat_chart": {beat_key: beat_desc}}
                target_label = f"beat_chart.{beat_key}"
            else:
                requested_schema = {field: full_schema[field]}
                target_label = field
            mode_rule = (
                f"FOCUS EXCLUSIVELY ON '{target_label}'. Expand, sharpen, and enrich ONLY '{target_label}'—preserving every specific plot thread, NPC, faction, and tone the user supplied while staying consistent with the rest of current_draft and campaign_seed. Return ONLY the requested schema key."
            )
        else:
            requested_schema = full_schema
            mode_rule = (
                "Design a fresh, ready-to-play Cyberpunk RED Night City 2045 campaign starter strictly adhering to Corebook districts, Threat Ratings, Fixer/Corp/Gang lore, and the Corebook Beat Chart structure (Hook -> Developments -> Cliffhangers -> Climax -> Resolution, pp. 395-405). Draw on creative_seed unless user_guidance overrides it."
                if mode == "scratch"
                else "The GM/player already wrote campaign notes/ideas. EXPAND, SHARPEN, and STRUCTURE their draft—preserving every specific plot thread, district, NPC, and faction they supplied while fleshing out Corebook-faithful hooks, Beat Chart stages, Fixer patrons, and GM secrets."
            )
        user_payload = {
            "task": "campaign_setup",
            "mode": mode,
            **({"target_field": field} if field else {}),
            "instruction": mode_rule,
            "user_guidance": guidance or "(none)",
            "campaign_seed": camp_brief,
            "current_draft": current_draft,
            "corebook_context": lore_block,
            "required_json_schema": requested_schema,
        }
        if scratch_seed:
            user_payload["creative_seed"] = scratch_seed
            prev_camp = " | ".join(
                str(current_draft.get(k) or "")[:120]
                for k in ("name", "summary", "opening_scene")
                if str(current_draft.get(k) or "").strip()
            )
            if prev_camp:
                user_payload["avoid_repeating"] = f"Generate a completely fresh premise, cast, and hook; avoid repeating: {prev_camp[:320]}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]
    raw_reply = await llm.complete(messages, json_mode=True, temperature=0.95 if mode == "scratch" else 0.7)
    cleaned = _strip_json_fences(raw_reply)
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("Model returned non-object JSON for creation AI assist")

    if target == "bio":
        out: dict[str, Any] = {"target": "bio", "mode": mode, "citations": citations}
        if field:
            out["field"] = field
            out[field] = str(parsed.get(field) or "").strip()
        else:
            out["concept"] = str(parsed.get("concept") or "").strip()
            out["summary"] = str(parsed.get("summary") or "").strip()
            out["established_history"] = str(parsed.get("established_history") or "").strip()
            out["appearance"] = str(parsed.get("appearance") or "").strip()
        return out

    if target == "campaign":
        raw_npcs = parsed.get("npcs") if isinstance(parsed.get("npcs"), dict) else {}
        npcs_out = {
            str(k).strip(): str(v).strip()
            for k, v in raw_npcs.items()
            if str(k).strip() and str(v).strip()
        }
        raw_obj = parsed.get("objectives") if isinstance(parsed.get("objectives"), dict) else {}
        obj_out = {
            str(k).strip(): str(v).strip()
            for k, v in raw_obj.items()
            if str(k).strip() and str(v).strip()
        }
        raw_beats = parsed.get("beat_chart") if isinstance(parsed.get("beat_chart"), dict) else {}
        beat_chart_out = {
            "hook": str(raw_beats.get("hook") or "").strip(),
            "developments": str(raw_beats.get("developments") or "").strip(),
            "cliffhanger": str(raw_beats.get("cliffhanger") or "").strip(),
            "climax": str(raw_beats.get("climax") or "").strip(),
            "resolution": str(raw_beats.get("resolution") or "").strip(),
        }
        raw_clock = parsed.get("opening_clock") if isinstance(parsed.get("opening_clock"), dict) else {}
        seg_val = raw_clock.get("segments", 4)
        segments = seg_val if isinstance(seg_val, int) and 2 <= seg_val <= 12 else 4
        opening_clock_out = (
            {
                "name": str(raw_clock.get("name")).strip(),
                "segments": segments,
                "note": str(raw_clock.get("note") or "").strip(),
            }
            if str(raw_clock.get("name") or "").strip()
            else None
        )
        if field:
            out = {"target": "campaign", "mode": mode, "field": field, "citations": citations}
            if field in _BEAT_KEY_TO_FIELD:
                beat_key = _BEAT_KEY_TO_FIELD[field][0]
                val = str(raw_beats.get(beat_key) or parsed.get(beat_key) or parsed.get(field) or "").strip()
                out["beat_chart"] = {beat_key: val}
            elif field == "beat_chart":
                out["beat_chart"] = beat_chart_out
            elif field == "npcs":
                out["npcs"] = npcs_out
            elif field == "objectives":
                out["objectives"] = obj_out
            elif field == "opening_clock":
                out["opening_clock"] = opening_clock_out
            else:
                out[field] = str(parsed.get(field) or "").strip()
            return out
        return {
            "target": "campaign",
            "mode": mode,
            "name": str(parsed.get("name") or "").strip(),
            "summary": str(parsed.get("summary") or "").strip(),
            "opening_scene": str(parsed.get("opening_scene") or "").strip(),
            "npcs": npcs_out,
            "objectives": obj_out,
            "beat_chart": beat_chart_out,
            "gm_secrets": str(parsed.get("gm_secrets") or "").strip(),
            "opening_clock": opening_clock_out,
            "citations": citations,
        }

    friends_out = []
    for entry in parsed.get("friends") or []:
        if isinstance(entry, dict) and str(entry.get("name") or "").strip():
            friends_out.append({
                "name": str(entry.get("name")).strip(),
                "relationship": str(entry.get("relationship") or "Night City contact").strip(),
                "note": str(entry.get("note") or "").strip(),
            })
    enemies_out = []
    for entry in parsed.get("enemies") or []:
        if isinstance(entry, dict) and (str(entry.get("name") or "").strip() or str(entry.get("who") or "").strip()):
            raw_wronged = str(entry.get("wronged") or "They wronged me").strip()
            wronged = "I wronged them" if "i wronged" in raw_wronged.lower() else "They wronged me"
            enemies_out.append({
                "who": str(entry.get("who") or "Rival").strip(),
                "name": str(entry.get("name") or "Unnamed Rival").strip(),
                "wronged": wronged,
                "cause": str(entry.get("cause") or "Old score in Night City").strip(),
                "backup": str(entry.get("backup") or "Just themselves").strip(),
                "revenge": str(entry.get("revenge") or "Waiting for payback").strip(),
            })
    loves_out = []
    for entry in parsed.get("tragic_love_affairs") or []:
        if isinstance(entry, dict) and str(entry.get("name") or "").strip():
            loves_out.append({
                "name": str(entry.get("name")).strip(),
                "outcome": str(entry.get("outcome") or "Lost in Night City").strip(),
            })
    if field:
        out = {"target": "contacts", "mode": mode, "field": field, "citations": citations}
        if field == "friends":
            out["friends"] = friends_out
        elif field == "enemies":
            out["enemies"] = enemies_out
        else:
            out["tragic_love_affairs"] = loves_out
        return out
    return {
        "target": "contacts",
        "mode": mode,
        "friends": friends_out,
        "enemies": enemies_out,
        "tragic_love_affairs": loves_out,
        "citations": citations,
    }
