from unittest.mock import patch

import pytest

from campaign import STAT_NAMES
from gameplay import GameplayService
from mechanics import skill_check


def setup_game(tmp_path):
    path = tmp_path / "campaign.sqlite"
    game = GameplayService(path)
    character = game.execute("create_character", {"name": "V", "stats": dict.fromkeys(STAT_NAMES, 6),
                             "skills": {"Evasion": 4}, "operation_id": "create"})["result"]
    return game, character, path


def test_roll_idempotency_survives_restart(tmp_path):
    game, _, path = setup_game(tmp_path)
    args = dict(count=2, sides=6, operation_id="damage", reason="weapon damage")
    with patch("gameplay.roll_dice", return_value=[3, 5]) as dice:
        first = game.execute("roll_dice", args)
        second = GameplayService(path).execute("roll_dice", args)
    assert first == second
    assert dice.call_count == 1
    with pytest.raises(ValueError):
        game.execute("roll_dice", dict(args, count=3))


def test_check_atomic_luck_wounds_history_and_undo(tmp_path):
    game, char, path = setup_game(tmp_path)
    char = game.store.update_character(char["id"], 1, {"hp": 10}, "hurt", "hurt")
    args = dict(character_id=char["id"], expected_revision=2, stat="DEX", skill="Evasion",
                dv=16, operation_id="check", reason="dodge", luck=2)
    with patch("gameplay.skill_check", side_effect=lambda *a, **kw: skill_check(*a, **kw, randbelow=lambda _: 5)) as dice:
        first = game.execute("skill_check", args)["result"]
        replay = GameplayService(path).execute("skill_check", args)["result"]
    assert dice.call_count == 1
    assert first == replay
    assert first["total"] == 16  # 6+4+6+2 LUCK-2 wound penalty; tie fails
    assert not first["success"]
    assert first["character"]["luck_remaining"] == 4
    restored = game.execute("undo", dict(character_id=char["id"], expected_revision=3,
                                        reason="reverse mistaken check", operation_id="undo"))["result"]
    assert restored["luck_remaining"] == 6
    assert restored["revision"] == 4
    assert len(game.store.audit_events(char["id"])) == 4


def test_failed_check_does_not_roll_or_spend(tmp_path):
    game, char, _ = setup_game(tmp_path)
    args = dict(character_id=char["id"], expected_revision=1, stat="DEX", skill=None,
                dv=13, operation_id="check", reason="test", luck=7)
    with patch("gameplay.skill_check") as dice, pytest.raises(ValueError):
        game.execute("skill_check", args)
    dice.assert_not_called()
    assert game.store.get_character(char["id"]) == char


def test_roll_operation_cannot_be_reused_for_state(tmp_path):
    game, char, _ = setup_game(tmp_path)
    game.roll(1, 6, "op", "test")
    with pytest.raises(ValueError):
        game.store.update_character(char["id"], 1, {"money": 3}, "test", "op")


def test_rules_path_is_protected(tmp_path):
    path = tmp_path / "rules.sqlite"
    with pytest.raises(ValueError):
        GameplayService(path, path)
    assert not path.exists()


def test_concurrent_initialization(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from campaign import CampaignStore
    path = tmp_path / "concurrent.sqlite"
    with ThreadPoolExecutor(max_workers=8) as pool:
        stores = list(pool.map(lambda _: CampaignStore(path), range(16)))
    assert all(store.list_characters() == [] for store in stores)


def test_check_wires_effective_emp_body_armor_injuries_maker_and_breakdown(tmp_path):
    game = GameplayService(tmp_path / "campaign.sqlite")
    # humanity=45 -> effective EMP 4 (base EMP 6), Linear Frame Sigma -> BODY 12,
    # Heavy Armorjack -> -2 REF/DEX/MOVE, Concussion -> -2 all actions, Tech Maker rank 3 + Field Expertise 2
    char = game.execute(
        "create_character",
        {
            "name": "TechV",
            "stats": dict.fromkeys(STAT_NAMES, 6),
            "skills": {"Evasion": 4},
            "humanity": 45,
            "detail": {
                "equipped_armor": {"name": "Heavy Armorjack", "sp": 13, "penalty": 2},
                "cyberware": [{"name": "Implanted Linear Frame Sigma", "installed": True}],
                "injuries": [{"id": "head:5", "name": "Concussion"}],
                "roles": [{"role": "Tech", "rank": 3, "choices": {"maker_ranks": {"Field Expertise": 2}}}],
            },
            "operation_id": "create-tech",
        },
    )["result"]

    # 1. EMP check uses effective EMP = 4 (from humanity 45) + Concussion (-2), no armor penalty
    with patch("gameplay.skill_check", side_effect=lambda *a, **kw: skill_check(*a, **kw, randbelow=lambda _: 4)):
        emp_res = game.execute(
            "skill_check",
            {
                "character_id": char["id"],
                "expected_revision": char["revision"],
                "stat": "emp",
                "skill": None,
                "dv": 6,
                "reason": "read tell",
                "operation_id": "chk-emp",
            },
        )["result"]
    assert emp_res["stat_value"] == 4
    assert emp_res["armor_penalty"] == 0
    assert emp_res["injury_penalty"] == -2
    assert emp_res["total"] == 4 + 5 - 2  # stat 4 + die 5 - concussion 2 = 7
    assert emp_res["margin"] == 1
    assert emp_res["success"] is True
    assert emp_res["die"] == 5
    assert emp_res["explosion"] == 0
    assert emp_res["critical_success"] is False
    assert emp_res["critical_failure"] is False
    assert emp_res["reason"] == "read tell"
    assert any("Concussion (-2)" in r for r in emp_res["modifier_breakdown"])

    # 2. BODY check uses Linear Frame Sigma (12) + Concussion (-2)
    char = emp_res["character"]
    with patch("gameplay.skill_check", side_effect=lambda *a, **kw: skill_check(*a, **kw, randbelow=lambda _: 4)):
        body_res = game.execute(
            "skill_check",
            {
                "character_id": char["id"],
                "expected_revision": char["revision"],
                "stat": "BODY",
                "skill": None,
                "dv": 13,
                "reason": "bend bars",
                "operation_id": "chk-body",
            },
        )["result"]
    assert body_res["stat_value"] == 12
    assert body_res["total"] == 12 + 5 - 2  # 15

    # 3. DEX check with case-insensitive skill lookup ("evasion") applies armor penalty (-2) + Concussion (-2)
    char = body_res["character"]
    with patch("gameplay.skill_check", side_effect=lambda *a, **kw: skill_check(*a, **kw, randbelow=lambda _: 4)):
        dex_res = game.execute(
            "skill_check",
            {
                "character_id": char["id"],
                "expected_revision": char["revision"],
                "stat": "DEX",
                "skill": "evasion",
                "dv": 13,
                "reason": "dodge fire",
                "operation_id": "chk-dex",
            },
        )["result"]
    assert dex_res["skill_value"] == 4
    assert dex_res["armor_penalty"] == -2
    assert dex_res["injury_penalty"] == -2
    assert dex_res["total"] == 6 + 4 + 5 - 2 - 2  # 11

    # 4. ROLE check for Maker and TECH check for Field Expertise specialty
    char = dex_res["character"]
    with patch("gameplay.skill_check", side_effect=lambda *a, **kw: skill_check(*a, **kw, randbelow=lambda _: 4)):
        role_res = game.execute(
            "skill_check",
            {
                "character_id": char["id"],
                "expected_revision": char["revision"],
                "stat": "ROLE",
                "skill": "Maker",
                "dv": 6,
                "reason": "jury-rig",
                "operation_id": "chk-role",
            },
        )["result"]
    assert role_res["base"] == 3
    assert role_res["total"] == 3 + 5 - 2  # 6

    char = role_res["character"]
    with patch("gameplay.skill_check", side_effect=lambda *a, **kw: skill_check(*a, **kw, randbelow=lambda _: 4)):
        spec_res = game.execute(
            "skill_check",
            {
                "character_id": char["id"],
                "expected_revision": char["revision"],
                "stat": "TECH",
                "skill": "Field Expertise",
                "dv": 10,
                "reason": "field patch",
                "operation_id": "chk-spec",
            },
        )["result"]
    assert spec_res["skill_value"] == 2
    assert spec_res["total"] == 6 + 2 + 5 - 2  # 11


def test_check_honors_pain_editor_net_debuff_and_solo_fumble_recovery(tmp_path):
    game = GameplayService(tmp_path / "campaign.sqlite")
    char = game.execute(
        "create_character",
        {
            "name": "SoloV",
            "stats": dict.fromkeys(STAT_NAMES, 6),
            "skills": {"Perception": 5},
            "detail": {
                "cyberware": [{"name": "Pain Editor", "installed": True}],
                "net_debuffs": {"REF": 2},
                "roles": [{"role": "Solo", "rank": 7}],
                "solo_allocation": {"threat_detection": 3, "fumble_recovery": True},
            },
            "operation_id": "create-solo",
        },
    )["result"]
    char = game.store.update_character(char["id"], char["revision"], {"hp": 10}, "wounded", "wounded")

    # Natural 1 on Perception with Fumble Recovery -> ignores critical fumble subtraction,
    # Pain Editor ignores serious wound -2, Threat Detection adds +3.
    with patch("gameplay.skill_check", side_effect=lambda *a, **kw: skill_check(*a, **kw, randbelow=lambda _: 0)):
        perc_res = game.execute(
            "skill_check",
            {
                "character_id": char["id"],
                "expected_revision": char["revision"],
                "stat": "INT",
                "skill": "Perception",
                "dv": 13,
                "reason": "spot ambush",
                "operation_id": "chk-perc",
            },
        )["result"]
    assert perc_res["wound_modifier"] == 0
    assert perc_res["solo_bonus"] == 3
    assert perc_res["fumble_recovery"] is True
    assert perc_res["dice"] == [1]
    assert perc_res["die"] == 1
    assert perc_res["critical_adjustment"] == 0
    assert perc_res["explosion"] == 0
    assert perc_res["critical_failure"] is False
    assert perc_res["total"] == 6 + 5 + 1 + 3  # 15 (fumble -1 was ignored!)
    assert perc_res["success"] is True

    # NET debuff on REF reduces effective stat from 6 to 4
    char = perc_res["character"]
    with patch("gameplay.skill_check", side_effect=lambda *a, **kw: skill_check(*a, **kw, randbelow=lambda _: 4)):
        ref_res = game.execute(
            "skill_check",
            {
                "character_id": char["id"],
                "expected_revision": char["revision"],
                "stat": "REF",
                "skill": None,
                "dv": 10,
                "reason": "quick draw",
                "operation_id": "chk-ref",
            },
        )["result"]
    assert ref_res["stat_value"] == 4
    assert ref_res["total"] == 4 + 5


def test_chat_roll_endpoint_validation_complementary_retry_and_sync(tmp_path):
    import asyncio
    import sys
    from pathlib import Path

    httpx = pytest.importorskip("httpx")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import redkb
    from campaign import STAT_NAMES
    from server.coop import _CoopHub

    camp_db = tmp_path / "campaign.sqlite"
    svc = GameplayService(camp_db)
    camp = svc.execute("create_campaign", {"name": "Roll Test", "operation_id": "c1"})["result"]
    char = svc.execute(
        "create_character",
        {
            "name": "SoloV",
            "stats": dict.fromkeys(STAT_NAMES, 6),
            "skills": {"Handgun": 5},
            "operation_id": "ch1",
        },
    )["result"]
    svc.execute(
        "attach_character",
        {
            "campaign_id": camp["id"],
            "character_id": char["id"],
            "expected_revision": camp["revision"],
            "reason": "join",
            "operation_id": "att1",
        },
    )

    published = []
    orig_publish = _CoopHub.publish

    def spy_publish(self, cid, event, data):
        published.append((cid, event, data))
        return orig_publish(self, cid, event, data)

    async def run():
        app = redkb.make_api(
            tmp_path / "rules.sqlite",
            ("http://localhost:8000",),
            campaign_path=camp_db,
        )

        with patch.object(_CoopHub, "publish", spy_publish):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                # Reject boolean dv and modifier
                bad_dv = await client.post(
                    "/v1/chat/roll",
                    json={"campaign_id": camp["id"], "character_id": char["id"], "stat": "REF", "dv": True},
                )
                assert bad_dv.status_code == 400
                bad_mod = await client.post(
                    "/v1/chat/roll",
                    json={"campaign_id": camp["id"], "character_id": char["id"], "stat": "REF", "modifier": False},
                )
                assert bad_mod.status_code == 400

                # Valid roll with complementary=True, extra_time=True, channel_id, and transient revision conflict retry
                orig_check = GameplayService.check
                attempts = {"count": 0}

                def flaky_check(self, *args, **kwargs):
                    attempts["count"] += 1
                    if attempts["count"] == 1:
                        raise ValueError("revision conflict; read the character before rolling")
                    return orig_check(self, *args, **kwargs)

                with patch.object(GameplayService, "check", flaky_check), patch(
                    "gameplay.skill_check",
                    side_effect=lambda *a, **kw: skill_check(*a, **kw, randbelow=lambda _: 9),
                ):
                    ok = await client.post(
                        "/v1/chat/roll",
                        json={
                            "campaign_id": camp["id"],
                            "character_id": char["id"],
                            "stat": "REF",
                            "skill": "Handgun",
                            "dv": 15,
                            "modifier": 1,
                            "complementary": True,
                            "extra_time": True,
                            "channel_id": "split-a",
                            "reason": "Snipe lock",
                        },
                    )
                assert attempts["count"] == 2
                assert ok.status_code == 200
                body = ok.json()
                assert body["roll"]["die"] == 10
                assert body["roll"]["explosion"] == 10
                assert body["roll"]["critical_adjustment"] == 10
                assert body["result"]["die"] == 10
                assert body["result"]["explosion"] == 10
                assert body["result"]["critical_adjustment"] == 10
                assert body["result"]["total"] == 6 + 5 + 10 + 10 + 1 + 1 + 1  # 34
                assert any(
                    ev == "sync" and data.get("channel_id") == "split-a"
                    for _, ev, data in published
                )

    asyncio.run(run())
