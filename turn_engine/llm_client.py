"""OpenAI-compatible async LLM client, streaming sanitizer, and GM tag/plan parsers."""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass
import json
import os
import re
from typing import Any, AsyncIterator

import httpx

_GM_TAG_RE = re.compile(r"\[\[GM_STATE\s*:\s*(\{.*?\})\s*\]\]", re.S | re.I)
_GM_XML_RE = re.compile(r"<gm_ops\b[^>]*>\s*(.*?)\s*</gm_ops>", re.S | re.I)
_THINK_XML_RE = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.S | re.I)
_TRAILING_PARTIAL_TAG_RE = re.compile(r"(?:\[\[GM_STATE\b.*|<gm_ops\b.*|<think\b.*)$", re.S | re.I)
_FENCED_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S | re.I)

_CLOSE_THINK_RE = re.compile(r"</think\s*>", re.S | re.I)
_CLOSE_GM_OPS_RE = re.compile(r"</gm_ops\s*>", re.S | re.I)
_GM_STATE_START_RE = re.compile(r"\[\[GM_STATE(?=[^a-z0-9_])", re.I)
_GM_STATE_OPEN_RE = re.compile(r"\[\[GM_STATE\s*:", re.I)

_TAG_PREFIXES = ("<think", "<gm_ops", "[[gm_state")
_OPEN_THINK_START_RE = re.compile(r"^<think(?=[^a-z0-9_])", re.I)
_OPEN_GM_OPS_START_RE = re.compile(r"^<gm_ops(?=[^a-z0-9_])", re.I)
_OPEN_GM_STATE_START_RE = re.compile(r"^\[\[gm_state(?=[^a-z0-9_])", re.I)
_EXACT_TAG_NAME_RE = re.compile(r"^(?:<think|<gm_ops|\[\[gm_state)$", re.I)

_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


@dataclass(slots=True)
class LLMConfig:
    """Model-agnostic connection settings for any OpenAI-compatible chat API."""

    base_url: str = os.environ.get("REDGM_LLM_URL", "http://127.0.0.1:11434/v1")
    model: str = os.environ.get("REDGM_LLM_MODEL", "llama3")
    api_key: str = os.environ.get("REDGM_LLM_API_KEY", "")
    temperature: float = 0.75
    top_p: float = 1.0
    presence_penalty: float = 0.0
    frequency_penalty: float = 0.0
    max_tokens: int = 2400
    timeout_s: float = 60.0
    mode: str = "two_pass"  # "two_pass" or "single_pass_tagged"
    retry_attempts: int = 2


def _extract_provider_error(payload: Any) -> str | None:
    """Extract a readable provider error string from an HTTP 200 error envelope, if present."""
    if not isinstance(payload, dict):
        return None
    err = payload.get("error")
    if not err:
        return None
    if isinstance(err, str):
        return err.strip() or "Unknown provider error"
    if isinstance(err, dict):
        for key in ("message", "error", "detail", "reason"):
            val = err.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return json.dumps(err)
    return str(err)


def _normalize_usage(raw_usage: Any) -> dict[str, int] | None:
    if not isinstance(raw_usage, dict):
        return None
    out = {
        k: int(v)
        for k, v in raw_usage.items()
        if k in {"prompt_tokens", "completion_tokens", "total_tokens"} and isinstance(v, (int, float))
    }
    return out or None


class OpenAICompatibleLLM:
    """Async OpenAI-compatible /chat/completions client usable with local or cloud models."""

    def __init__(self, config: LLMConfig | None = None, *, transport: httpx.AsyncBaseTransport | None = None):
        self.config = config or LLMConfig()
        self.transport = transport
        self.last_usage: dict[str, int] | None = None
        self.last_finish_reason: str | None = None
        self.last_truncated: bool = False
        self._call_meta_var: ContextVar[dict[str, Any] | None] = ContextVar("llm_call_meta", default=None)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _endpoint(self) -> str:
        base = self.config.base_url.rstrip("/")
        return f"{base}/chat/completions" if not base.endswith("/chat/completions") else base

    @staticmethod
    def _retry_delay(resp: httpx.Response | None, attempt: int) -> float:
        if resp is not None:
            ra = resp.headers.get("retry-after")
            if ra:
                try:
                    return max(0.5, min(10.0, float(ra)))
                except ValueError:
                    pass
        return 1.5 * (attempt + 1)

    def _sampling_extras(self) -> dict[str, Any]:
        extras: dict[str, Any] = {}
        top_p = float(getattr(self.config, "top_p", 1.0))
        if top_p < 0.999:
            extras["top_p"] = top_p
        pp = float(getattr(self.config, "presence_penalty", 0.0))
        if abs(pp) > 1e-6:
            extras["presence_penalty"] = pp
        fp = float(getattr(self.config, "frequency_penalty", 0.0))
        if abs(fp) > 1e-6:
            extras["frequency_penalty"] = fp
        return extras

    def _begin_call_meta(self) -> dict[str, Any]:
        self.last_usage = None
        self.last_finish_reason = None
        self.last_truncated = False
        meta: dict[str, Any] = {"usage": None, "finish_reason": None, "truncated": False}
        self._call_meta_var.set(meta)
        return meta

    def _record_usage(self, raw_usage: Any, meta: dict[str, Any]) -> None:
        usage = _normalize_usage(raw_usage)
        if usage is not None:
            meta["usage"] = usage
            self.last_usage = dict(usage)

    def _record_finish_reason(self, finish_reason: Any, meta: dict[str, Any]) -> None:
        if isinstance(finish_reason, str) and finish_reason:
            meta["finish_reason"] = finish_reason
            self.last_finish_reason = finish_reason
            if finish_reason == "length":
                meta["truncated"] = True
                self.last_truncated = True

    def pop_call_meta(self) -> dict[str, Any]:
        """Return and clear metadata (usage, finish_reason, truncated) for the most recent call in this context."""
        meta = self._call_meta_var.get()
        if meta is not None:
            self._call_meta_var.set(None)
            return {
                "usage": dict(meta["usage"]) if isinstance(meta.get("usage"), dict) else None,
                "finish_reason": meta.get("finish_reason"),
                "truncated": bool(meta.get("truncated", False)),
            }
        out = {
            "usage": dict(self.last_usage) if isinstance(self.last_usage, dict) else None,
            "finish_reason": self.last_finish_reason,
            "truncated": bool(self.last_truncated),
        }
        self.last_usage = None
        self.last_finish_reason = None
        self.last_truncated = False
        return out

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
        enable_thinking: bool | None = None,
    ) -> str:
        meta = self._begin_call_meta()
        effective_max = self.config.max_tokens if max_tokens is None else max_tokens
        if json_mode and max_tokens is None:
            # Reasoning models count thinking tokens against max_tokens; give structured JSON passes headroom.
            effective_max = max(int(effective_max), 4096)
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature if temperature is None else temperature,
            "max_tokens": effective_max,
            "stream": False,
            **self._sampling_extras(),
        }
        if enable_thinking is False:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        max_attempts = max(1, 1 + int(getattr(self.config, "retry_attempts", 2)))
        data: dict[str, Any] = {}
        async with httpx.AsyncClient(timeout=self.config.timeout_s, transport=self.transport) as client:
            for attempt in range(max_attempts):
                retry_delay: float | None = None
                try:
                    while True:
                        resp = await client.post(self._endpoint(), headers=self._headers(), json=payload)
                        if resp.status_code in {400, 422}:
                            if "chat_template_kwargs" in payload:
                                payload.pop("chat_template_kwargs", None)
                                continue
                            if "response_format" in payload:
                                payload.pop("response_format", None)
                                continue
                        if resp.status_code in _RETRYABLE_STATUS_CODES and attempt < max_attempts - 1:
                            retry_delay = self._retry_delay(resp, attempt)
                            break
                        resp.raise_for_status()
                        data = resp.json()
                        retry_delay = None
                        break
                except (httpx.TimeoutException, httpx.TransportError):
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(self._retry_delay(None, attempt))
                        continue
                    raise
                if retry_delay is not None:
                    await asyncio.sleep(retry_delay)
                    continue
                break

        err_msg = _extract_provider_error(data)
        if err_msg is not None:
            raise RuntimeError(f"LLM provider error: {err_msg}")
        self._record_usage(data.get("usage"), meta)
        choices = data.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            return ""
        self._record_finish_reason(choices[0].get("finish_reason"), meta)
        msg = choices[0].get("message") or {}
        return str(msg.get("content") or "")

    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        enable_thinking: bool | None = None,
    ) -> AsyncIterator[str]:
        meta = self._begin_call_meta()
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature if temperature is None else temperature,
            "max_tokens": self.config.max_tokens if max_tokens is None else max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
            **self._sampling_extras(),
        }
        if enable_thinking is False:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        max_attempts = max(1, 1 + int(getattr(self.config, "retry_attempts", 2)))
        emitted_any_token = False
        async with httpx.AsyncClient(timeout=self.config.timeout_s, transport=self.transport) as client:
            for attempt in range(max_attempts):
                retry_delay: float | None = None
                try:
                    while True:
                        async with client.stream("POST", self._endpoint(), headers=self._headers(), json=payload) as resp:
                            if resp.status_code in {400, 422}:
                                if "chat_template_kwargs" in payload:
                                    await resp.aread()
                                    payload.pop("chat_template_kwargs", None)
                                    continue
                                if "stream_options" in payload:
                                    await resp.aread()
                                    payload.pop("stream_options", None)
                                    continue
                            if resp.status_code in _RETRYABLE_STATUS_CODES and attempt < max_attempts - 1:
                                await resp.aread()
                                retry_delay = self._retry_delay(resp, attempt)
                                break
                            if resp.status_code >= 400:
                                await resp.aread()
                                resp.raise_for_status()

                            content_type = (resp.headers.get("content-type") or "").lower()
                            if "application/json" in content_type:
                                raw_body = await resp.aread()
                                data = json.loads(raw_body.decode("utf-8"))
                                err_msg = _extract_provider_error(data)
                                if err_msg is not None:
                                    raise RuntimeError(f"LLM provider error: {err_msg}")
                                self._record_usage(data.get("usage"), meta)
                                choices = data.get("choices") or []
                                if choices and isinstance(choices[0], dict):
                                    self._record_finish_reason(choices[0].get("finish_reason"), meta)
                                    msg = choices[0].get("message") or choices[0].get("delta") or {}
                                    content = msg.get("content") if isinstance(msg, dict) else None
                                    if isinstance(content, str) and content:
                                        emitted_any_token = True
                                        yield content
                                return

                            async for line in resp.aiter_lines():
                                if not line or not line.startswith("data:"):
                                    continue
                                body = line[5:].strip()
                                if body == "[DONE]":
                                    break
                                try:
                                    chunk = json.loads(body)
                                except json.JSONDecodeError:
                                    continue
                                err_msg = _extract_provider_error(chunk)
                                if err_msg is not None:
                                    raise RuntimeError(f"LLM provider error: {err_msg}")
                                self._record_usage(chunk.get("usage"), meta)
                                choices = chunk.get("choices") or []
                                if not choices or not isinstance(choices[0], dict):
                                    continue
                                self._record_finish_reason(choices[0].get("finish_reason"), meta)
                                delta = (choices[0].get("delta") or {}).get("content")
                                if isinstance(delta, str) and delta:
                                    emitted_any_token = True
                                    yield delta
                            return
                except (httpx.TimeoutException, httpx.TransportError):
                    if not emitted_any_token and attempt < max_attempts - 1:
                        await asyncio.sleep(self._retry_delay(None, attempt))
                        continue
                    raise
                if retry_delay is not None:
                    await asyncio.sleep(retry_delay)


def _scan_balanced_json_object(text: str, start: int) -> int | None:
    """Return exclusive end index of the balanced `{...}` object starting at `start`, or None if unclosed."""
    if start >= len(text) or text[start] != "{":
        return None
    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return idx + 1
    return None


def _find_gm_state_end(buf: str) -> int | None:
    """Given text immediately after `[[GM_STATE`, return exclusive end index of closing `]]`, or None if incomplete."""
    idx = 0
    length = len(buf)
    while idx < length and buf[idx].isspace():
        idx += 1
    if idx < length and buf[idx] == ":":
        idx += 1
        while idx < length and buf[idx].isspace():
            idx += 1
    if idx >= length:
        return None
    if buf[idx] == "{":
        obj_end = _scan_balanced_json_object(buf, idx)
        if obj_end is None:
            return None
        tail_idx = obj_end
        while tail_idx < length and buf[tail_idx].isspace():
            tail_idx += 1
        if tail_idx >= length or buf[tail_idx:] == "]":
            return None
        if buf.startswith("]]", tail_idx):
            return tail_idx + 2
        close_idx = buf.find("]]", tail_idx)
        return close_idx + 2 if close_idx != -1 else None
    close_idx = buf.find("]]", idx)
    return close_idx + 2 if close_idx != -1 else None


def _strip_think_blocks(text: str) -> str:
    """Remove all closed `<think>...</think>` blocks and any unclosed trailing `<think\\b...`."""
    cleaned = _THINK_XML_RE.sub("", text)
    cleaned = re.sub(r"<think\b.*$", "", cleaned, flags=re.S | re.I)
    return cleaned


def _strip_gm_state_blocks(text: str) -> str:
    """Remove all closed `[[GM_STATE:...]]` blocks (with nested-brace awareness) and unclosed trailing `[[GM_STATE\\b...`."""
    out: list[str] = []
    pos = 0
    while pos < len(text):
        m = _GM_STATE_START_RE.search(text, pos)
        if m is None:
            out.append(text[pos:])
            break
        out.append(text[pos : m.start()])
        end_rel = _find_gm_state_end(text[m.end() :])
        if end_rel is None:
            # Unclosed trailing [[GM_STATE... block: strip to end of text.
            break
        pos = m.end() + end_rel
    return "".join(out)


def strip_gm_tags(text: str) -> str:
    """Remove `<think>` reasoning blocks and structured GM control tags so user-visible narrative stays clean."""
    if not isinstance(text, str) or not text:
        return ""
    cleaned = _strip_think_blocks(text)
    cleaned = _GM_XML_RE.sub("", cleaned)
    cleaned = _strip_gm_state_blocks(cleaned)
    cleaned = _TRAILING_PARTIAL_TAG_RE.sub("", cleaned)
    return cleaned.strip()


class StreamSanitizer:
    """Incremental stateful stream buffer stripping `<think>` and GM control tags while holding back partial prefixes."""

    def __init__(self) -> None:
        self._chunks: list[str] = []
        self._buf: str = ""
        self._state: str = "TEXT"  # "TEXT" | "IN_THINK" | "IN_GM_OPS" | "IN_GM_STATE"
        self._open_tag_closed: bool = False
        self._has_emitted_content: bool = False

    def _emit_text(self, text: str, out: list[str]) -> None:
        if not text:
            return
        if not self._has_emitted_content:
            trimmed = text.lstrip()
            if not trimmed:
                return
            self._has_emitted_content = True
            out.append(trimmed)
            return
        out.append(text)

    @staticmethod
    def _find_tag_start(text: str) -> int:
        lt = text.find("<")
        lb = text.find("[")
        if lt == -1:
            return lb
        if lb == -1:
            return lt
        return min(lt, lb)

    def _drain_buffer(self, out: list[str]) -> None:
        while self._buf:
            if self._state == "TEXT":
                idx = self._find_tag_start(self._buf)
                if idx == -1:
                    self._emit_text(self._buf, out)
                    self._buf = ""
                    break
                if idx > 0:
                    self._emit_text(self._buf[:idx], out)
                    self._buf = self._buf[idx:]
                low = self._buf.lower()
                if _OPEN_THINK_START_RE.match(low):
                    self._state = "IN_THINK"
                    self._open_tag_closed = False
                    self._buf = self._buf[6:]
                    continue
                if _OPEN_GM_OPS_START_RE.match(low):
                    self._state = "IN_GM_OPS"
                    self._open_tag_closed = False
                    self._buf = self._buf[7:]
                    continue
                if _OPEN_GM_STATE_START_RE.match(low):
                    self._state = "IN_GM_STATE"
                    self._open_tag_closed = True
                    self._buf = self._buf[10:]
                    continue
                if any(prefix.startswith(low) for prefix in _TAG_PREFIXES):
                    break
                # Not a GM or think tag (and not a prefix of one): emit the leading char and advance.
                self._emit_text(self._buf[0], out)
                self._buf = self._buf[1:]
            elif self._state == "IN_THINK":
                if not self._open_tag_closed:
                    gt = self._buf.find(">")
                    if gt == -1:
                        self._buf = ""
                        break
                    self._open_tag_closed = True
                    self._buf = self._buf[gt + 1 :]
                m = _CLOSE_THINK_RE.search(self._buf)
                if m is not None:
                    self._state = "TEXT"
                    self._buf = self._buf[m.end() :]
                    continue
                last_lt = self._buf.rfind("<")
                self._buf = self._buf[last_lt:] if last_lt != -1 else ""
                break
            elif self._state == "IN_GM_OPS":
                if not self._open_tag_closed:
                    gt = self._buf.find(">")
                    if gt == -1:
                        self._buf = ""
                        break
                    self._open_tag_closed = True
                    self._buf = self._buf[gt + 1 :]
                m = _CLOSE_GM_OPS_RE.search(self._buf)
                if m is not None:
                    self._state = "TEXT"
                    self._buf = self._buf[m.end() :]
                    continue
                last_lt = self._buf.rfind("<")
                self._buf = self._buf[last_lt:] if last_lt != -1 else ""
                break
            elif self._state == "IN_GM_STATE":
                end_rel = _find_gm_state_end(self._buf)
                if end_rel is not None:
                    self._state = "TEXT"
                    self._buf = self._buf[end_rel:]
                    continue
                break

    def feed(self, delta: str) -> str:
        if not delta:
            return ""
        self._chunks.append(delta)
        self._buf += delta
        out: list[str] = []
        self._drain_buffer(out)
        return "".join(out)

    def finalize(self) -> tuple[str, str]:
        raw_text = "".join(self._chunks)
        out: list[str] = []
        if self._state == "TEXT" and self._buf:
            if not _EXACT_TAG_NAME_RE.match(self._buf):
                self._emit_text(self._buf, out)
        self._buf = ""
        self._state = "TEXT"
        return "".join(out), raw_text


def _extract_last_json_dict(text: str) -> dict[str, Any] | None:
    """Scan `text` using `JSONDecoder.raw_decode` at top-level `{` positions, returning the last valid dict."""
    if not text:
        return None
    decoder = json.JSONDecoder()
    last_dict: dict[str, Any] | None = None
    pos = 0
    while pos < len(text):
        brace = text.find("{", pos)
        if brace == -1:
            break
        try:
            obj, end_pos = decoder.raw_decode(text, brace)
        except json.JSONDecodeError:
            pos = brace + 1
            continue
        if isinstance(obj, dict):
            last_dict = obj
        pos = max(end_pos, brace + 1)
    return last_dict


def extract_gm_plan(raw_text: str) -> dict[str, Any] | None:
    """Extract structured GM plan dict from `<gm_ops>`, `[[GM_STATE:...]]`, fenced JSON, or balanced braces.

    Strips `<think>` blocks first. Returns `{}` when a valid empty JSON object was parsed,
    and returns `None` when no valid JSON dict could be extracted.
    """
    if not isinstance(raw_text, str) or not raw_text.strip():
        return None
    cleaned = _strip_think_blocks(raw_text)
    if not cleaned.strip():
        return None

    # 1. Check <gm_ops>...</gm_ops> blocks (last valid dict wins).
    for match in reversed(list(_GM_XML_RE.finditer(cleaned))):
        inner = match.group(1)
        parsed = _extract_last_json_dict(inner)
        if parsed is not None:
            return parsed

    # 2. Check [[GM_STATE:...]] blocks (last valid dict wins, supporting nested braces/arrays).
    decoder = json.JSONDecoder()
    for match in reversed(list(_GM_STATE_OPEN_RE.finditer(cleaned))):
        idx = match.end()
        while idx < len(cleaned) and cleaned[idx].isspace():
            idx += 1
        if idx < len(cleaned) and cleaned[idx] == "{":
            try:
                obj, end_pos = decoder.raw_decode(cleaned, idx)
                if isinstance(obj, dict) and re.match(r"\s*\]\]", cleaned[end_pos:]):
                    return obj
            except json.JSONDecodeError:
                pass
        close_idx = cleaned.find("]]", match.end())
        if close_idx != -1:
            parsed = _extract_last_json_dict(cleaned[match.end() : close_idx])
            if parsed is not None:
                return parsed

    # 3. Check fenced ```json / ``` blocks from the last block backwards.
    for match in reversed(list(_FENCED_BLOCK_RE.finditer(cleaned))):
        inner = match.group(1)
        parsed = _extract_last_json_dict(inner)
        if parsed is not None:
            return parsed

    # 4. Scan remaining text using balanced-brace raw_decode, preferring the last valid top-level dict.
    return _extract_last_json_dict(cleaned)
