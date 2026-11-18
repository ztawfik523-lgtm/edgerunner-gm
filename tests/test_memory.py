import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from campaign import CampaignStore, STAT_NAMES
from memory import CampaignMemory


def stats(**overrides):
    values = dict.fromkeys(STAT_NAMES, 50)
    values.update(overrides)
    return values


def setup(tmp_path):
    store = CampaignStore(tmp_path / "campaign.sqlite")
    memory = CampaignMemory(store)
    return store, memory


def test_campaign_persistence_update_undo_and_retry(tmp_path):
    store, memory = setup(tmp_path)
    c = memory.create_campaign("Night City", "create")
    changes = {"scene": "At the Afterlife", "npcs": {"Rogue": "Fixer"}}
    updated = memory.update_campaign(c["id"], 1, changes, "opening", "update")
    assert memory.update_campaign(c["id"], 1, changes, "opening", "update") == updated
    assert CampaignMemory(CampaignStore(store.path)).get_campaign(c["id"]) == updated
    undone = memory.undo_campaign(c["id"], 2, "undo opening", "undo")
    assert undone["state"] == c["state"] and undone["revision"] == 3
    assert memory.undo_campaign(c["id"], 2, "undo opening", "undo") == undone
    assert [e["payload"]["action"] for e in memory.history(c["id"])] == ["create_campaign", "update_campaign", "undo_campaign"]
    with pytest.raises(ValueError, match="different campaign"):
        memory.create_campaign("Other", "create")


def test_membership_is_single_campaign_and_optimistic(tmp_path):
    store, m = setup(tmp_path)
    a, b = m.create_campaign("A", "a"), m.create_campaign("B", "b")
    char = store.create_character("Solo", stats())
    attached = m.attach_character(a["id"], char["id"], 1, "join", "join")
    assert attached["character_ids"] == [char["id"]]
    with pytest.raises(ValueError, match="another campaign"):
        m.attach_character(b["id"], char["id"], 1, "join", "join-b")
    with pytest.raises(ValueError, match="revision conflict"):
        m.attach_character(a["id"], char["id"], 1, "stale", "stale")


def test_session_refills_luck_atomically_and_retries(tmp_path):
    store, m = setup(tmp_path)
    c = m.create_campaign("A", "create")
    members = [store.create_character(n, stats(LUCK=i)) for n, i in (("One", 8), ("Two", 4))]
    rev = 1
    for i, char in enumerate(members):
        c = m.attach_character(c["id"], char["id"], rev, "join", f"join{i}")
        rev += 1
    for char in members:
        store.update_character(char["id"], 1, {"hp": 10}, "spend time", "damage:" + char["id"])
        with store._connect() as conn:
            conn.execute("UPDATE characters SET luck_remaining=0 WHERE id=?", (char["id"],))
    result = m.start_session(c["id"], rev, "new session", "session")
    assert result["session_number"] == 1 and result["revision"] == rev + 1
    assert m.start_session(c["id"], rev, "new session", "session") == result
    for char in members:
        current = store.get_character(char["id"])
        assert current["luck_remaining"] == char["stats"]["LUCK"] and current["revision"] == 3
        event = store.audit_events(char["id"])[-1]
        assert event["reason"] == "session start: new session"
        assert event["operation_id"] == f"session:character:{char['id']}"
    with pytest.raises(ValueError, match="not narrative"):
        m.undo_campaign(c["id"], result["revision"], "no", "undo-session")


@pytest.mark.parametrize("changes", [
    {"scene": 4}, {"other": "x"}, {"npcs": {"": "x"}},
    {"objectives": {"x": "x" * 2001}}, {"discoveries": {str(i): "v" for i in range(41)}},
    {"scene": "x" * 4001},
])
def test_invalid_narrative_rejected(tmp_path, changes):
    _, m = setup(tmp_path)
    c = m.create_campaign("A", "create")
    with pytest.raises(ValueError):
        m.update_campaign(c["id"], 1, changes, "reason", "bad")


def test_total_state_limit_and_missing_campaign(tmp_path):
    _, m = setup(tmp_path)
    c = m.create_campaign("A", "create")
    with pytest.raises(ValueError, match="24000"):
        m.update_campaign(c["id"], 1, {"summary": "s" * 4000, "scene": "x" * 4000,
          "npcs": {str(i): "v" * 1000 for i in range(24)}}, "reason", "large")
    assert m.get_campaign("absent") is None
    with pytest.raises(ValueError, match="not found"):
        m.update_campaign("absent", 1, {"scene": "x"}, "reason", "absent")


def test_session_collision_rolls_back_all_characters_and_preserves_retry(tmp_path):
    from contextlib import closing
    store, memory = setup(tmp_path)
    campaign = memory.create_campaign("Test", "create")
    members = [store.create_character(name, stats(LUCK=6)) for name in ("One", "Two")]
    for i, char in enumerate(members):
        campaign = memory.attach_character(campaign["id"], char["id"], campaign["revision"], "join", f"join-{i}")
    with closing(store._connect()) as conn, conn:
        conn.execute("UPDATE characters SET luck_remaining=0")
    collision = f"session:character:{members[1]['id']}"
    revision = campaign["revision"]
    updated = memory.update_campaign(campaign["id"], revision, {"scene": "Clinic"}, "arrived", collision)
    with pytest.raises(ValueError, match="campaign change"):
        memory.start_session(campaign["id"], updated["revision"], "new session", "session")
    assert all(store.get_character(c["id"])["luck_remaining"] == 0 for c in members)
    assert all(len(store.audit_events(c["id"])) == 1 for c in members)
    assert memory.get_campaign(campaign["id"])["session_number"] == 0
    assert memory.update_campaign(campaign["id"], revision, {"scene": "Clinic"}, "arrived", collision) == updated
