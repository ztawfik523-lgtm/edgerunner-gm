"""Deterministic state transitions for Cyberpunk RED NETrunning.

The caller owns persistence, character-sheet effects, meatspace coordination and
encounter initiative. Dice are supplied as randbelow(stop), like mechanics.py.
"""
from __future__ import annotations

import copy
import secrets
from collections.abc import Callable
from typing import Any

import mechanics

# Canonical numeric entries from Core Rulebook pp. 203-207. Effects are compact
# codes; caller-authored metadata is never treated as canonical program data.
PROGRAMS: dict[str, dict[str, Any]] = {
    "Eraser": dict(type="Booster", atk=0, def_=0, spd=0, per=0, rez=7, effect="cloak+2"),
    "See Ya": dict(type="Booster", atk=0, def_=0, spd=0, per=0, rez=7, effect="pathfinder+2"),
    "Speedy Gonzalvez": dict(type="Booster", atk=0, def_=0, spd=0, per=0, rez=7, effect="speed+2"),
    "Worm": dict(type="Booster", atk=0, def_=0, spd=0, per=0, rez=7, effect="backdoor+2"),
    "Armor": dict(type="Defender", atk=0, def_=0, spd=0, per=0, rez=7, effect="brain-4-once-run"),
    "Flak": dict(type="Defender", atk=0, def_=0, spd=0, per=0, rez=7, effect="non-ice-atk-zero-once-run"),
    "Shield": dict(type="Defender", atk=0, def_=0, spd=0, per=0, rez=7, effect="block-first-brain-hit-once-run"),
    "Banhammer": dict(type="Anti-Program Attacker", atk=1, def_=0, spd=0, per=0, rez=0, effect="damage-3d6-nonice-2d6-ice"),
    "Sword": dict(type="Anti-Program Attacker", atk=1, def_=0, spd=0, per=0, rez=0, effect="damage-3d6-ice-2d6-nonice"),
    "DeckKRASH": dict(type="Anti-Personnel Attacker", atk=0, def_=0, spd=0, per=0, rez=0, effect="unsafe-exit"),
    "Hellbolt": dict(type="Anti-Personnel Attacker", atk=2, def_=0, spd=0, per=0, rez=0, effect="brain-2d6-fire"),
    "Nervescrub": dict(type="Anti-Personnel Attacker", atk=0, def_=0, spd=0, per=0, rez=0, effect="int-ref-dex-penalty-1d6-hour"),
    "Poison Flatline": dict(type="Anti-Personnel Attacker", atk=0, def_=0, spd=0, per=0, rez=0, effect="destroy-random-program"),
    "Superglue": dict(type="Anti-Personnel Attacker", atk=2, def_=0, spd=0, per=0, rez=0, effect="block-deeper-safe-exit-1d6-rounds-once-run"),
    "Vrizzbolt": dict(type="Anti-Personnel Attacker", atk=1, def_=0, spd=0, per=0, rez=0, effect="brain-1d6-next-actions-1"),
}
BLACK_ICE: dict[str, dict[str, Any]] = {
    "Asp": (4,6,2,2,15,"destroy-random-program"), "Giant": (2,2,8,4,25,"brain-3d6-unsafe-exit"),
    "Hellhound": (6,6,6,2,20,"brain-2d6-fire"), "Kraken": (6,2,8,4,30,"brain-3d6-block-deeper-safe-exit"),
    "Liche": (8,2,6,2,25,"int-ref-dex-penalty-1d6-hour"), "Raven": (6,4,4,2,15,"derezz-defender-brain-1d6"),
    "Scorpion": (2,6,2,2,15,"move-penalty-1d6-hour"), "Skunk": (2,4,4,2,10,"slide-2"),
    "Wisp": (4,4,4,2,15,"brain-1d6-next-actions-1"), "Dragon": (6,4,6,6,30,"program-damage-6d6-destroy"),
    "Killer": (4,8,6,2,20,"program-damage-4d6-destroy"), "Sabertooth": (8,6,6,2,25,"program-damage-6d6-destroy"),
}
for _name, (_per,_spd,_atk,_def,_rez,_effect) in BLACK_ICE.items():
    PROGRAMS[_name] = dict(type="Black ICE", atk=_atk, def_=_def, spd=_spd, per=_per, rez=_rez, effect=_effect)

HARDWARE = {"Backup Drive":2,"DNA Lock":2,"Hardened Circuitry":1,"Insulated Wiring":1,"KRASH Barrier":2,"Range Upgrade":1}

def _copy(x): return copy.deepcopy(x)
def _die(rng, sides=10):
    n=rng(sides)
    if isinstance(n,bool) or not isinstance(n,int) or not 0 <= n < sides: raise ValueError("randbelow returned invalid result")
    return n+1
def _check(interface, dv, bonus, rng): return mechanics.skill_check(interface,0,dv,modifier=bonus,randbelow=rng)
def _budget(i): return 2 if i<=3 else 3 if i<=6 else 4 if i<=9 else 5

def create_architecture(floors, access_points):
    if not isinstance(floors,list) or not floors: raise ValueError("floors must be a non-empty list")
    result=[]; ids=set()
    for i,f in enumerate(floors):
        if not isinstance(f,dict): raise TypeError("floor must be an object")
        fid=f.get("id",i+1)
        if fid in ids: raise ValueError("duplicate floor id")
        ids.add(fid); kind=f.get("type","empty")
        if kind not in {"empty","password","file","control","ice","obstruction"}: raise ValueError("unsupported floor type")
        dv=f.get("dv")
        if dv is not None and (isinstance(dv,bool) or not isinstance(dv,int) or dv<0): raise ValueError("invalid DV")
        row={"id":fid,"type":kind,"adjacent":_copy(f.get("adjacent",[])),"dv":dv,"password":f.get("password"),"file":_copy(f.get("file")),"control":_copy(f.get("control")),"ice":_copy(f.get("ice"))}
        if kind=="ice":
            ice=row["ice"]
            if isinstance(ice,str): ice={"name":ice}
            if not isinstance(ice,dict) or ice.get("name") not in BLACK_ICE: raise ValueError("ice must name canonical Black ICE")
            row["ice"]={"name":ice["name"],"stats":_copy(PROGRAMS[ice["name"]]),"rez":PROGRAMS[ice["name"]]["rez"],"rezzed":True,"encountered":False,"pursuing":False}
        result.append(row)
    for row in result:
        if any(x not in ids for x in row["adjacent"]): raise ValueError("adjacency references unknown floor")
    if not isinstance(access_points,list) or not access_points: raise ValueError("access_points must be non-empty list")
    apids=set()
    for point in access_points:
        if not isinstance(point,dict) or point.get("floor_id") not in ids: raise ValueError("invalid access point")
        if point.get("id") in apids: raise ValueError("duplicate access point id")
        apids.add(point.get("id"))
    return {"floors":result,"access_points":_copy(access_points),"viruses":[],"audit":[]}

def create_run(character_id, interface, deck, architecture, access_point_id, distance, blocked=False, virtuality=True):
    if isinstance(interface,bool) or not isinstance(interface,int) or not 1<=interface<=10: raise ValueError("interface must be 1..10")
    if not isinstance(deck,dict): raise TypeError("deck must be an object")
    if "capacity" not in deck: raise ValueError("deck capacity must be explicitly configured")
    capacity=deck["capacity"]; installed=deck.get("programs",[]); hardware=deck.get("hardware",[])
    if isinstance(capacity,bool) or not isinstance(capacity,int) or capacity<0: raise ValueError("invalid deck capacity")
    if isinstance(distance,bool) or not isinstance(distance,(int,float)) or distance<0: raise ValueError("distance must be numeric and >= 0")
    if not isinstance(blocked,bool) or not isinstance(virtuality,bool): raise TypeError("blocked and virtuality must be bool")
    programs=[]
    for index,p in enumerate(installed):
        name=p if isinstance(p,str) else p.get("name") if isinstance(p,dict) else None
        if name not in PROGRAMS: raise ValueError(f"unknown/noncanonical program: {name}")
        if isinstance(p, dict) and len(p) > 1: raise ValueError(f"noncanonical program metadata for {name}")
        canonical=_copy(PROGRAMS[name]); canonical.update(name=name, instance_id=f"p{index}", max_rez=canonical["rez"], rez=canonical["rez"], active=False, destroyed=False)
        programs.append(canonical)
    used=sum(2 if p["type"]=="Black ICE" else 1 for p in programs)
    hw=[]
    for h in hardware:
        name=h if isinstance(h,str) else h.get("name") if isinstance(h,dict) else None
        if name not in HARDWARE: raise ValueError(f"unknown hardware: {name}")
        hw.append(name); used+=HARDWARE[name]
    if used>capacity: raise ValueError("deck slot capacity exceeded")
    arch=_copy(architecture)
    ap=next((a for a in arch["access_points"] if a.get("id")==access_point_id),None)
    if ap is None: raise ValueError("unknown access point")
    return {"character_id":character_id,"interface":interface,"deck":{"capacity":capacity,"programs":programs,"hardware":hw},"connected":False,"floor_id":ap["floor_id"],"access_point_id":access_point_id,"access_floor_id":ap["floor_id"],"distance":distance,"blocked":blocked,"virtuality":virtuality,"actions_remaining":_budget(interface),"action_budget":_budget(interface),"turn":0,"slide_used":False,"activated_this_round":[],"run_used_programs":[],"encountered_ice":[],"discovered":[],"passed_passwords":[],"trace":[],"cloak_dv":None,"controls":{},"node_activated":[],"virus_work":None,"conditions":{}}

def public_view(run, architecture):
    seen=set(run.get("discovered",[])); a={"floors":[],"access_points":[{"id":p["id"],"floor_id":p["floor_id"]} for p in architecture.get("access_points",[]) if p["floor_id"] in seen]}
    for f in architecture["floors"]:
        if f["id"] not in seen: continue
        row={"id":f["id"],"type":f["type"],"adjacent":[x for x in f.get("adjacent",[]) if x in seen]}
        if f["type"]=="ice": row["ice"]={"name":f["ice"]["name"]}
        a["floors"].append(row)
    return {"run":_copy(run),"architecture":a}

def _unsafe(run, arch, omit=None):
    effects=[]
    for fid in run["encountered_ice"]:
        f=next((x for x in arch["floors"] if x["id"]==fid),None)
        if f and f.get("ice",{}).get("rezzed") and f["ice"]["name"]!=omit:
            effects.append({"type":"black_ice_effect","name":f["ice"]["name"],"effect":f["ice"]["stats"]["effect"]})
    run["connected"]=False; run["controls"]={}; run["floor_id"]=run["access_floor_id"]
    for p in run["deck"]["programs"]: p["active"]=False
    return effects

def apply_action(run, architecture, action, args=None, randbelow=secrets.randbelow):
    r,a=_copy(run),_copy(architecture); args=args or {}; effects=[]; encounters=[]; result={"action":action,"success":True}
    def spend():
        if r["actions_remaining"]<=0: raise ValueError("no NET actions remaining")
        r["actions_remaining"]-=1
    def enter(floor):
        r["floor_id"] = floor["id"]
        if floor["id"] not in r["discovered"]: r["discovered"].append(floor["id"])
        if floor["type"] != "ice" or not floor["ice"]["rezzed"]: return
        ice = floor["ice"]
        fresh = floor["id"] not in r["encountered_ice"] or not ice.get("pursuing")
        if not fresh: return
        ice.update(encountered=True, pursuing=True)
        if floor["id"] not in r["encountered_ice"]: r["encountered_ice"].append(floor["id"])
        pc = r["interface"] + 2*sum(p["active"] and p["rez"]>0 and p["effect"]=="speed+2" for p in r["deck"]["programs"]) + _die(randbelow)
        ic = ice["stats"]["spd"] + _die(randbelow)
        encounters.append({"type":"ice_initiative","floor_id":floor["id"],"name":ice["name"],"initiative":"top"})
        result["speed_check"] = {"runner":pc,"ice":ic}
        if ic>pc: effects.append({"type":"black_ice_effect","name":ice["name"],"floor_id":floor["id"]})
    if action=="new_turn":
        r["turn"]+=1; r["actions_remaining"]=max(2,r["action_budget"]-r["conditions"].get("next_turn_action_penalty",0)); r["conditions"].pop("next_turn_action_penalty",None); r["slide_used"]=False; r["activated_this_round"]=[]; r["node_activated"]=[]
    elif action=="scan": result["requires_meat_action"]=True; result["marker"]="scan_access_points"
    elif action=="jack_in":
        spend()
        ap=next(x for x in a["access_points"] if x["id"]==r["access_point_id"])
        max_range=8 if "Range Upgrade" in r["deck"]["hardware"] else 6
        if r["connected"] or r["distance"]>max_range or r["blocked"]: result["success"]=False
        else:
            r["connected"]=True; enter(next(f for f in a["floors"] if f["id"]==ap["floor_id"]))
            if not r["virtuality"]: effects.append({"type":"character_condition","condition":"unconscious_in_meat"})
    elif action in ("jack_out","move"):
        if action=="jack_out": spend()
        if action=="jack_out":
            max_range=8 if "Range Upgrade" in r["deck"]["hardware"] else 6
            if not r["connected"] or r["distance"]>max_range or r["conditions"].get("safe_exit_blocked",0)>0:
                result["success"]=False
            else:
                r["connected"]=False; r["floor_id"]=r["access_floor_id"]; r["controls"]={}; r["passed_passwords"]=[]
                for p in r["deck"]["programs"]: p["active"]=False
                for floor in a["floors"]:
                    if floor["type"]=="ice": floor["ice"]["pursuing"]=False; floor["ice"]["encountered"]=False
                r["encountered_ice"]=[]
        elif not r["connected"]: raise ValueError("must be jacked in")
        elif args.get("distance",r["distance"])>(8 if "Range Upgrade" in r["deck"]["hardware"] else 6):
            effects=_unsafe(r,a); result["unsafe_effects"]=effects
        else:
            target=args.get("floor_id"); floor=next((f for f in a["floors"] if f["id"]==target),None)
            if floor is None or target not in next(f for f in a["floors"] if f["id"]==r["floor_id"])["adjacent"]: result["success"]=False
            elif floor["type"]=="obstruction" or (next(f for f in a["floors"] if f["id"]==r["floor_id"])["type"]=="password" and r["floor_id"] not in r["passed_passwords"]): result["success"]=False; result["blocked_by"]="password"
            else:
                enter(floor)
        if action=="move": r["distance"]=args.get("distance",r["distance"])
    elif action in ("backdoor","pathfinder","eye_dee","copy_file","slide","cloak","control","activate_node","virus_start","virus_work","zap","activate_program","deactivate_program","ice_turn"):
        if action=="copy_file":
            if not r["connected"]: raise ValueError("must be jacked in")
            here=next(f for f in a["floors"] if f["id"]==r["floor_id"])
            if here["type"]!="file": result["success"]=False
            else:
                r.setdefault("copied_files", {})[str(here["id"])] = _copy(here["file"])
                result["copied"] = True
        elif action=="ice_turn":
            if not r["connected"]: raise ValueError("must be jacked in")
            floor = next((f for f in a["floors"] if f["id"] == args.get("ice_floor_id")), None)
            if not floor or floor["type"] != "ice" or not floor["ice"]["rezzed"] or not floor["ice"].get("pursuing"):
                raise ValueError("ICE is not pursuing this runner")
            ice = floor["ice"]; anti_program = ice["name"] in {"Dragon", "Killer", "Sabertooth"}
            target = None
            if anti_program:
                candidates = [p for p in r["deck"]["programs"] if p["active"] and p["rez"]>0 and not p["destroyed"]]
                if not candidates:
                    result = {"requires_human_ruling":True,"reason":"Anti-program ICE has no active valid target"}
                else: target = candidates[_die(randbelow, len(candidates))-1]
            if not anti_program or target is not None:
                defense = target["def_"] if target else r["interface"]
                check = mechanics.opposed_check({"stat":ice["stats"]["atk"],"skill":0,"dv":0}, {"stat":defense,"skill":0,"dv":0}, randbelow)
                result["check"] = check
                if check["attacker_wins"]:
                    from neteffects import resolve_effect
                    resolved = resolve_effect(ice["name"], r, target_program_id=target["instance_id"] if target else None, randbelow=randbelow)
                    r = resolved["run"]; effects.extend(resolved["character_effects"]); result["effect_dice"] = resolved["dice"]
                    if resolved["forced_exit"]: effects.extend(_unsafe(r,a,ice["name"] if resolved["forced_exit"].get("exclude_self") else None))
        else:
            if not r["connected"]: raise ValueError("must be jacked in")
            spend(); here=next(f for f in a["floors"] if f["id"]==r["floor_id"])
            if action in ("activate_program","deactivate_program"):
                instance_id=args.get("instance_id"); p=next((p for p in r["deck"]["programs"] if p["instance_id"]==instance_id and not p["destroyed"]),None)
                if not p: result["success"]=False
                elif action=="activate_program":
                    if p["active"] or instance_id in r["activated_this_round"]: result["success"]=False
                    elif p["type"] in ("Defender",) and p["name"] in {q["name"] for q in r["deck"]["programs"] if q["active"]}: result["success"]=False
                    elif p["type"] == "Defender" and instance_id in r["run_used_programs"]: result["success"]=False
                    else:
                        p["active"]=True; p["rez"]=p["max_rez"]; r["activated_this_round"].append(instance_id)
                        if p["type"] == "Defender": r["run_used_programs"].append(instance_id)
                        if p["type"].endswith("Attacker"):
                            target = next((f for f in a["floors"] if f["id"] == args.get("target_floor_id")), None)
                            if not target or target["type"]!="ice" or not target["ice"]["rezzed"]:
                                raise ValueError("A rezzed discovered ICE target is required")
                            if target["id"] not in r["discovered"]: raise ValueError("Target has not been discovered")
                            if p["type"] != "Anti-Program Attacker": raise ValueError("Anti-personnel programs require a runner target")
                            check = mechanics.opposed_check({"stat":r["interface"]+p["atk"],"skill":0,"dv":0}, {"stat":target["ice"]["stats"]["def_"],"skill":0,"dv":0}, randbelow)
                            result["check"] = check
                            if check["attacker_wins"]:
                                dice = mechanics.roll_dice(3 if p["name"]=="Sword" else 2,6,randbelow)
                                target["ice"]["rez"] = max(0,target["ice"]["rez"]-sum(dice)); target["ice"]["rezzed"] = target["ice"]["rez"]>0
                                result["damage_dice"] = dice
                        if p["type"].endswith("Attacker"): p["active"]=False
                else: p["active"]=False
            elif action=="slide":
                if r["slide_used"]: result["success"]=False
                else:
                    r["slide_used"]=True; target=next((f for f in a["floors"] if f["id"]==args.get("ice_floor_id")),None)
                    destination=next((f for f in a["floors"] if f["id"]==args.get("floor_id")),None)
                    if not target or target.get("type")!="ice" or target["ice"]["name"]=="Demon" or not target["ice"].get("pursuing") or not destination or destination["id"] not in here["adjacent"] or destination["type"] in ("password","obstruction"):
                        result["success"]=False
                    else:
                        c=mechanics.opposed_check({"stat":r["interface"],"skill":0,"dv":0},{"stat":target["ice"]["stats"]["per"],"skill":0,"dv":0},randbelow); result["check"]=c
                        if c["attacker_wins"]:
                            target["ice"]["pursuing"]=False; enter(destination); result["escaped"]=True
            elif action in ("backdoor","pathfinder","eye_dee","cloak","control"):
                target=next((f for f in a["floors"] if f["id"]==args.get("floor_id",r["floor_id"])),None)
                if target is None or target["id"]!=here["id"]: raise ValueError("action target must be the current floor")
                if action=="pathfinder":
                    c=mechanics.skill_check(r["interface"],0,0,modifier=sum(2 for p in r["deck"]["programs"] if p["active"] and p["effect"]=="pathfinder+2"),randbelow=randbelow)
                    visible=set(r["discovered"]); visited=set(); frontier=[here["id"]]; steps=0
                    while frontier and steps<c["total"]:
                        fid=frontier.pop(0)
                        if fid in visited: continue
                        visited.add(fid)
                        floor=next(f for f in a["floors"] if f["id"]==fid); visible.add(fid); steps+=1
                        if floor.get("dv") is not None and floor["dv"]>c["total"]: continue
                        frontier.extend(x for x in floor["adjacent"] if x not in visible)
                    r["discovered"]=list(visible); result["check"]=c
                elif action=="cloak":
                    c=_check(r["interface"],999,0,randbelow); r["cloak_dv"]=c["total"]+2*sum(p["active"] and p["effect"]=="cloak+2" for p in r["deck"]["programs"]); result["check"]=c
                else:
                    required_type = {"backdoor":"password","eye_dee":"file","control":"control"}[action]
                    if target["type"] != required_type: raise ValueError(f"{action} requires a {required_type} floor")
                    dv=r["controls"].get(str(target["id"]),target.get("dv") or 0); bonus=2*sum(p["active"] and p["rez"]>0 and p["effect"]=="backdoor+2" for p in r["deck"]["programs"]) if action=="backdoor" else 0
                    c=_check(r["interface"],dv,bonus,randbelow); result["check"]=c
                    if action=="backdoor" and target["type"]=="password" and c["success"]: r["passed_passwords"].append(target["id"])
                    if action=="eye_dee" and target["type"]=="file" and c["success"]: result["file"]=_copy(target["file"])
                    if action=="control" and target["type"]=="control" and c["success"]: r["controls"][str(target["id"])]=c["total"]
                    if action=="control" and target.get("password") is not None: result["requires_human_ruling"]="known-password traversal behavior/cost"
            elif action=="activate_node":
                fid=str(args.get("floor_id",r["floor_id"])); node=next((f for f in a["floors"] if str(f["id"])==fid),None)
                if fid not in r["controls"] or not node: result["success"]=False
                elif fid in r["node_activated"]: result["success"]=False
                else: r["node_activated"].append(fid); result["node"]=node.get("control")
            elif action=="virus_start":
                current = next(x for x in a["floors"] if x["id"]==r["floor_id"])
                # Virus can only start on floors not adjacent to any rezzed, pursuing ICE
                adjacent_ice = any(
                    f["type"] == "ice" and f["ice"].get("rezzed") and f["ice"].get("pursuing")
                    for f in a["floors"] if f["id"] in current.get("adjacent", [])
                )
                if adjacent_ice: result["success"]=False
                else:
                    v=args.get("virus",{}); 
                    if not isinstance(v,dict) or set(v)!={"description","dv","actions_required"} or not isinstance(v["description"],str) or isinstance(v["dv"],bool) or not isinstance(v["dv"],int) or v["dv"]<=0 or isinstance(v["actions_required"],bool) or not isinstance(v["actions_required"],int) or v["actions_required"]<=0: raise ValueError("virus schema needs description, positive integer dv and actions_required")
                    r["virus_work"]={**_copy(v),"spent":1}; result["gm_adjudication_required"]=True
                    if v["actions_required"]==1:
                        c=_check(r["interface"],v["dv"],0,randbelow); result["check"]=c
                        if c["success"]: a["viruses"].append({**_copy(v),"check":c["total"]})
                        r["virus_work"]=None
            elif action=="virus_work":
                if not r["virus_work"]: result["success"]=False
                else:
                    r["virus_work"]["spent"]+=1
                    if r["virus_work"]["spent"]>=r["virus_work"]["actions_required"]:
                        c=_check(r["interface"],r["virus_work"]["dv"],0,randbelow); result["check"]=c
                        if c["success"]: a["viruses"].append({**r["virus_work"],"check":c["total"]})
                        r["virus_work"]=None
            elif action=="zap":
                target = next((f for f in a["floors"] if f["id"]==args.get("target_floor_id")),None)
                if not target or target["type"]!="ice" or target["id"] not in r["discovered"] or not target["ice"]["rezzed"]:
                    raise ValueError("Zap requires a discovered rezzed target")
                check=mechanics.opposed_check({"stat":r["interface"],"skill":0,"dv":0},{"stat":target["ice"]["stats"]["def_"],"skill":0,"dv":0},randbelow)
                result["check"]=check
                if check["attacker_wins"]:
                    dice=mechanics.roll_dice(1,6,randbelow); result["damage_dice"]=dice
                    target["ice"]["rez"]=max(0,target["ice"]["rez"]-sum(dice)); target["ice"]["rezzed"]=target["ice"]["rez"]>0
    else: raise ValueError("unknown action")
    return {"run":r,"architecture":a,"result":result,"character_effects":effects,"encounter_effects":encounters}
