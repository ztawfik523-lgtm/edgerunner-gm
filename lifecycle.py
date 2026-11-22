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


def advance_campaign_clock(
    state: dict,
    after_clock: int | None = None,
    randbelow=secrets.randbelow,
    *,
    elapsed_minutes: int = 0,
) -> list[dict]:
    """Sync runtime and character clocks forward and resolve any expired street drugs."""
    from substances import process_expirations

    runtime = state.setdefault("runtime", {})
    chars = state.setdefault("characters", {})
    base_runtime = int(runtime.get("clock_minutes") or 0)
    new_clock = max(base_runtime, int(after_clock or 0))
    for ch in chars.values():
        d = ch.get("detail") if isinstance(ch.get("detail"), dict) else {}
        ch_clock = int(d.get("clock_minutes") or 0)
        new_clock = max(new_clock, ch_clock + elapsed_minutes if elapsed_minutes else ch_clock)
    runtime["clock_minutes"] = new_clock
    expired: list[dict] = []
    for cid, ch in chars.items():
        d = ch.setdefault("detail", {})
        prev_c = int(d.get("clock_minutes") or 0)
        target_c = max(new_clock, prev_c + elapsed_minutes if elapsed_minutes else prev_c)
        d["clock_minutes"] = target_c
        for chk in process_expirations(ch, target_c, randbelow=randbelow, prev_minutes=prev_c):
            expired.append({"character_id": cid, "character": ch.get("name") or cid, **chk})
    return expired


def _sync_chars_to_runtime_clock(chars: dict, runtime: dict) -> None:
    runtime_clock = int(runtime.get("clock_minutes") or 0)
    for ch in chars.values():
        d = ch.setdefault("detail", {})
        if int(d.get("clock_minutes") or 0) < runtime_clock:
            d["clock_minutes"] = runtime_clock


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
            from encounters import build_npc_combatant, start_encounter
            if runtime["encounter"] and runtime["encounter"].get("active"):
                raise ValueError("An encounter is already active")
            ids = args.pop("character_ids", None)
            raw_npcs = args.pop("npcs", None)
            if args:
                raise ValueError("start_encounter takes only character_ids and optional npcs")
            if ids is None:
                ids = []
            if not isinstance(ids, list) or len(ids) != len(set(ids)) or any(i not in chars for i in ids):
                raise ValueError("character_ids must name distinct campaign members")
            if raw_npcs is not None and not isinstance(raw_npcs, list):
                raise ValueError("npcs must be a list")
            npc_specs = raw_npcs or []
            if not ids and not npc_specs:
                raise ValueError("character_ids must name distinct campaign members")
            existing_ids = set(str(i) for i in ids) | set(str(k) for k in chars)
            built_npcs = []
            npc_map = {}
            for spec in npc_specs:
                npc_sheet = build_npc_combatant(spec, existing_ids=existing_ids)
                existing_ids.add(npc_sheet["id"])
                built_npcs.append(npc_sheet)
                npc_map[npc_sheet["id"]] = copy.deepcopy(npc_sheet)
            combatants = [chars[i] for i in ids] + built_npcs
            enc = start_encounter(combatants, randbelow)
            enc["npcs"] = npc_map
            runtime["encounter"] = enc
            start_actor = enc["queue"][enc["turn_index"]]
            start_res = self._begin_turn(state, start_actor, randbelow)
            if start_res["dead"]:
                self._next_turn(state, randbelow)
            return runtime["encounter"]
        if action == "encounter_action":
            from encounters import apply_action
            if not runtime["encounter"] or not runtime["encounter"].get("active"):
                raise ValueError("No active encounter")
            encounter = runtime["encounter"]
            sub_action = args["action"]
            if sub_action == "next_turn":
                if encounter["queue"][encounter["turn_index"]] != args["actor_id"]:
                    raise ValueError("Only the current actor can finish its turn")
                return self._next_turn(state, randbelow)
            pc_ids = set(chars.keys())
            npcs_before = copy.deepcopy(encounter.get("npcs") or {})
            combined = {**chars, **npcs_before}
            actor_id = args.get("actor_id")
            if sub_action in {"add_npc", "remove_npc"} and actor_id is None:
                actor_id = encounter["queue"][encounter["turn_index"]]
            prev_active = encounter["queue"][encounter["turn_index"]] if encounter.get("queue") else None
            result = apply_action(encounter, combined, actor_id, sub_action, args.get("arguments", {}), randbelow)
            updated_enc = result["encounter"]
            updated_all = result["characters"]
            for cid in pc_ids:
                if cid in updated_all:
                    chars[cid] = updated_all[cid]
            if isinstance(updated_enc.get("npcs"), dict):
                for nid in list(updated_enc["npcs"].keys()):
                    if nid in updated_all:
                        updated_enc["npcs"][nid] = updated_all[nid]
            else:
                updated_enc["npcs"] = {
                    nid: updated_all[nid]
                    for nid in npcs_before
                    if nid in updated_all and nid not in pc_ids
                }
            runtime["encounter"] = updated_enc
            if sub_action == "remove_npc" and updated_enc.get("active") and updated_enc.get("queue"):
                new_active = updated_enc["queue"][updated_enc["turn_index"]]
                if new_active != prev_active:
                    self._begin_turn(state, new_active, randbelow)
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
            expired = advance_campaign_clock(state, after_clock=after_clock, randbelow=randbelow, elapsed_minutes=elapsed)
            out = {"before_minutes": before_clock, "after_minutes": runtime["clock_minutes"], "elapsed_minutes": elapsed}
            if expired:
                out["expired_drug_checks"] = expired
            return out
        if action == "health_action":
            from health import apply_action
            _sync_chars_to_runtime_clock(chars, runtime)
            result = apply_action(chars, args["actor_id"], args["action"], args.get("arguments", {}), randbelow)
            state["characters"] = result["characters"]
            expired = advance_campaign_clock(state, randbelow=randbelow)
            res = result["result"]
            if expired and isinstance(res, dict) and not res.get("requires_human_ruling"):
                res["expired_drug_checks"] = expired
            return res
        if action == "role_action":
            from roles import apply_action
            char_id = args["character_id"]
            if char_id not in chars: raise ValueError("Character is not in this campaign")
            _sync_chars_to_runtime_clock(chars, runtime)
            result = apply_action(chars[char_id], args["action"], args.get("arguments", {}), randbelow)
            chars[char_id] = result["character"]
            expired = advance_campaign_clock(state, randbelow=randbelow)
            res = result["result"]
            if expired and isinstance(res, dict) and not res.get("requires_human_ruling"):
                res["expired_drug_checks"] = expired
            return res
        if action in {"gear_action", "economy_action"}:
            char_id = args["character_id"]
            if char_id not in chars: raise ValueError("Character is not in this campaign")
            if action == "gear_action":
                from gear import apply_action
                if not self.gameplay.rules_path: raise ValueError("A source index is required")
                result = apply_action(chars[char_id], args["action"], args.get("arguments", {}), self.gameplay.rules_path, randbelow)
                chars[char_id] = result["character"]
            else:
                from economy import apply_action
                _sync_chars_to_runtime_clock(chars, runtime)
                result = apply_action(chars[char_id], args["action"], args.get("arguments", {}), randbelow)
                chars[char_id] = result["character"]
                expired = advance_campaign_clock(state, randbelow=randbelow)
                res = result["result"]
                if expired and isinstance(res, dict):
                    res["expired_drug_checks"] = expired
                return res
            return result["result"]
        if action == "substance_action":
            from substances import apply_action
            _sync_chars_to_runtime_clock(chars, runtime)
            result = apply_action(chars, args["actor_id"], args["action"], args.get("arguments", {}), randbelow)
            state["characters"] = result["characters"]
            expired = advance_campaign_clock(state, randbelow=randbelow)
            res = result["result"]
            if expired and isinstance(res, dict):
                existing = res.get("expired_drug_checks")
                if isinstance(existing, list):
                    existing.extend(expired)
                else:
                    res["expired_drug_checks"] = expired
            return res
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
        from encounters import resolve_start_of_turn
        encounter = state["runtime"].get("encounter") or {}
        npcs = encounter.get("npcs") if isinstance(encounter.get("npcs"), dict) else {}
        actor = state["characters"].get(char_id) or npcs.get(char_id)
        if actor is None:
            raise ValueError(f"Unknown combatant: {char_id}")
        start_res = resolve_start_of_turn(actor, randbelow=randbelow)
        if char_id in state["characters"]:
            from netrunning import apply_action
            for run_id, run in state["runtime"]["runs"].items():
                if run["character_id"] == char_id:
                    arch = state["runtime"]["architectures"][run["architecture_id"]]
                    updated = apply_action(run, arch, "new_turn", {}, randbelow)
                    state["runtime"]["runs"][run_id] = updated["run"]
        return start_res

    def _next_turn(self, state, randbelow):
        from encounters import _is_dead, resolve_end_of_turn
        encounter, chars = state["runtime"]["encounter"], state["characters"]
        npcs = encounter.setdefault("npcs", {})
        current = encounter["queue"][encounter["turn_index"]]
        outgoing = chars.get(current) or npcs.get(current)
        end_of_turn_effects = resolve_end_of_turn(outgoing) if outgoing is not None else []
        resolved = []
        eliminated = []
        for _ in range(len(encounter["queue"]) + 1):
            encounter["turn_index"] = (encounter["turn_index"] + 1) % len(encounter["queue"])
            if encounter["turn_index"] == 0:
                encounter["round"] += 1
            actor_id = encounter["queue"][encounter["turn_index"]]
            actor = chars.get(actor_id) or npcs.get(actor_id)
            if actor is not None:
                if _is_dead(actor):
                    continue
                start_res = self._begin_turn(state, actor_id, randbelow)
                if not start_res["dead"]:
                    return {
                        "actor_id": actor_id,
                        "round": encounter["round"],
                        "death_save": start_res["death_save"],
                        "end_of_turn_effects": end_of_turn_effects,
                        **({"eliminated": eliminated} if eliminated else {}),
                        "net_turns": resolved,
                    }
                eliminated.append({"actor_id": actor_id, "death_save": start_res["death_save"]})
            else:
                ice = encounter.get("net_actors", {}).get(actor_id)
                if ice:
                    run = state["runtime"]["runs"][ice["run_id"]]
                    arch = state["runtime"]["architectures"][run["architecture_id"]]
                    floor = next(f for f in arch["floors"] if f["id"] == ice["floor_id"])
                    if run["connected"] and floor["ice"]["rezzed"] and floor["ice"].get("pursuing"):
                        resolved.append(self._net_step(state, ice["run_id"], "ice_turn", {"ice_floor_id": ice["floor_id"]}, randbelow, internal=True))
        encounter["active"] = False
        return {
            "ended": True,
            "reason": "No living participants remain",
            "end_of_turn_effects": end_of_turn_effects,
            **({"death_save": eliminated[-1]["death_save"], "eliminated": eliminated} if eliminated else {}),
            "net_turns": resolved,
        }

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
                    candidates = [
                        p for p in r.get("deck", {}).get("programs", [])
                        if p.get("active") and int(p.get("rez", 0) or 0) > 0 and not p.get("destroyed")
                    ]
                    if not candidates:
                        continue
                    n = randbelow(len(candidates))
                    if type(n) is not int or not 0 <= n < len(candidates): raise ValueError("Invalid RNG outcome")
                    target = candidates[n]["instance_id"]
                resolved = resolve_effect(name, r, target_program_id=target, randbelow=randbelow)
                if resolved.get("requires_human_ruling"):
                    continue
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
