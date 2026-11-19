"""Factual mechanical schemas and BYOC-backed catalog query helpers.

All Corebook item catalogs, prose descriptions, lore, and page citations are
strictly Bring-Your-Own-Corebook (sourced at runtime from the user's indexed
rules.sqlite). Only factual mechanical payout math and DV numbers required for
rules validation are retained here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

# Mechanical payout tiers per Role & 1d6 roll (labels come from the user's indexed PDF).
_HUSTLE_PAYOUT_INDICES: dict[str, tuple[int, int, int, int, int, int]] = {
    "Rockerboy": (2, 0, 3, 3, 3, 2),
    "Solo": (1, 2, 2, 1, 0, 1),
    "Netrunner": (1, 2, 0, 2, 2, 2),
    "Tech": (0, 1, 2, 1, 1, 1),
    "Medtech": (1, 2, 1, 0, 2, 1),
    "Media": (3, 2, 2, 2, 0, 3),
    "Lawman": (1, 2, 0, 1, 2, 2),
    "Exec": (3, 0, 2, 3, 3, 2),
    "Fixer": (2, 2, 2, 0, 2, 3),
    "Nomad": (1, 1, 1, 2, 1, 0),
}
_LOW_PAY = (0, 100, 200, 300)
_TYP_PAY = (100, 200, 300, 500)
_HIGH_PAY = (300, 500, 600, 800)

ROLE_HUSTLES_60: dict[str, list[dict[str, Any]]] = {
    role: [
        {
            "roll": idx,
            "low_eb": _LOW_PAY[tier],
            "typical_eb": _TYP_PAY[tier],
            "high_eb": _HIGH_PAY[tier],
            "label": "",
        }
        for idx, tier in enumerate(tiers, 1)
    ]
    for role, tiers in _HUSTLE_PAYOUT_INDICES.items()
}

MARTIAL_ARTS_MOVES: dict[str, list[dict[str, Any]]] = {}

DV_TABLE: dict[str, int] = {
    "Simple": 9,
    "Everyday": 13,
    "Difficult": 15,
    "Professional": 17,
    "Heroic": 21,
    "Incredible": 24,
    "Legendary": 29,
}

REPAIR_TABLE: dict[str, Any] = {
    "vehicles": {
        "Minor Damage": {"dv": 9},
        "Major Damage": {"dv": 13},
        "Destroyed": {"dv": 17},
    },
    "items": {
        "Cheap / Everyday (<=20eb)": {"dv": 9},
        "Costly (<=100eb)": {"dv": 13},
        "Premium (<=500eb)": {"dv": 17},
        "Expensive (<=1000eb)": {"dv": 21},
        "Very Expensive (<=5000eb)": {"dv": 24},
        "Luxury (>=10000eb)": {"dv": 29},
    },
}

CRITICAL_INJURIES_TABLE: dict[str, Any] = {
    "bonus_damage": 5,
    "body": [],
    "head": [],
}

BEAT_CHART_63: dict[str, list[str]] = {
    "Hook": [],
    "Cliffhanger": [],
    "Development": [],
    "Climax": [],
    "Resolution": [],
}

PLAYSTYLE_IP_TABLE: list[dict[str, Any]] = [{"ip": ip} for ip in range(10, 90, 10)]


def _query_categories(rules_path: str | Path | None, categories: tuple[str, ...]) -> list[dict[str, Any]]:
    if rules_path is None:
        return []
    path = Path(rules_path).expanduser()
    if not path.is_file():
        return []
    from library import search_library

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for cat in categories:
        for entry in search_library(path, category=cat, limit=250):
            eid = str(entry.get("id") or "")
            if eid and eid not in seen:
                seen.add(eid)
                out.append(entry)
    return out


def build_corebook_net_catalog(rules_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Return NET programs/hardware from the user's indexed rules.sqlite (empty when unindexed)."""
    return _query_categories(rules_path, ("program", "hardware"))


def build_corebook_cyberware_additions(rules_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Return cyberware entries from the user's indexed rules.sqlite (empty when unindexed)."""
    return _query_categories(rules_path, ("cyberware",))


def build_corebook_ammo_attachments_exotics(rules_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Return ammo and attachment entries from the user's indexed rules.sqlite (empty when unindexed)."""
    return _query_categories(rules_path, ("ammo", "attachment"))


def build_corebook_services_housing_fashion(rules_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Return service, housing, and fashion entries from the user's indexed rules.sqlite (empty when unindexed)."""
    return _query_categories(rules_path, ("service", "housing", "fashion"))


def build_corebook_mooks_and_encounters() -> list[dict[str, Any]]:
    """Return empty list; mooks and encounters are strictly Bring-Your-Own-Corebook."""
    return []


def build_corebook_opponents() -> list[dict[str, Any]]:
    """Return empty list; opponents are strictly Bring-Your-Own-Corebook."""
    return []


def build_corebook_encounters() -> list[dict[str, Any]]:
    """Return empty list; encounters are strictly Bring-Your-Own-Corebook."""
    return []


def build_corebook_rules_reference(rules_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Return rule entries from the user's indexed rules.sqlite (empty when unindexed)."""
    return _query_categories(rules_path, ("rule",))
