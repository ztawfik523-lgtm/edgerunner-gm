import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from campaign import CampaignStore, STAT_NAMES


def stats(**overrides):
    result = {key: 50 for key in STAT_NAMES}
    result.update(overrides)
    return result


def test_create_derived_state_and_reopen(tmp_path):
    path = tmp_path / "private" / "campaign.sqlite"
    store = CampaignStore(path)
    character = store.create_character("Rogue", stats(BODY=41, WILL=32, EMP=42, LUCK=8), {"Handgun": 60})
    assert character["hp"] == character["max_hp"] == 195
    assert character["humanity"] == 420
    assert character["luck_remaining"] == 8
    assert character["revision"] == 1
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    reopened = CampaignStore(path)
    assert reopened.get_character(character["id"]) == character
    assert reopened.list_characters() == [character]


def test_update_audit_revision_and_idempotency(tmp_path):
    store = CampaignStore(tmp_path / "campaign.sqlite")
    character = store.create_character("Solo", stats())
    changes = {"hp": -2, "money": 125, "inventory": {"Pistol": 1}}
    result = store.update_character(character["id"], 1, changes, "took damage", "op-1")
    assert result["revision"] == 2
    assert store.update_character(character["id"], 1, changes, "took damage", "op-1") == result
    with pytest.raises(ValueError, match="different update"):
        store.update_character(character["id"], 1, {"hp": 0}, "took damage", "op-1")
    with pytest.raises(ValueError, match="revision conflict"):
        store.update_character(character["id"], 1, {"hp": 0}, "later", "op-2")
    events = store.audit_events(character["id"])
    assert len(events) == 2
    assert events[1]["before"]["hp"] == character["max_hp"]
    assert events[1]["after"] == result
    assert events[1]["reason"] == "took damage"


def test_undo_is_audited_monotonic_and_idempotent(tmp_path):
    store = CampaignStore(tmp_path / "campaign.sqlite")
    character = store.create_character("Solo", stats())
    changed = store.update_character(character["id"], 1, {"hp": 20, "money": 50}, "change", "change-1")
    undone = store.undo_last(character["id"], 2, "reverse mistake", "undo-1")
    assert undone["hp"] == character["hp"]
    assert undone["money"] == character["money"]
    assert undone["revision"] == 3
    assert store.undo_last(character["id"], 2, "reverse mistake", "undo-1") == undone
    with pytest.raises(ValueError, match="revision conflict"):
        store.undo_last(character["id"], 2, "stale", "undo-2")
    events = store.audit_events(character["id"])
    assert len(events) == 3 and events[-1]["before"] == changed and events[-1]["after"] == undone


def test_create_operation_idempotency_and_rules_database_guard(tmp_path):
    path = tmp_path / "campaign.sqlite"
    store = CampaignStore(path)
    character = store.create_character("Solo", stats(), operation_id="create-1")
    assert store.create_character("Solo", stats(), operation_id="create-1") == character
    with pytest.raises(ValueError, match="different create"):
        store.create_character("Other", stats(), operation_id="create-1")
    other = tmp_path / "rules.sqlite"
    import sqlite3
    with sqlite3.connect(other) as conn:
        conn.execute("CREATE TABLE rules_index (id INTEGER)")
    with pytest.raises(ValueError, match="not an empty campaign"):
        CampaignStore(other)


@pytest.mark.parametrize("bad_stats", [
    {}, {**stats(), "EXTRA": 1}, {**stats(), "INT": True}, {**stats(), "BODY": 101},
])
def test_invalid_stats_rejected(tmp_path, bad_stats):
    with pytest.raises(ValueError):
        CampaignStore(tmp_path / "c.sqlite").create_character("A", bad_stats)


def test_invalid_skill_and_update_values_rejected(tmp_path):
    store = CampaignStore(tmp_path / "c.sqlite")
    with pytest.raises(ValueError):
        store.create_character("A", stats(), {"": 1})
    character = store.create_character("A", stats())
    for changes in ({"hp": character["max_hp"] + 1}, {"money": -1}, {"inventory": {"x": -1}}, {"stats": stats()}):
        with pytest.raises(ValueError):
            store.update_character(character["id"], 1, changes, "bad", "bad-" + str(len(changes)))


def test_enriched_create_and_update_character_profile(tmp_path):
    store = CampaignStore(tmp_path / "c.sqlite")
    char = store.create_character(
        "Nova",
        stats(),
        skills={"Handgun": 4},
        money=1250,
        inventory={"Heavy Pistol": 1},
        detail={"roles": [{"role": "Solo", "rank": 4}], "backstory": {"concept": "Ex-corp"}},
        humanity=53,
    )
    assert char["money"] == 1250
    assert char["humanity"] == 53
    assert char["inventory"] == {"Heavy Pistol": 1}
    assert char["detail"]["backstory"]["concept"] == "Ex-corp"

    updated = store.update_character_profile(
        char["id"],
        expected_revision=char["revision"],
        profile={
            "backstory": {
                "concept": "Ex-corp turned edgerunner",
                "established_history": "Burned a Militech convoy in 2044.",
            },
            "appearance": "Mirrorshades and scuffed synthleather.",
        },
        reason="Added established history",
        operation_id="prof-1",
    )
    assert updated["revision"] == 2
    assert updated["detail"]["backstory"]["concept"] == "Ex-corp turned edgerunner"
    assert updated["detail"]["backstory"]["established_history"] == "Burned a Militech convoy in 2044."
    assert updated["detail"]["appearance"] == "Mirrorshades and scuffed synthleather."
    assert updated["detail"]["roles"] == [{"role": "Solo", "rank": 4}]
