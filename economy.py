"""Stored solo downtime and obligations; GM job rewards are explicitly adjudicated."""
from __future__ import annotations

import copy
import secrets

from mechanics import roll_dice
from corebook_gm_data import ROLE_HUSTLES_60

LIFESTYLES = {"Kibble": 100, "Generic Prepak": 300, "Good Prepak": 600, "Fresh Food": 1500}
HOUSING = {"street": 0, "vehicle": 0, "cube": 500, "cargo_container": 1000,
           "studio": 1500, "two_bedroom": 2500, "upscale_conapt": 7500,
           "luxury_penthouse": 15000, "corporate": 0}
_LOW = (0, 100, 200, 300)
_MID = (100, 200, 300, 500)
_HIGH = (300, 500, 600, 800)
_HUSTLES = {
    "Rockerboy": (2, 0, 3, 3, 3, 2), "Solo": (1, 2, 2, 1, 0, 1),
    "Netrunner": (1, 2, 0, 2, 2, 2), "Tech": (0, 1, 2, 1, 1, 1),
    "Medtech": (1, 2, 1, 0, 2, 1), "Media": (3, 2, 2, 2, 0, 3),
    "Lawman": (1, 2, 0, 1, 2, 2), "Exec": (3, 0, 2, 3, 3, 2),
    "Fixer": (2, 2, 2, 0, 2, 3), "Nomad": (1, 1, 1, 2, 1, 0),
}


def apply_action(character, action, args, randbelow=secrets.randbelow):
    c = copy.deepcopy(character)
    d = c.setdefault("detail", {})
    roles = {r["role"]: r["rank"] for r in d.get("roles", [])}
    clock = d.get("clock_minutes", 0)
    if action == "hustle":
        role = args.get("role")
        if role not in roles: raise ValueError("Hustle requires a saved role")
        if args.get("free_days") != 7: raise ValueError("A hustle consumes seven completely free days")
        die = roll_dice(1, 6, randbelow)[0]
        rank = roles[role]
        amount = (_LOW if rank <= 4 else _MID if rank <= 7 else _HIGH)[_HUSTLES[role][die-1]]
        c["money"] += amount
        d["clock_minutes"] = clock + 10080
        hustle_entry = ROLE_HUSTLES_60.get(role, [{}])[die - 1] if role in ROLE_HUSTLES_60 and 1 <= die <= 6 else {}
        result = {
            "earned": amount,
            "dice": [die],
            "elapsed_minutes": 10080,
            "label": hustle_entry.get("label", ""),
            "source": "Corebook pp.381–385",
        }
    elif action == "job_reward":
        amount = args.get("amount")
        if type(amount) is not int or amount < 0 or not isinstance(args.get("contract_reason"), str) or not args["contract_reason"].strip():
            raise ValueError("A nonnegative reward and explicit contract reason are required")
        c["money"] += amount
        result = {"earned": amount, "adjudication": "GM-authorized contract payment, not an inferred price", "source": "Corebook p.381"}
    elif action == "pay_month":
        lifestyle = args.get("lifestyle", d.get("lifestyle", "Kibble"))
        housing = args.get("housing", d.get("housing", "cargo_container"))
        month = args.get("month")
        if type(month) is not int or month < 1: raise ValueError("A positive campaign month is required")
        if lifestyle not in LIFESTYLES or housing not in HOUSING: raise ValueError("Unknown lifestyle or housing")
        if housing == "corporate" and not roles.get("Exec"): raise ValueError("Corporate housing requires Exec benefits")
        paid = d.setdefault("paid_months", {})
        if str(month) in paid: raise ValueError("This month's obligations were already paid")
        cost = LIFESTYLES[lifestyle] + HOUSING[housing]
        if c["money"] < cost: raise ValueError("Insufficient money for monthly obligations")
        c["money"] -= cost
        paid[str(month)] = {"cost": cost, "lifestyle": lifestyle, "housing": housing}
        d.update(lifestyle=lifestyle, housing=housing)
        result = {"paid": cost, "month": month, "source": "Corebook pp.377–378"}
    else:
        raise ValueError("Unknown economy action")
    return {"character": c, "result": result}
