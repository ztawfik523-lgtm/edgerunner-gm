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
