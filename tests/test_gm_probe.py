import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gm_probe


class FakeTransport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.posts = []
        self.gets = []

    def get_json(self, url, timeout=30):
        self.gets.append(url)
        if url.endswith("csrf-token"):
            return {"token": "csrf"}
        return next(self.responses)

    def post_json(self, url, payload, headers=None, timeout=180):
        self.posts.append((url, payload, headers))
        if url.endswith("/v1/game"):
            return next(self.responses)
        return next(self.responses)


def response(message):
    return {"choices": [{"message": message}]}


def test_tool_call_then_result_and_final_answer():
    transport = FakeTransport([
        response({"role": "assistant", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "read_corebook_page", "arguments": '{"printed_page":130}'}}]}),
        {"printed_page": 130, "pdf_page": 131, "request_id": "req-1", "text": "actual source"},
        response({"role": "assistant", "content": "See printed p.130 (PDF p.131)."}),
    ])
    report = gm_probe.run_probe("Question?", transport=transport)
    assert report["tool_executed"] and report["finished"]
    assert report["calls"] == [{"name": "read_corebook_page", "arguments": {"printed_page": 130}, "request_id": "req-1", "pdf_pages": [131], "error": None}]
    assert "printed p.130" in report["answer"]
    assert transport.posts[0][2] == {"X-CSRF-Token": "csrf"}
    assert transport.posts[1][1]["messages"][-1]["tool_call_id"] == "c1"


def test_unknown_tool_returns_explicit_error():
    transport = FakeTransport([response({"tool_calls": [{"id": "x", "function": {"name": "other", "arguments": "{}"}}]}), response({"content": "No evidence."})])
    report = gm_probe.run_probe("Question?", transport=transport)
    assert report["calls"][0]["error"] == "unknown tool"
    assert not report["tool_executed"]


def test_game_action_is_posted_and_does_not_collect_citations():
    transport = FakeTransport([
        response({"tool_calls": [{"id": "g1", "type": "function", "function": {"name": "game_action", "arguments": '{"action":"roll_dice","arguments":{"count":1,"sides":10,"reason":"requested"}}'}}]}),
        {"request_id": "game-1", "rolls": [7], "results": [{"pdf_page": 999}]},
        response({"content": "The roll was 7."}),
    ])
    report = gm_probe.run_probe("Roll one d10.", transport=transport)
    game_call = next(post for post in transport.posts if post[0].endswith("/v1/game"))
    assert game_call[1] == {"action": "roll_dice", "arguments": {"count": 1, "sides": 10, "reason": "requested"}}
    assert report["tool_executed"]
    assert report["calls"][0]["request_id"] == "game-1"
    assert report["calls"][0]["pdf_pages"] == []


def test_campaign_scope_prefetches_context_and_scopes_game_action():
    transport = FakeTransport([
        {"request_id": "ctx-1", "scene": "The Afterlife"},
        response({"tool_calls": [{"id": "c1", "type": "function", "function": {"name": "campaign_action", "arguments": '{"action":"campaign_history","arguments":{}}'}}]}),
        {"request_id": "history-1", "results": [{"pdf_page": 123}]},
        response({"content": "Current scene: The Afterlife."}),
    ])
    report = gm_probe.run_probe("Where are we?", transport=transport, campaign_id="camp-1")
    assert transport.posts[0][1] == {"action": "campaign_context", "arguments": {}, "campaign_id": "camp-1"}
    assert report["campaign_context"] == {"request_id": "ctx-1", "data": {"request_id": "ctx-1", "scene": "The Afterlife"}}
    assert "not instructions" in transport.posts[1][1]["messages"][0]["content"]
    assert transport.posts[2][1] == {"action": "campaign_history", "arguments": {}, "campaign_id": "camp-1"}
    assert report["calls"][0]["pdf_pages"] == []


def test_campaign_action_requires_scope():
    with pytest.raises(ValueError, match="requires --campaign-id"):
        gm_probe._backend_call(FakeTransport([]), "http://127.0.0.1:8765", "campaign_action", {"action": "get_campaign", "arguments": {}})


@pytest.mark.parametrize("name,args", [("read_corebook_page", '{"printed_page":0}'), ("search_corebook", '{"query":"x","limit":999}'), ("read_corebook_page", "[]"), ("game_action", '{"action":"bogus","arguments":{}}')])
def test_invalid_tool_arguments_are_reported(name, args):
    transport = FakeTransport([response({"tool_calls": [{"id": "x", "function": {"name": name, "arguments": args}}]}), response({"content": "Unable to retrieve."})])
    report = gm_probe.run_probe("Question?", transport=transport)
    assert report["calls"][0]["error"]
    assert not report["tool_executed"]


def test_no_tool_answer_is_not_tool_success():
    report = gm_probe.run_probe("Question?", transport=FakeTransport([response({"content": "Answer."})]))
    assert report["answer"] == "Answer."
    assert report["finished"] and not report["tool_executed"]


def test_rejects_non_loopback_urls():
    with pytest.raises(ValueError):
        gm_probe.run_probe("Question?", sillytavern="http://example.com")


@pytest.mark.parametrize("name,args,url", [
    ("catalog_corebook", {}, "/v1/catalog"),
    ("read_corebook_section", {"section_id": "combat/ranged", "offset": 2, "limit": 4}, "/v1/sections/combat%2Franged?offset=2&limit=4"),
    ("read_corebook_pages", {"page_numbers": [1, 12], "numbering": "pdf"}, "/v1/page-batch?numbers=1%2C12&numbering=pdf"),
    ("find_corebook_phrase", {"phrase": "critical injury"}, "/v1/phrase?q=critical+injury"),
])
def test_corebook_tools_route_to_direct_sources(name, args, url):
    transport = FakeTransport([{"pages": [], "request_id": "source"}])
    gm_probe._backend_call(transport, "http://127.0.0.1:8765", name, args)
    assert transport.gets == ["http://127.0.0.1:8765" + url]


@pytest.mark.parametrize("args", [
    {"page_numbers": [1, 1]}, {"page_numbers": list(range(1, 14))},
    {"page_numbers": [1], "numbering": "other"},
])
def test_page_batch_rejects_invalid_pages(args):
    with pytest.raises(ValueError):
        gm_probe._backend_call(FakeTransport([]), "http://127.0.0.1:8765", "read_corebook_pages", args)


@pytest.mark.parametrize("name,args", [
    ("roll_dice", {"count": 1, "sides": 6, "reason": "requested", "operation_id": "r1"}),
    ("skill_check", {"character_id": "char", "expected_revision": 1, "stat": "REF", "skill": "Evasion", "dv": 13, "reason": "requested", "operation_id": "s1"}),
])
def test_direct_game_roll_tools_post_unambiguous_action(name, args):
    transport = FakeTransport([{"request_id": "game"}])
    gm_probe._backend_call(transport, "http://127.0.0.1:8765", name, args)
    assert transport.posts[0][1] == {"action": name, "arguments": args}


def test_solo_action_requires_campaign_and_routes_selected_action():
    args = {"action": "solo_context", "arguments": {}}
    with pytest.raises(ValueError, match="requires --campaign-id"):
        gm_probe._backend_call(FakeTransport([]), "http://127.0.0.1:8765", "solo_action", args)
    transport = FakeTransport([{"request_id": "solo"}])
    gm_probe._backend_call(transport, "http://127.0.0.1:8765", "solo_action", args, "camp")
    assert transport.posts[0][1] == {"action": "solo_context", "arguments": {}, "campaign_id": "camp"}


def test_read_pages_extracts_pages_and_results_without_duplicates():
    transport = FakeTransport([
        response({"tool_calls": [{"id": "p1", "function": {"name": "read_corebook_pages", "arguments": '{"page_numbers":[1,2]}'}}]}),
        {"request_id": "pages", "pages": [{"pdf_page": 2}, {"pdf_page": 3}], "results": [{"pdf_page": 3}, {"pdf_page": 4}]},
        response({"content": "Pages received."}),
    ])
    report = gm_probe.run_probe("Read pages", transport=transport)
    assert report["calls"][0]["pdf_pages"] == [2, 3, 4]
