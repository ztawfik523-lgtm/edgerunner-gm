"""OpenAI-compatible async LLM client, streaming sanitizer, and GM tag/plan parsers."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import os
import re
from typing import Any, AsyncIterator

import httpx

_GM_TAG_RE = re.compile(r"\[\[GM_STATE\s*:\s*(\{.*?\})\s*\]\]", re.S)
_GM_XML_RE = re.compile(r"<gm_ops>\s*(\{.*?\})\s*</gm_ops>", re.S | re.I)
_TRAILING_PARTIAL_TAG_RE = re.compile(r"(?:\[\[GM_STATE\b.*|<gm_ops\b.*)$", re.S | re.I)


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
    max_tokens: int = 1200
    timeout_s: float = 60.0
    mode: str = "two_pass"  # "two_pass" or "single_pass_tagged"
    retry_attempts: int = 2


class OpenAICompatibleLLM:
    """Async OpenAI-compatible /chat/completions client usable with local or cloud models."""

    def __init__(self, config: LLMConfig | None = None, *, transport: httpx.AsyncBaseTransport | None = None):
        self.config = config or LLMConfig()
        self.transport = transport
        self.last_usage: dict[str, int] | None = None

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _endpoint(self) -> str:
        base = self.config.base_url.rstrip("/")
        return f"{base}/chat/completions" if not base.endswith("/chat/completions") else base

    @staticmethod
    def _retry_delay(resp: httpx.Response, attempt: int) -> float:
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

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
        enable_thinking: bool | None = None,
    ) -> str:
        self.last_usage = None
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
        async with httpx.AsyncClient(timeout=self.config.timeout_s, transport=self.transport) as client:
            for attempt in range(max_attempts):
                resp = await client.post(self._endpoint(), headers=self._headers(), json=payload)
                if resp.status_code == 400 and ("response_format" in payload or "chat_template_kwargs" in payload):
                    payload.pop("response_format", None)
                    payload.pop("chat_template_kwargs", None)
                    resp = await client.post(self._endpoint(), headers=self._headers(), json=payload)
                if resp.status_code in {429, 503} and attempt < max_attempts - 1:
                    await asyncio.sleep(self._retry_delay(resp, attempt))
                    continue
                resp.raise_for_status()
                data = resp.json()
                break
        usage = data.get("usage")
        if isinstance(usage, dict):
            self.last_usage = {
                k: int(v)
                for k, v in usage.items()
                if k in {"prompt_tokens", "completion_tokens", "total_tokens"} and isinstance(v, (int, float))
            }
        choices = data.get("choices") or []
        if not choices:
            return ""
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
        self.last_usage = None
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
        async with httpx.AsyncClient(timeout=self.config.timeout_s, transport=self.transport) as client:
            for attempt in range(max_attempts):
                retry_delay: float | None = None
                stripped_kwargs = False
                while True:
                    async with client.stream("POST", self._endpoint(), headers=self._headers(), json=payload) as resp:
                        if (
                            resp.status_code == 400
                            and ("chat_template_kwargs" in payload or "stream_options" in payload)
                            and not stripped_kwargs
                        ):
                            payload.pop("chat_template_kwargs", None)
                            payload.pop("stream_options", None)
                            stripped_kwargs = True
                            continue
                        if resp.status_code in {429, 503} and attempt < max_attempts - 1:
                            retry_delay = self._retry_delay(resp, attempt)
                            break
                        resp.raise_for_status()
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
                            chunk_usage = chunk.get("usage")
                            if isinstance(chunk_usage, dict):
                                self.last_usage = {
                                    k: int(v)
                                    for k, v in chunk_usage.items()
                                    if k in {"prompt_tokens", "completion_tokens", "total_tokens"} and isinstance(v, (int, float))
                                }
                            choices = chunk.get("choices") or []
                            if not choices:
                                continue
                            delta = (choices[0].get("delta") or {}).get("content")
                            if isinstance(delta, str) and delta:
                                yield delta
                        return
                if retry_delay is not None:
                    await asyncio.sleep(retry_delay)


def strip_gm_tags(text: str) -> str:
    """Remove structured GM control tags so user-visible narrative stays clean."""
    cleaned = _GM_TAG_RE.sub("", text)
    cleaned = _GM_XML_RE.sub("", cleaned)
    return cleaned.strip()


class StreamSanitizer:
    """Incremental stream buffer that strips GM control tags and holds back partial trailing tags."""

    def __init__(self) -> None:
        self._chunks: list[str] = []
        self._emitted_len: int = 0

    def feed(self, delta: str) -> str:
        self._chunks.append(delta)
        joined = "".join(self._chunks)
        safe = _TRAILING_PARTIAL_TAG_RE.sub("", strip_gm_tags(joined))
        if len(safe) > self._emitted_len:
            new_piece = safe[self._emitted_len :]
            self._emitted_len = len(safe)
            return new_piece
        return ""

    def finalize(self) -> tuple[str, str]:
        raw_text = "".join(self._chunks)
        clean_text = strip_gm_tags(raw_text)
        trailing = clean_text[self._emitted_len :] if len(clean_text) > self._emitted_len else ""
        self._emitted_len = len(clean_text)
        return trailing, raw_text


def extract_gm_plan(raw_text: str) -> dict[str, Any]:
    """Extract structured GM plan/operations from JSON, [[GM_STATE:...]], or <gm_ops>...</gm_ops>."""
    if not isinstance(raw_text, str) or not raw_text.strip():
        return {}
    for pattern in (_GM_XML_RE, _GM_TAG_RE):
        match = pattern.search(raw_text)
        if match:
            try:
                parsed = json.loads(match.group(1))
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                pass
    stripped = raw_text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.S)
    candidate = fence.group(1) if fence else stripped
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end > start:
            try:
                parsed = json.loads(candidate[start : end + 1])
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
    return {}
