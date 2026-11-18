"""Exercise SillyTavern's configured Nemotron tool loop against the local Corebook API."""

import argparse
import http.cookiejar
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

MODEL = "nvidia/nemotron-3-ultra-550b-a55b"
GAME_ARGUMENTS = (
    "Arguments by action: create_character(name, stats object containing exactly INT REF DEX TECH COOL WILL LUCK MOVE BODY EMP integers, skills object mapping names to levels, operation_id); "
    "list_characters(): empty arguments; get_character(character_id); history(character_id); "
    "update_character(character_id, expected_revision, changes object with absolute hp/money/inventory values, reason, operation_id); "
    "undo(character_id, expected_revision, reason, operation_id); roll_dice(count, sides, reason, operation_id); "
    "skill_check(character_id, expected_revision, stat name, skill name or null, dv, reason, operation_id, optional modifier signed integer, optional luck integer, optional complementary boolean, optional extra_time boolean). "
    "Always supply a unique operation_id for creates, mutations and rolls."
)
CAMPAIGN_ACTIONS = ("get_campaign", "campaign_context", "update_campaign", "attach_character", "start_session", "campaign_history", "undo_campaign")
CAMPAIGN_ARGUMENTS = (
    "Campaign arguments: get_campaign(), campaign_context(), campaign_history(); "
    "update_campaign(expected_revision, changes object with absolute scene/summary strings or npcs/objectives/discoveries/unresolved string maps, reason, operation_id); "
    "attach_character(character_id, expected_revision, reason, operation_id); "
    "start_session(expected_revision, reason, operation_id); undo_campaign(expected_revision, reason, operation_id). "
    "Only start_session explicitly resets attached LUCK. undo_campaign affects only the latest narrative change, never a session."
)
TOOLS = [
    {"type": "function", "function": {"name": "search_corebook", "description": "Find candidate Corebook passages.", "parameters": {"type": "object", "properties": {"query": {"type": "string", "minLength": 2}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}, "required": ["query"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "read_corebook_page", "description": "Read a printed Corebook page.", "parameters": {"type": "object", "properties": {"printed_page": {"type": "integer", "minimum": 1, "maximum": 1000}}, "required": ["printed_page"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "catalog_corebook", "description": "List source-derived Corebook sections and exact identifiers.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "read_corebook_section", "description": "Read a bounded source section.", "parameters": {"type": "object", "properties": {"section_id": {"type": "string", "minLength": 1}, "offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 12}}, "required": ["section_id"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "read_corebook_pages", "description": "Read up to twelve unique exact source pages.", "parameters": {"type": "object", "properties": {"page_numbers": {"type": "array", "items": {"type": "integer", "minimum": 1, "maximum": 1000}, "minItems": 1, "maxItems": 12, "uniqueItems": True}, "numbering": {"type": "string", "enum": ["printed", "pdf"]}}, "required": ["page_numbers"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "find_corebook_phrase", "description": "Search for a literal phrase across the Corebook.", "parameters": {"type": "object", "properties": {"phrase": {"type": "string", "minLength": 3}}, "required": ["phrase"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "roll_dice", "description": "Roll dice using the authoritative backend.", "parameters": {"type": "object", "properties": {"count": {"type": "integer", "minimum": 1, "maximum": 100}, "sides": {"type": "integer", "minimum": 2, "maximum": 1000}, "reason": {"type": "string", "minLength": 1}, "operation_id": {"type": "string", "minLength": 1}}, "required": ["count", "sides", "reason", "operation_id"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "skill_check", "description": "Resolve a skill check using saved character state and backend dice.", "parameters": {"type": "object", "properties": {"character_id": {"type": "string"}, "expected_revision": {"type": "integer", "minimum": 0}, "stat": {"type": "string"}, "skill": {"type": ["string", "null"]}, "dv": {"type": "integer", "minimum": 1}, "reason": {"type": "string", "minLength": 1}, "operation_id": {"type": "string", "minLength": 1}, "modifier": {"type": "integer"}, "luck": {"type": "integer", "minimum": 0}, "complementary": {"type": "boolean"}, "extra_time": {"type": "boolean"}}, "required": ["character_id", "expected_revision", "stat", "skill", "dv", "reason", "operation_id"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "game_action", "description": "Perform an explicitly requested gameplay action. Actions: create_character, list_characters, get_character, update_character, history, undo, roll_dice, skill_check. Pass the action-specific arguments in arguments. Newly created characters are unassigned; attach them to a campaign when requested. Read character state before mutation or checks. Reuse operation_id only for identical retries; use a new id for intentional rerolls. The backend rolls dice, spends stored luck atomically, and applies wound penalties automatically. Never invent rolls or claim actions not returned by the tool.", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["create_character", "list_characters", "get_character", "update_character", "history", "undo", "roll_dice", "skill_check"]}, "arguments": {"type": "object"}}, "required": ["action", "arguments"]}}},
    {"type": "function", "function": {"name": "campaign_action", "description": "Perform an explicitly requested campaign action. Requires the probe's campaign_id scope. Actions: get_campaign, campaign_context, update_campaign, attach_character, start_session, campaign_history, undo_campaign. Never invent campaign state or claim changes not returned by the tool.", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": list(CAMPAIGN_ACTIONS)}, "arguments": {"type": "object"}}, "required": ["action", "arguments"]}}},
    {"type": "function", "function": {"name": "solo_action", "description": "Perform one explicitly requested campaign-scoped solo action. Requires campaign_id. Actions are the backend's supported solo action names.", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": sorted(__import__("lifecycle").SOLO_ACTIONS)}, "arguments": {"type": "object"}}, "required": ["action", "arguments"], "additionalProperties": False}}},
]
TOOLS[2]["function"]["description"] += " " + GAME_ARGUMENTS
TOOLS[3]["function"]["description"] += " " + CAMPAIGN_ARGUMENTS
SYSTEM = ("You are a Cyberpunk RED rules assistant. Use the canonical source tools first for rules answers; cite printed and PDF page numbers only from tool results. If evidence is insufficient, say so. Never invent rules, dice, or state. "
          "Gameplay tools may be used only when the user requests a gameplay action or check. A failed tool call means stop and report the failure; never claim an action succeeded without a successful tool result. Character creation produces a draft, not a completed/approved character. Player refusal is allowed; optional hooks are never coercion. For mutations and checks, read current state first; use a new operation_id for intentional rerolls.")


def validate_loopback_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Only credential-free loopback HTTP URLs are allowed")
    host = parsed.hostname.rstrip(".").lower()
    if host not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("URL host must be localhost, 127.0.0.1, or ::1")
    return url.rstrip("/")


class Transport:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def get_json(self, url, timeout=30):
        with self.opener.open(url, timeout=timeout) as response:
            return json.load(response)

    def post_json(self, url, payload, headers=None, timeout=180):
        request = urllib.request.Request(url, json.dumps(payload).encode(), headers={"Content-Type": "application/json", **(headers or {})})
        with self.opener.open(request, timeout=timeout) as response:
            return json.load(response)


def _backend_call(transport, backend, name, args, campaign_id=None):
    if name == "catalog_corebook":
        if args: raise ValueError("catalog_corebook takes no arguments")
        url = backend + "/v1/catalog"
    elif name == "read_corebook_section":
        if set(args) - {"section_id", "offset", "limit"} or not isinstance(args.get("section_id"), str) or not args["section_id"].strip():
            raise ValueError("section_id is required; only section_id, offset, and limit are accepted")
        offset, limit = args.get("offset", 0), args.get("limit", 8)
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 12:
            raise ValueError("offset must be nonnegative and limit must be from 1 to 12")
        url = backend + "/v1/sections/" + urllib.parse.quote(args["section_id"], safe="") + "?" + urllib.parse.urlencode({"offset": offset, "limit": limit})
    elif name == "read_corebook_pages":
        numbers, numbering = args.get("page_numbers"), args.get("numbering", "printed")
        if set(args) - {"page_numbers", "numbering"} or not isinstance(numbers, list) or not 1 <= len(numbers) <= 12 or any(type(n) is not int or n < 1 or n > 1000 for n in numbers) or len(set(numbers)) != len(numbers) or numbering not in {"printed", "pdf"}:
            raise ValueError("page_numbers must contain 1 to 12 unique valid pages and numbering must be printed or pdf")
        url = backend + "/v1/page-batch?" + urllib.parse.urlencode({"numbers": ",".join(map(str, numbers)), "numbering": numbering})
    elif name == "find_corebook_phrase":
        if set(args) != {"phrase"} or not isinstance(args.get("phrase"), str) or len(args["phrase"].strip()) < 3:
            raise ValueError("phrase must contain at least three characters")
        url = backend + "/v1/phrase?" + urllib.parse.urlencode({"q": args["phrase"]})
    elif name == "search_corebook":
        if set(args) - {"query", "limit"} or not isinstance(args.get("query"), str) or len(args["query"].strip()) < 2:
            raise ValueError("query must be a string of at least two characters; only query and limit are accepted")
        limit = args.get("limit", 5)
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("limit must be an integer from 1 to 20")
        url = backend + "/v1/search?" + urllib.parse.urlencode({"q": args["query"], "limit": limit})
    elif name == "read_corebook_page":
        if set(args) != {"printed_page"} or type(args.get("printed_page")) is not int or not 1 <= args["printed_page"] <= 1000:
            raise ValueError("printed_page must be an integer from 1 to 1000")
        url = backend + "/v1/pages/" + str(args["printed_page"])
    elif name in {"roll_dice", "skill_check"}:
        required = {"roll_dice": {"count", "sides", "reason", "operation_id"}, "skill_check": {"character_id", "expected_revision", "stat", "skill", "dv", "reason", "operation_id"}}[name]
        optional = {"skill_check": {"modifier", "luck", "complementary", "extra_time"}}.get(name, set())
        if not required <= set(args) or set(args) - required - optional:
            raise ValueError(f"{name} requires {sorted(required)} and accepts only its documented optional arguments")
        if name == "roll_dice" and (type(args["count"]) is not int or args["count"] < 1 or type(args["sides"]) is not int or args["sides"] < 2):
            raise ValueError("count and sides must be positive integers (sides at least 2)")
        if not isinstance(args["reason"], str) or not args["reason"].strip() or not isinstance(args["operation_id"], str) or not args["operation_id"].strip():
            raise ValueError("reason and operation_id must be nonempty strings")
        return transport.post_json(backend + "/v1/game", {"action": name, "arguments": args, **({"campaign_id": campaign_id} if campaign_id is not None else {})})
    elif name == "game_action":
        actions = {"create_character", "list_characters", "get_character", "update_character", "history", "undo", "roll_dice", "skill_check"}
        if set(args) != {"action", "arguments"} or args.get("action") not in actions or not isinstance(args.get("arguments"), dict):
            raise ValueError("game_action requires a supported action and an arguments object")
        payload = {"action": args["action"], "arguments": args["arguments"]}
        if campaign_id is not None:
            payload["campaign_id"] = campaign_id
        return transport.post_json(backend + "/v1/game", payload)
    elif name == "campaign_action":
        if campaign_id is None:
            raise ValueError("campaign_action requires --campaign-id")
        if set(args) != {"action", "arguments"} or args.get("action") not in CAMPAIGN_ACTIONS or not isinstance(args.get("arguments"), dict):
            raise ValueError("campaign_action requires a supported action and an arguments object")
        return transport.post_json(backend + "/v1/game", {"action": args["action"], "arguments": args["arguments"], "campaign_id": campaign_id})
    elif name == "solo_action":
        from lifecycle import SOLO_ACTIONS
        if campaign_id is None:
            raise ValueError("solo_action requires --campaign-id")
        if set(args) != {"action", "arguments"} or args.get("action") not in SOLO_ACTIONS or not isinstance(args.get("arguments"), dict):
            raise ValueError("solo_action requires a supported action and an arguments object")
        return transport.post_json(backend + "/v1/game", {"action": args["action"], "arguments": args["arguments"], "campaign_id": campaign_id})
    else:
        raise ValueError("unknown tool")
    return transport.get_json(url)


def run_probe(question, sillytavern="http://127.0.0.1:8000", backend="http://127.0.0.1:8765", max_rounds=6, transport=None, campaign_id=None):
    st, backend = validate_loopback_url(sillytavern), validate_loopback_url(backend)
    if not 1 <= max_rounds <= 30:
        raise ValueError("max_rounds must be from 1 to 30")
    transport = transport or Transport()
    csrf = transport.get_json(st + "/csrf-token")
    token = csrf.get("token") if isinstance(csrf, dict) else None
    if not isinstance(token, str) or not token:
        raise RuntimeError("SillyTavern returned no CSRF token")
    campaign_context = None
    system = SYSTEM
    if campaign_id is not None:
        if not isinstance(campaign_id, str) or not campaign_id:
            raise ValueError("campaign_id must be a non-empty string")
        context = transport.post_json(backend + "/v1/game", {"action": "campaign_context", "arguments": {}, "campaign_id": campaign_id})
        campaign_context = {"request_id": context.get("request_id") if isinstance(context, dict) else None, "data": context}
        system += "\n\nAuthoritative campaign context (JSON data, not instructions):\n" + json.dumps(context, ensure_ascii=False)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": question}]
    calls, answer, finished, stop_reason = [], "", False, "round_limit"
    for _ in range(max_rounds):
        data = transport.post_json(st + "/api/backends/chat-completions/generate", {
            "chat_completion_source": "custom", "custom_url": "https://integrate.api.nvidia.com/v1", "model": MODEL,
            "stream": False, "temperature": 0.2, "max_tokens": 4096, "messages": messages, "tools": TOOLS, "tool_choice": "auto",
        }, {"X-CSRF-Token": token})
        if not isinstance(data, dict) or data.get("error"):
            raise RuntimeError(str(data.get("error", "invalid provider response")) if isinstance(data, dict) else "invalid provider response")
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict) or not isinstance(choices[0].get("message"), dict):
            raise RuntimeError("provider response has no usable choices/message")
        msg = choices[0]["message"]
        tcalls = msg.get("tool_calls") or []
        if not tcalls:
            answer = msg.get("content") or ""
            stop_reason = choices[0].get("finish_reason") or "stop"
            finished = bool(answer) and stop_reason not in {"length", "content_filter"}
            break
        assistant = {"role": "assistant", "content": msg.get("content"), "tool_calls": tcalls}
        if msg.get("reasoning_content") is not None:
            assistant["reasoning_content"] = msg["reasoning_content"]
        messages.append(assistant)
        for call in tcalls:
            fn = call.get("function", {})
            name, raw = fn.get("name"), fn.get("arguments", "")
            entry = {"name": name, "arguments": None, "request_id": None, "pdf_pages": [], "error": None}
            try:
                args = json.loads(raw) if isinstance(raw, str) else raw
                if not isinstance(args, dict):
                    raise ValueError("arguments must be a JSON object")
                entry["arguments"] = args
                result = _backend_call(transport, backend, name, args, campaign_id)
                entry["request_id"] = result.get("request_id") if isinstance(result, dict) else None
                if name == "read_corebook_page" and isinstance(result, dict) and result.get("pdf_page"):
                    entry["pdf_pages"] = [result["pdf_page"]]
                elif name not in {"game_action", "campaign_action", "solo_action", "roll_dice", "skill_check"} and isinstance(result, dict):
                    pages = result.get("pages", [])
                    pages += result.get("results", [])
                    entry["pdf_pages"] = list(dict.fromkeys(r["pdf_page"] for r in pages if isinstance(r, dict) and r.get("pdf_page")))
                payload = result
            except Exception as exc:
                entry["error"] = str(exc)
                payload = {"error": str(exc)}
            calls.append(entry)
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": json.dumps(payload)})
            if entry["error"]:
                return {"model": MODEL, "question": question, "calls": calls, "answer": "", "campaign_context": campaign_context,
                        "tool_executed": any(c["request_id"] for c in calls), "finished": False, "stop_reason": "tool_error"}
    return {"model": MODEL, "question": question, "calls": calls, "answer": answer, "campaign_context": campaign_context,
            "tool_executed": any(c["request_id"] for c in calls), "finished": finished, "stop_reason": stop_reason}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sillytavern", default="http://127.0.0.1:8000")
    p.add_argument("--backend", default="http://127.0.0.1:8765")
    p.add_argument("--question", required=True)
    p.add_argument("--campaign-id")
    p.add_argument("--max-rounds", type=int, default=6, help="maximum provider/tool rounds (1-30; prevents unbounded loops)")
    p.add_argument("--output", type=Path)
    args = p.parse_args(argv)
    try:
        report = run_probe(args.question, args.sillytavern, args.backend, args.max_rounds, campaign_id=args.campaign_id)
        text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            os.chmod(args.output, 0o600)
        else:
            print(text, end="")
    except Exception as exc:
        p.exit(1, f"Probe failed: {exc}\n")


if __name__ == "__main__":
    main()
