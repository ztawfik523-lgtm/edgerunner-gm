"""Stored solo downtime and obligations; GM job rewards are explicitly adjudicated."""
from __future__ import annotations

import copy
import secrets

from mechanics import roll_dice
import sourcecatalog


def housing_costs(rules_path) -> tuple[dict[str, int], dict[str, int]]:
    """(housing name -> monthly rent, lifestyle name -> monthly cost) from the indexed Corebook."""
    housing: dict[str, int] = {}
    lifestyles: dict[str, int] = {}
    for entry in sourcecatalog.entries(rules_path, "housing"):
        target = lifestyles if entry["stats"]["kind"] == "lifestyle" else housing
        target[entry["name"]] = entry["stats"]["cost_eb"]
    if not housing or not lifestyles:
        raise ValueError("The rules index has no housing and lifestyle entries")
    return housing, lifestyles


def _hustle(rules_path, role: str, rank: int, die: int) -> tuple[int, str, int]:
    """(pay, description, printed page) from the role's Corebook hustle table."""
    for table in sourcecatalog.rule_tables(rules_path, "hustle"):
        if table["title"] == f"{role} Hustle":
            row = next(row for row in table["rows"] if row[0] == str(die))
            # Pay columns follow the description: role ranks 1-4, 5-7, 8-10.
            pay = row[2 if rank <= 4 else 3 if rank <= 7 else 4]
            return sourcecatalog.parse_cost(pay)["cost_eb"], row[1], table["printed_page"]
    raise ValueError(f"The rules index has no hustle table for {role}")


def apply_action(character, action, args, rules_path, randbelow=secrets.randbelow):
    c = copy.deepcopy(character)
    d = c.setdefault("detail", {})
    roles = {r["role"]: r["rank"] for r in d.get("roles", [])}
    clock = d.get("clock_minutes", 0)
    if action == "hustle":
        role = args.get("role")
        if role not in roles: raise ValueError("Hustle requires a saved role")
        if args.get("free_days") != 7: raise ValueError("A hustle consumes seven completely free days")
        die = roll_dice(1, 6, randbelow)[0]
        amount, label, page = _hustle(rules_path, role, roles[role], die)
        c["money"] += amount
        d["clock_minutes"] = clock + 10080
        result = {
            "earned": amount,
            "dice": [die],
            "elapsed_minutes": 10080,
            "label": label,
            "source": f"Corebook p.{page}",
        }
    elif action == "job_reward":
        amount = args.get("amount")
        if type(amount) is not int or amount < 0 or not isinstance(args.get("contract_reason"), str) or not args["contract_reason"].strip():
            raise ValueError("A nonnegative reward and explicit contract reason are required")
        c["money"] += amount
        result = {"earned": amount, "adjudication": "GM-authorized contract payment, not an inferred price", "source": "Corebook p.381"}
    elif action == "pay_month":
        lifestyle = args.get("lifestyle", d.get("lifestyle", "Kibble"))
        housing = args.get("housing", d.get("housing", "Cargo Container"))
        month = args.get("month")
        if type(month) is not int or month < 1: raise ValueError("A positive campaign month is required")
        housing_eb, lifestyle_eb = housing_costs(rules_path)
        if lifestyle not in lifestyle_eb or housing not in housing_eb: raise ValueError("Unknown lifestyle or housing")
        if housing.startswith("Corporate") and not roles.get("Exec"): raise ValueError("Corporate housing requires Exec benefits")
        paid = d.setdefault("paid_months", {})
        if str(month) in paid: raise ValueError("This month's obligations were already paid")
        cost = lifestyle_eb[lifestyle] + housing_eb[housing]
        if c["money"] < cost: raise ValueError("Insufficient money for monthly obligations")
        c["money"] -= cost
        paid[str(month)] = {"cost": cost, "lifestyle": lifestyle, "housing": housing}
        d.update(lifestyle=lifestyle, housing=housing)
        result = {"paid": cost, "month": month, "source": "Corebook pp.377–378"}
    else:
        raise ValueError("Unknown economy action")
    return {"character": c, "result": result}
