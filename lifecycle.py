"""Atomic campaign-scoped solo actions, including all affected character records.

Pure rule modules propose transitions; this module alone commits them. The action
ledger stores complete before/after snapshots, not model-written success claims.
"""
from __future__ import annotations

import copy
import json
import secrets
import uuid
from contextlib import closing

from campaign import _json, _integer


class SoloService:
    def __init__(self, gameplay):
        self.gameplay = gameplay
        self.store = gameplay.store
        with closing(self.store._connect()) as conn, conn:
            conn.execute("CREATE TABLE IF NOT EXISTS solo_state(campaign_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, state_json TEXT NOT NULL)")
            conn.execute("""CREATE TABLE IF NOT EXISTS gameplay_events(
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id TEXT NOT NULL,
                operation_id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL,
                result TEXT NOT NULL, before_json TEXT NOT NULL, after_json TEXT NOT NULL,
                reason TEXT NOT NULL)""")

    def _snapshot(self, conn, campaign_id):
        self.gameplay.memory._campaign(conn, campaign_id)
        row = conn.execute("SELECT revision,state_json FROM solo_state WHERE campaign_id=?", (campaign_id,)).fetchone()
        runtime = json.loads(row[1]) if row else {"encounter": None, "architectures": {}, "runs": {}, "clock_minutes": 0}
        chars = {r["id"]: self.store._record(r) for r in conn.execute(
            "SELECT c.* FROM characters c JOIN campaign_members m ON m.character_id=c.id WHERE m.campaign_id=? ORDER BY c.id", (campaign_id,))}
        return {"revision": row[0] if row else 0, "runtime": runtime, "characters": chars}

    def context(self, campaign_id):
        with closing(self.store._connect()) as conn:
            conn.execute("BEGIN")
            snapshot = self._snapshot(conn, campaign_id)
        # Hidden architecture data is not part of ordinary model context.
        public = copy.deepcopy(snapshot)
        from netrunning import public_view
        public["runtime"]["architectures"] = {}
        for run_id, run in public["runtime"]["runs"].items():
            original = snapshot["runtime"]["runs"][run_id]
            arch_id = original["architecture_id"]
            view = public_view(original, snapshot["runtime"]["architectures"][arch_id])
            public["runtime"]["runs"][run_id] = view
        return public

    def history(self, campaign_id):
        with closing(self.store._connect()) as conn:
            return [dict(sequence=r[0], operation_id=r[1], action=json.loads(r[2])["action"], reason=r[3]) for r in conn.execute(
                "SELECT sequence,operation_id,payload,reason FROM gameplay_events WHERE campaign_id=? ORDER BY sequence", (campaign_id,))]

    def set_initial_clock_minutes(self, campaign_id: str, clock_minutes: int):
        if type(clock_minutes) is not int or clock_minutes < 0:
            raise ValueError("clock_minutes must be a nonnegative integer")
        with closing(self.store._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            snap = self._snapshot(conn, campaign_id)
            runtime = dict(snap["runtime"])
            runtime["clock_minutes"] = clock_minutes
            next_rev = int(snap["revision"]) + 1 if snap["revision"] else 1
            conn.execute(
                "INSERT INTO solo_state VALUES(?,?,?) ON CONFLICT(campaign_id) DO UPDATE SET revision=excluded.revision,state_json=excluded.state_json",
                (campaign_id, next_rev, _json(runtime)),
            )
            return {"revision": next_rev, "runtime": runtime}

    def execute(self, action, arguments, campaign_id, randbelow=secrets.randbelow):
        if not campaign_id:
            raise ValueError("A selected campaign is required for solo gameplay")
        args = copy.deepcopy(arguments)
        if action == "solo_context":
            if args: raise ValueError("solo_context takes no arguments")
            return self.context(campaign_id)
        if action == "solo_history":
            if args: raise ValueError("solo_history takes no arguments")
            return self.history(campaign_id)
        operation_id = args.pop("operation_id", None)
        reason = args.pop("reason", None)
        expected = args.pop("expected_revision", None)
        if not isinstance(operation_id, str) or not operation_id.strip() or len(operation_id) > 160:
            raise ValueError("operation_id must be a nonempty string of at most 160 characters")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason is required")
        _integer(expected, "expected_revision", 0, 2**63-1)
        payload = _json({"action": action, "campaign_id": campaign_id, "arguments": arguments})
        with closing(self.store._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            prior = conn.execute("SELECT payload,result FROM gameplay_events WHERE operation_id=?", (operation_id,)).fetchone()
            if prior:
                if prior[0] != payload: raise ValueError("operation_id already used for another action")
                return json.loads(prior[1])
            self.store._reject_roll_id(conn, operation_id)
            for table in ("audit", "rolls", "campaign_events"):
                if conn.execute(f"SELECT 1 FROM {table} WHERE operation_id=?", (operation_id,)).fetchone():
                    raise ValueError("operation_id already used by another operation")
            before = self._snapshot(conn, campaign_id)
            if before["revision"] != expected:
                raise ValueError(f"solo revision conflict: expected {expected}, current {before['revision']}")
            after = copy.deepcopy(before)
            if action == "undo_action":
                if args: raise ValueError("undo_action takes no extra arguments")
                latest = conn.execute("SELECT before_json,after_json FROM gameplay_events WHERE campaign_id=? ORDER BY sequence DESC LIMIT 1", (campaign_id,)).fetchone()
                if not latest: raise ValueError("No solo action to undo")
                if _json(before) != latest[1]:
                    raise ValueError("State changed outside the latest action; undo would overwrite newer changes")
                after = json.loads(latest[0])
                if set(after["characters"]) != set(before["characters"]):
                    raise ValueError("Character creation cannot be undone; retain the audited saved character")
                result = {"undone": True}
            else:
                result = self._apply(action, args, after, randbelow)
            if result.get("requires_human_ruling"):
                # No action budget/resource change is committed for an unsupported
                # operation. Genuine failed rolls, unlike unsupported rules, commit.
                return {"committed": False, "revision": before["revision"], "result": result}
            after["revision"] = before["revision"] + 1
            for char_id, char in after["characters"].items():
                old = before["characters"].get(char_id)
                if old == char: continue
                char["revision"] = old["revision"] + 1 if old else 1
                self._write_character(conn, char)
                if old is None:
                    conn.execute("INSERT INTO campaign_members VALUES(?,?)", (campaign_id, char_id))
                    conn.execute("UPDATE campaigns SET revision=revision+1 WHERE id=?", (campaign_id,))
                derived_op = f"{operation_id}:character:{char_id}"
                self.store._reject_roll_id(conn, derived_op)
                if conn.execute("SELECT 1 FROM audit WHERE operation_id=?", (derived_op,)).fetchone():
                    raise ValueError("Derived operation ID collision")
                conn.execute("INSERT INTO audit(character_id,revision,before_json,after_json,reason,operation_id,payload) VALUES(?,?,?,?,?,?,?)",
                    (char_id, char["revision"], _json(old) if old else None, _json(char), reason, derived_op, payload))
            conn.execute("INSERT INTO solo_state VALUES(?,?,?) ON CONFLICT(campaign_id) DO UPDATE SET revision=excluded.revision,state_json=excluded.state_json",
                         (campaign_id, after["revision"], _json(after["runtime"])))
            response = {"committed": True, "operation_id": operation_id, "revision": after["revision"], "result": result,
                        "characters": list(after["characters"].values())}
            conn.execute("INSERT INTO gameplay_events(campaign_id,operation_id,payload,result,before_json,after_json,reason) VALUES(?,?,?,?,?,?,?)",
                         (campaign_id, operation_id, payload, _json(response), _json(before), _json(after), reason))
            return response

    @staticmethod
    def _write_character(conn, c):
        keys = ("id", "name", "stats", "skills", "hp", "max_hp", "humanity", "luck_remaining", "money", "inventory", "revision", "detail")
        values = [_json(c[k]) if k in {"stats", "skills", "inventory", "detail"} else c[k] for k in keys]
        conn.execute(f"INSERT INTO characters({','.join(keys)}) VALUES({','.join('?' for _ in keys)}) ON CONFLICT(id) DO UPDATE SET " +
                     ",".join(f"{k}=excluded.{k}" for k in keys if k != "id"), values)

    def _apply(self, action, args, state, randbelow):
        runtime, chars = state["runtime"], state["characters"]
        if action == "create_player_character":
            from creation import build_character
            if not self.gameplay.rules_path: raise ValueError("A structured rules index is required for character creation")
            c = build_character(args, self.gameplay.rules_path, randbelow=randbelow)
            c["id"] = str(uuid.uuid4())
            c.setdefault("detail", {})
            for key in list(c):
                if key not in {"id", "name", "stats", "skills", "hp", "max_hp", "humanity", "luck_remaining", "money", "inventory", "revision", "detail"}:
                    c["detail"][key] = c.pop(key)
            c.setdefault("revision", 1)
            chars[c["id"]] = c
            return {"character_id": c["id"], "creation": c["detail"]}
        if action == "start_encounter":
            from encounters import start_encounter
            if runtime["encounter"] and runtime["encounter"].get("active"):
                raise ValueError("An encounter is already active")
            ids = args.pop("character_ids", None)
            if args or not isinstance(ids, list) or not ids or len(ids) != len(set(ids)) or any(i not in chars for i in ids):
                raise ValueError("character_ids must name distinct campaign members")
            runtime["encounter"] = start_encounter([chars[i] for i in ids], randbelow)
            self._begin_turn(state, runtime["encounter"]["queue"][0], randbelow)
            return runtime["encounter"]
        if action == "encounter_action":
            from encounters import apply_action
            if not runtime["encounter"] or not runtime["encounter"].get("active"):
                raise ValueError("No active encounter")
            if args["action"] == "next_turn":
                encounter = runtime["encounter"]
                if encounter["queue"][encounter["turn_index"]] != args["actor_id"]:
                    raise ValueError("Only the current actor can finish its turn")
                return self._next_turn(state, randbelow)
            result = apply_action(runtime["encounter"], chars, args["actor_id"], args["action"], args.get("arguments", {}), randbelow)
            runtime["encounter"], state["characters"] = result["encounter"], result["characters"]
            return result["result"]
        if action == "end_encounter":
            if args: raise ValueError("end_encounter takes no extra arguments")
            if not runtime["encounter"]: raise ValueError("No encounter")
            runtime["encounter"]["active"] = False
            return {"ended": True}
        if action == "advance_time":
            elapsed = args.get("elapsed_minutes")
            if type(elapsed) is not int or elapsed < 0 or elapsed > 43200:
                raise ValueError("elapsed_minutes must be an integer between 0 and 43200")
            before_clock = int(runtime.get("clock_minutes") or 0)
            after_clock = before_clock + elapsed
            runtime["clock_minutes"] = after_clock
            for ch in chars.values():
                d = ch.setdefault("detail", {})
                d["clock_minutes"] = max(after_clock, int(d.get("clock_minutes") or 0) + elapsed)
            return {"before_minutes": before_clock, "after_minutes": after_clock, "elapsed_minutes": elapsed}
        if action == "health_action":
            from health import apply_action
            result = apply_action(chars, args["actor_id"], args["action"], args.get("arguments", {}), randbelow)
            state["characters"] = result["characters"]
            max_clock = max([int(c.get("detail", {}).get("clock_minutes") or 0) for c in state["characters"].values()], default=0)
            runtime["clock_minutes"] = max(int(runtime.get("clock_minutes") or 0), max_clock)
            return result["result"]
        if action == "role_action":
            from roles import apply_action
            char_id = args["character_id"]
            if char_id not in chars: raise ValueError("Character is not in this campaign")
            result = apply_action(chars[char_id], args["action"], args.get("arguments", {}), randbelow)
            chars[char_id] = result["character"]
            return result["result"]
        if action in {"gear_action", "economy_action"}:
            char_id = args["character_id"]
            if char_id not in chars: raise ValueError("Character is not in this campaign")
            if action == "gear_action":
                from gear import apply_action
                if not self.gameplay.rules_path: raise ValueError("A source index is required")
                result = apply_action(chars[char_id], args["action"], args.get("arguments", {}), self.gameplay.rules_path, randbelow)
            else:
                from economy import apply_action
                result = apply_action(chars[char_id], args["action"], args.get("arguments", {}), randbelow)
                max_clock = max([int(c.get("detail", {}).get("clock_minutes") or 0) for c in chars.values()], default=0)
                runtime["clock_minutes"] = max(int(runtime.get("clock_minutes") or 0), max_clock)
            chars[char_id] = result["character"]
            return result["result"]
        if action == "substance_action":
            from substances import apply_action
            result = apply_action(chars, args["actor_id"], args["action"], args.get("arguments", {}), randbelow)
            state["characters"] = result["characters"]
            return result["result"]
        if action == "create_architecture":
            from netrunning import create_architecture
            ident = str(uuid.uuid4())
            runtime["architectures"][ident] = create_architecture(args["floors"], args["access_points"])
            return {"architecture_id": ident}
        if action == "start_netrun":
            from netrunning import create_run
            char_id = args["character_id"]
            if char_id not in chars: raise ValueError("Character is not in this campaign")
            roles = chars[char_id]["detail"].get("roles", [])
            interface = next((r["rank"] for r in roles if r["role"] == "Netrunner"), 0)
            arch_id = args["architecture_id"]
            deck = chars[char_id]["detail"].get("deck")
            if not deck: raise ValueError("No saved cyberdeck is installed")
            if any(r["character_id"] == char_id and r["connected"] for r in runtime["runs"].values()):
                raise ValueError("Character already has a connected NET run")
            if not runtime["encounter"] or not runtime["encounter"].get("active"):
                from encounters import start_encounter
                runtime["encounter"] = start_encounter([chars[char_id]], randbelow)
                self._begin_turn(state, char_id, randbelow)
            run = create_run(char_id, interface, deck, runtime["architectures"][arch_id], args["access_point_id"], args["distance"], args.get("blocked", False), args.get("virtuality", True))
            run["architecture_id"] = arch_id
            ident = str(uuid.uuid4()); runtime["runs"][ident] = run
            return {"run_id": ident}
        if action == "net_action":
            if args["action"] in {"new_turn", "ice_turn"}: raise ValueError("NET/ICE turns advance through the shared encounter queue")
            return self._net_step(state, args["run_id"], args["action"], args.get("arguments", {}), randbelow)
        raise ValueError(f"Unknown solo action: {action}")

    @staticmethod
    def _begin_turn(state, char_id, randbelow):
        from encounters import _begin_turn
        from combat import death_save
        char = state["characters"][char_id]
        _begin_turn(char)
        detail = char["detail"]
        if char["hp"] <= 0 and not detail.get("dead"):
            death_body = int((detail.get("creation") or {}).get("effective_body") or detail.get("death_save") or char["stats"]["BODY"])
            check = death_save(death_body, detail.get("death_save_penalty", 0), randbelow)
            detail["death_save_penalty"] = check["next_penalty"]
            detail["dead"] = check["dead"]
            detail["last_death_save"] = check
        from netrunning import apply_action
        for run_id, run in state["runtime"]["runs"].items():
            if run["character_id"] == char_id:
                arch = state["runtime"]["architectures"][run["architecture_id"]]
                updated = apply_action(run, arch, "new_turn", {}, randbelow)
                state["runtime"]["runs"][run_id] = updated["run"]

    def _next_turn(self, state, randbelow):
        encounter, chars = state["runtime"]["encounter"], state["characters"]
        current = encounter["queue"][encounter["turn_index"]]
        if current in chars and chars[current]["detail"].get("conditions", {}).get("burning"):
            chars[current]["hp"] -= 2
        resolved = []
        for _ in range(len(encounter["queue"]) + 1):
            encounter["turn_index"] = (encounter["turn_index"] + 1) % len(encounter["queue"])
            if encounter["turn_index"] == 0: encounter["round"] += 1
            actor = encounter["queue"][encounter["turn_index"]]
            if actor in chars:
                self._begin_turn(state, actor, randbelow)
                if not chars[actor]["detail"].get("dead"):
                    return {"actor_id": actor, "round": encounter["round"], "net_turns": resolved}
            else:
                ice = encounter.get("net_actors", {}).get(actor)
                if ice:
                    run = state["runtime"]["runs"][ice["run_id"]]
                    arch = state["runtime"]["architectures"][run["architecture_id"]]
                    floor = next(f for f in arch["floors"] if f["id"] == ice["floor_id"])
                    if run["connected"] and floor["ice"]["rezzed"] and floor["ice"].get("pursuing"):
                        resolved.append(self._net_step(state, ice["run_id"], "ice_turn", {"ice_floor_id": ice["floor_id"]}, randbelow, internal=True))
        encounter["active"] = False
        return {"ended": True, "reason": "No living participants remain", "net_turns": resolved}

    def _net_step(self, state, run_id, action, arguments, randbelow, internal=False):
        from netrunning import apply_action, public_view, _unsafe
        from neteffects import resolve_effect
        runtime, chars = state["runtime"], state["characters"]
        run = runtime["runs"][run_id]; arch_id = run["architecture_id"]
        actor = chars[run["character_id"]]; detail = actor["detail"]
        encounter = runtime["encounter"]
        if not encounter or not encounter.get("active"): raise ValueError("An active encounter supplies NET turn budgets")
        turn = detail.setdefault("encounter_turn", {})
        if not internal:
            if encounter["queue"][encounter["turn_index"]] != actor["id"]: raise ValueError("Runner is not the current actor")
            if detail.get("dead") or detail.get("conditions", {}).get("unconscious"): raise ValueError("Runner cannot act")
            if turn.get("action_used") and turn.get("mode") != "net": raise ValueError("Meat and NET Actions are mutually exclusive")
        result = apply_action(run, runtime["architectures"][arch_id], action, arguments, randbelow)
        if result["result"].get("requires_human_ruling"):
            return result["result"]
        r, arch = result["run"], result["architecture"]
        if not internal and r["actions_remaining"] < run["actions_remaining"]:
            turn.update(action_used=True, mode="net")
        pending = list(result["character_effects"])
        effect_dice = []
        while pending:
            effect = pending.pop(0)
            if effect["type"] == "black_ice_effect":
                name = effect["name"]
                target = None
                if name in {"Dragon", "Killer", "Sabertooth"}:
                    candidates = [p for p in r["deck"]["programs"] if p["active"] and p["rez"]>0 and not p["destroyed"]]
                    if not candidates: return {"requires_human_ruling": True, "reason": "Anti-program ICE has no valid target"}
                    n = randbelow(len(candidates))
                    if type(n) is not int or not 0 <= n < len(candidates): raise ValueError("Invalid RNG outcome")
                    target = candidates[n]["instance_id"]
                resolved = resolve_effect(name, r, target_program_id=target, randbelow=randbelow)
                r = resolved["run"]; effect_dice.extend(resolved["dice"]); pending.extend(resolved["character_effects"])
                if resolved["forced_exit"] and r["connected"]:
                    pending.extend(_unsafe(r, arch, name if resolved["forced_exit"].get("exclude_self") else None))
            elif effect["type"] == "damage":
                if effect.get("timing") == "end_of_turn": continue
                actor["hp"] -= effect["amount"]
                detail["stabilized"] = False
            elif effect["type"] in {"condition", "character_condition"}:
                name = effect.get("name", effect.get("condition"))
                value = effect.get("value", True)
                if name in {"next_turn_action_penalty", "slide_penalty", "net_movement_block"}:
                    r["conditions"][name] = value
                else:
                    detail.setdefault("conditions", {})[name] = value
                    detail.setdefault("condition_details", {})[name] = effect
        for added in result["encounter_effects"]:
            key = f"net:{run_id}:{added['floor_id']}"
            if key not in encounter["queue"]:
                encounter["queue"].insert(0, key)
                encounter["turn_index"] += 1  # preserve the actor whose turn is in progress
                encounter.setdefault("net_actors", {})[key] = {"run_id": run_id, "floor_id": added["floor_id"]}
        if not r["connected"]:
            detail.setdefault("conditions", {}).pop("unconscious_in_meat", None)
        runtime["runs"][run_id], runtime["architectures"][arch_id] = r, arch
        return {"outcome": result["result"], "effect_dice": effect_dice, "view": public_view(r, arch)}


SOLO_ACTIONS = {"solo_context", "solo_history", "undo_action", "create_player_character", "advance_time", "start_encounter", "encounter_action", "end_encounter", "health_action", "role_action", "gear_action", "economy_action", "substance_action", "create_architecture", "start_netrun", "net_action"}
