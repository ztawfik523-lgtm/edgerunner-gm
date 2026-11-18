#!/usr/bin/env python3
"""Cyberpunk RED page-aware rules search, independent of the GM model.

Only the PDF owner runs ingestion. The PDF, index and user data remain local.
Search is deterministic and returns actual source pages, never LLM-generated rules.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
import hashlib
import hmac
import importlib.util
import json
import logging
import os
import re
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Any, Callable, Iterator

from index_lock import index_lock

DEFAULT_DB = Path(os.environ.get("REDKB_DB", Path.home() / ".local/share/cyberpunk-red-gm/rules.sqlite"))
STOP_WORDS = set("a an and are as at be by can could do does for from how i in into is it me of on or page pages please red rule rules show tell the this to under use using what when where with you cyberpunk corebook happens work my character book say".split())


def clean_text(text: str) -> str:
    """Normalize noisy PDF characters without throwing away paragraph boundaries."""
    return unicodedata.normalize("NFKC", text).replace("\u00ad", "").replace("\u200b", "").replace("\x00", "").strip()


def get_printed_page(text: str) -> int | None:
    """Read the actual running header; never invent printed page numbers."""
    lines = [s.strip() for s in text.splitlines() if s.strip()]
    # Some illustrated pages put an artist credit before their page header.
    # Only look near the top; never infer a missing printed number from the PDF index.
    for line in lines[:4]:
        if re.fullmatch(r"\d{1,3}", line):
            number = int(line)
            if 1 <= number <= 456:
                return number
    return None


def build_index(
    pdf_path: Path,
    db_path: Path,
    *,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
    source_filename: str | None = None,
) -> dict[str, Any]:
    """Build a fresh index atomically; incomplete runs do not corrupt the old DB."""
    import pymupdf as fitz

    def _emit(stage: str, percent: int, message: str, *, current: int = 0, total: int = 0) -> None:
        if progress_cb is not None:
            progress_cb({
                "stage": stage,
                "percent": max(0, min(100, int(percent))),
                "current": current,
                "total": total,
                "message": message,
            })

    pdf_path = pdf_path.expanduser().resolve()
    db_path = db_path.expanduser().resolve()
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    _emit("reading", 2, "Opening PDF file...")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=db_path.name + ".building-", dir=db_path.parent)
    os.close(fd)
    temp_path = Path(temporary)
    conn = sqlite3.connect(temp_path)
    try:
        conn.executescript("""
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE pages (
                id INTEGER PRIMARY KEY,
                pdf_page INTEGER NOT NULL UNIQUE,
                printed_page INTEGER,
                header TEXT NOT NULL,
                text TEXT NOT NULL,
                chars INTEGER NOT NULL
            );
            CREATE INDEX printed_page_idx ON pages(printed_page);
            CREATE TABLE passages (
                id INTEGER PRIMARY KEY,
                page_id INTEGER NOT NULL REFERENCES pages(id),
                start_word INTEGER NOT NULL,
                end_word INTEGER NOT NULL,
                text TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE page_fts USING fts5(
                text, header, content='pages', content_rowid='id',
                tokenize='porter unicode61'
            );
            CREATE VIRTUAL TABLE passage_fts USING fts5(
                text, content='passages', content_rowid='id',
                tokenize='porter unicode61'
            );
        """)
        # Hash precisely the immutable byte snapshot used for extraction.
        source_bytes = pdf_path.read_bytes()
        source_sha256 = hashlib.sha256(source_bytes).hexdigest()
        with fitz.open(stream=source_bytes, filetype="pdf") as pdf:
            count, populated, without_printed = len(pdf), 0, 0
            _emit("extracting", 5, f"Reading {count} pages from Corebook PDF...", current=0, total=count)
            for index, page in enumerate(pdf):
                text = clean_text(page.get_text("text", sort=False))
                # Keep the original extraction intact. Supplemental rows preserve
                # cell boundaries only where conservative table detection succeeds.
                from layout import extract_tables, table_text
                structured = table_text(extract_tables(page))
                if structured:
                    text += "\n\nSupplemental extracted table rows (verify against page):\n" + structured
                if text:
                    populated += 1
                printed = get_printed_page(text)
                if printed is None:
                    without_printed += 1
                lines = [v.strip() for v in text.splitlines() if v.strip()]
                header = next((v for v in lines[:6] if v != str(printed) and not v.startswith("BY ")), "")
                conn.execute(
                    "INSERT INTO pages(pdf_page, printed_page, header, text, chars) VALUES(?,?,?,?,?)",
                    (index + 1, printed, header[:180], text, len(text)),
                )
                page_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                words = text.split()
                for start in range(0, len(words), 75):
                    end = min(start + 150, len(words))
                    if start >= len(words):
                        break
                    conn.execute("INSERT INTO passages(page_id,start_word,end_word,text) VALUES(?,?,?,?)",
                                  (page_id, start, end, " ".join(words[start:end])))
                if count > 0 and ((index + 1) % 5 == 0 or index + 1 == count):
                    pct = 5 + int(((index + 1) / count) * 70)
                    _emit("extracting", pct, f"Reading page {index + 1} of {count}...", current=index + 1, total=count)
            _emit("structure", 78, "Organizing Corebook chapters and sections...", current=count, total=count)
            from knowledge import build_structure
            build_structure(conn, pdf)
        for key, value in {
            "schema_version": "2",
            "extraction_method": "plain_text+conservative_line_tables_v1",
            "passage_window_words": "150",
            "passage_stride_words": "75",
            "source_filename": (source_filename or pdf_path.name),
            "source_sha256": source_sha256,
            "pdf_page_count": str(count),
            "populated_pages": str(populated),
            "pages_without_printed_number": str(without_printed),
        }.items():
            conn.execute("INSERT INTO metadata(key,value) VALUES(?,?)", (key, value))
        _emit("library", 86, "Building searchable skills, roles, gear & cyberware library...", current=count, total=count)
        from library import build_library
        build_library(conn)
        _emit("fts", 94, "Building fast keyword search index...", current=count, total=count)
        conn.execute("INSERT INTO page_fts(page_fts) VALUES('rebuild')")
        conn.execute("INSERT INTO passage_fts(passage_fts) VALUES('rebuild')")
        conn.commit()
    except BaseException:
        conn.close()
        temp_path.unlink(missing_ok=True)
        raise
    conn.close()
    _emit("saving", 98, "Saving Corebook database...", current=count, total=count)
    with index_lock(db_path):
        os.replace(temp_path, db_path)
    info = inspect_index(db_path)
    _emit("done", 100, f"Corebook ready ({info.get('indexed_pages', count)} pages).", current=count, total=count)
    return info


@contextmanager
def _open(db_path: Path) -> Iterator[sqlite3.Connection]:
    db_path = db_path.expanduser().resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"Index missing: {db_path} (run index first)")
    conn = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN")
        yield conn
    finally:
        conn.close()


def inspect_index(db_path: Path) -> dict[str, Any]:
    with _open(db_path) as conn:
        meta = dict(conn.execute("SELECT key,value FROM metadata").fetchall())
        meta["indexed_pages"] = conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
        meta["fts_rows"] = conn.execute("SELECT COUNT(*) FROM page_fts").fetchone()[0]
        if meta.get("schema_version") == "2":
            meta["indexed_passages"] = conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0]
        meta["db_path"] = str(db_path.expanduser().resolve())
    return meta


def read_page(db_path: Path, page: int, numbering: str = "printed") -> dict[str, Any] | None:
    if page < 1 or numbering not in {"printed", "pdf"}:
        raise ValueError("Page must be positive; numbering must be 'printed' or 'pdf'")
    if page > 2**63 - 1:
        return None
    column = "printed_page" if numbering == "printed" else "pdf_page"
    with _open(db_path) as conn:
        result = conn.execute(f"SELECT pdf_page,printed_page,header,text FROM pages WHERE {column}=? LIMIT 1", (page,)).fetchone()
        meta = dict(conn.execute("SELECT key,value FROM metadata"))
    if result is None:
        return None
    value = dict(result)
    value["source_sha256"] = meta.get("source_sha256")
    value["citation"] = (f"Corebook printed p.{value['printed_page']} (PDF p.{value['pdf_page']})"
                         if value["printed_page"] else f"Corebook PDF p.{value['pdf_page']}")
    return value


def _terms(query: str) -> list[str]:
    words = re.findall(r"[\w]+", clean_text(query).lower())
    return list(dict.fromkeys(w for w in words if w not in STOP_WORDS and (len(w) > 1 or w.isdigit())))[:18]


def _expanded_vehicle_query(query: str) -> str | None:
    """Add a small collision vocabulary only for vehicle collision queries."""
    words = set(re.findall(r"[\w]+", clean_text(query).lower()))
    vehicle = words & {"vehicle", "vehicles", "car", "cars", "truck", "trucks"}
    collision = words & {"collision", "collisions", "crash", "crashes", "crashed",
                         "ram", "rams", "ramming", "impact", "impacts"}
    if not vehicle or not collision:
        return None
    # Keep expansion bounded, while retaining the complete original query.
    return query + " vehicle car truck collision crash ramming impact"


def _excerpt(text: str, terms: list[str], max_length: int = 1000) -> str:
    if len(text) <= max_length:
        return text
    flat = re.sub(r"\s+", " ", text)
    lower = flat.lower()
    first = min((lower.find(w) for w in terms if lower.find(w) >= 0), default=0)
    start = max(0, first - 120)
    end = min(len(flat), start + max_length)
    return ("…" if start else "") + flat[start:end] + ("…" if end < len(flat) else "")


def search_pages(db_path: Path, query: str, limit: int = 5, *, lexical_only: bool = False) -> list[dict[str, Any]]:
    """Exact pages bypass search; otherwise rank passages lexically or with local hybrid RRF."""
    limit = max(1, min(int(limit), 20))
    page_match = re.search(r"\b(?:(pdf)\s+|printed\s+)?(?:page|pg\.?|p\.)\s*(\d+)\b", query, re.I)
    if page_match:
        numbering = "pdf" if page_match.group(1) and page_match.group(1).lower() == "pdf" else "printed"
        number = int(page_match.group(2))
        if number < 1:
            return []
        result = read_page(db_path, number, numbering)
        if result is None:
            return []
        result["excerpt"] = _excerpt(result["text"], _terms(query))
        result["citation"] = (f"Corebook printed p.{result['printed_page']} (PDF p.{result['pdf_page']})"
                              if result["printed_page"] else f"Corebook PDF p.{result['pdf_page']}")
        return [result]
    expanded_query = _expanded_vehicle_query(query)
    retrieval_query = expanded_query or query
    terms = _terms(retrieval_query)
    if not terms:
        return []
    quoted = ['"' + t.replace('"', '""') + '"' for t in terms]
    with _open(db_path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
        if "passages" not in tables or "passage_fts" not in tables:
            raise ValueError("This index predates passage search; rebuild the index with the current version")
        meta = dict(conn.execute("SELECT key,value FROM metadata"))
        rows = conn.execute(
            """SELECT ps.id,p.pdf_page,p.printed_page,p.header,ps.text,ps.start_word,ps.end_word,
               bm25(passage_fts) AS score
               FROM passage_fts JOIN passages ps ON ps.id=passage_fts.rowid
               JOIN pages p ON p.id=ps.page_id
                WHERE passage_fts MATCH ? ORDER BY score,p.pdf_page,ps.start_word LIMIT 100""",
            (" OR ".join(quoted),),
        ).fetchall()
        from semantic import dense_candidates
        dense = [] if lexical_only else dense_candidates(conn, retrieval_query, 100)
        method = "hybrid_rrf" if dense else "passage_bm25"
        if expanded_query:
            method += "+expanded"
        if dense:
            scores: dict[int, float] = {}
            for ranking in ([int(r["id"]) for r in rows], [pid for pid, _ in dense]):
                for rank, pid in enumerate(ranking, 1):
                    scores[pid] = scores.get(pid, 0.0) + 1.0 / (60 + rank)
            ids = list(scores)
            rows = conn.execute(
                f"""SELECT ps.id,p.pdf_page,p.printed_page,p.header,ps.text,ps.start_word,ps.end_word
                    FROM passages ps JOIN pages p ON p.id=ps.page_id
                    WHERE ps.id IN ({','.join('?' for _ in ids)})""", ids).fetchall()
            rows = sorted(rows, key=lambda row: (-scores[row["id"]], row["pdf_page"], row["start_word"]))
        reranker_model = meta.get("reranker_model")
        if reranker_model and not lexical_only and rows:
            from reranker import rank_passages
            head, tail = rows[:30], rows[30:]
            rows = rank_passages(retrieval_query, head) + list(tail)
            method += "+rerank"
    selected = []
    seen_pages = set()
    for r in rows:
        if r["pdf_page"] in seen_pages:
            continue
        seen_pages.add(r["pdf_page"])
        selected.append(r)
        if len(selected) >= limit:
            break
    return [
        {
            "pdf_page": r["pdf_page"],
            "printed_page": r["printed_page"],
            "header": r["header"],
            "excerpt": r["text"],
            "passage_start_word": r["start_word"],
            "passage_end_word": r["end_word"],
            "source_sha256": meta.get("source_sha256"),
            "retrieval_method": method,
            "citation": f"Corebook printed p.{r['printed_page']} (PDF p.{r['pdf_page']})" if r["printed_page"] else f"Corebook PDF p.{r['pdf_page']}",
        }
        for r in selected
    ]


def find_phrase(db_path: Path, phrase: str, limit: int = 10) -> list[dict[str, Any]]:
    phrase = re.sub(r"\s+", " ", clean_text(phrase).lower()).strip()
    if len(phrase) < 3:
        raise ValueError("Use a phrase of at least three characters")
    matches = []
    with _open(db_path) as conn:
        meta = dict(conn.execute("SELECT key,value FROM metadata"))
        for row in conn.execute("SELECT pdf_page,printed_page,header,text FROM pages ORDER BY pdf_page"):
            if phrase in re.sub(r"\s+", " ", row["text"].lower()):
                matches.append({"pdf_page": row["pdf_page"], "printed_page": row["printed_page"],
                                "header": row["header"], "excerpt": _excerpt(row["text"], [phrase]),
                                "source_sha256": meta.get("source_sha256"),
                                "citation": f"Corebook printed p.{row['printed_page']} (PDF p.{row['pdf_page']})" if row["printed_page"] else f"Corebook PDF p.{row['pdf_page']}"})
                if len(matches) >= min(max(int(limit), 1), 100):
                    break
    return matches


def evaluate(db_path: Path, casefile: Path) -> dict[str, Any]:
    cases = json.loads(casefile.read_text(encoding="utf-8"))
    if not isinstance(cases, list):
        raise ValueError("Evaluation JSON must be a list")
    outcomes = []
    for case in cases:
        results = search_pages(db_path, case["query"], case.get("top_k", 5))
        actual = [r.get("printed_page") for r in results]
        expected = case["expected_printed_pages"]
        passed = any(p in actual for p in expected)
        outcomes.append({"query": case["query"], "expected": expected, "actual": actual, "passed": passed})
    passed = sum(row["passed"] for row in outcomes)
    return {"total": len(outcomes), "passed": passed, "recall_at_k": round(passed / len(outcomes), 4) if outcomes else 0, "cases": outcomes}


def _detect_lan_ips() -> list[str]:
    """Return likely LAN IPv4 addresses for sharing local co-op links without external traffic."""
    found: list[str] = []
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("10.255.255.255", 1))
            ip = sock.getsockname()[0]
            if ip and not ip.startswith("127."):
                found.append(ip)
        finally:
            sock.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and ip not in found:
                found.append(ip)
    except OSError:
        pass
    return found


class _CoopHub:
    """In-memory per-campaign presence, per-channel turn locks, and SSE fanout for LAN co-op play."""

    def __init__(self, ttl_s: float = 45.0):
        self.ttl_s = ttl_s
        self.subscribers: dict[str, set[asyncio.Queue]] = {}
        self.presence: dict[str, dict[str, dict[str, Any]]] = {}
        self.active_turns: dict[tuple[str, str], dict[str, Any]] = {}
        self.sync_seq: dict[str, int] = {}

    @staticmethod
    def _norm_chan(channel_id: str | None) -> str:
        clean = str(channel_id or "main").strip()
        return clean[:80] if clean else "main"

    def current_seq(self, campaign_id: str) -> int:
        return int(self.sync_seq.get(campaign_id, 0))

    def bump_seq(self, campaign_id: str) -> int:
        nxt = int(self.sync_seq.get(campaign_id, 0)) + 1
        self.sync_seq[campaign_id] = nxt
        return nxt

    def _prune(self, campaign_id: str) -> None:
        cutoff = time.time() - self.ttl_s
        members = self.presence.get(campaign_id)
        if not members:
            return
        stale = [cid for cid, entry in members.items() if entry.get("ts", 0.0) < cutoff]
        for cid in stale:
            del members[cid]

    def roster(self, campaign_id: str) -> list[dict[str, Any]]:
        self._prune(campaign_id)
        members = list(self.presence.get(campaign_id, {}).values())
        members.sort(key=lambda m: (not bool(m.get("is_host")), str(m.get("player_name") or "").casefold(), str(m.get("client_id") or "")))
        return [{k: v for k, v in m.items() if k != "ts"} for m in members]

    def active_turn_for(self, campaign_id: str, channel_id: str = "main") -> dict[str, Any] | None:
        chan = self._norm_chan(channel_id)
        now = time.time()
        existing = self.active_turns.get((campaign_id, chan))
        if existing and now - float(existing.get("started_at", 0.0)) < 180.0:
            return existing
        if existing:
            self.active_turns.pop((campaign_id, chan), None)
        return None

    def all_active_turns(self, campaign_id: str) -> dict[str, dict[str, Any]]:
        now = time.time()
        out: dict[str, dict[str, Any]] = {}
        stale_keys: list[tuple[str, str]] = []
        for (cid, chan), info in self.active_turns.items():
            if cid != campaign_id:
                continue
            if now - float(info.get("started_at", 0.0)) < 180.0:
                out[chan] = info
            else:
                stale_keys.append((cid, chan))
        for k in stale_keys:
            self.active_turns.pop(k, None)
        return out

    def publish(self, campaign_id: str, event: str, data: dict[str, Any]) -> None:
        payload_data = dict(data)
        if event == "sync" and "sync_seq" not in payload_data:
            payload_data["sync_seq"] = self.bump_seq(campaign_id)
        queues = list(self.subscribers.get(campaign_id) or ())
        for q in queues:
            try:
                q.put_nowait({"event": event, "data": payload_data})
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                    q.put_nowait({"event": event, "data": payload_data})
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

    def update_presence(
        self,
        campaign_id: str,
        *,
        client_id: str,
        player_name: str,
        character_id: str | None = None,
        is_host: bool = False,
    ) -> list[dict[str, Any]]:
        self._prune(campaign_id)
        bucket = self.presence.setdefault(campaign_id, {})
        bucket[client_id] = {
            "client_id": client_id,
            "player_name": player_name[:40] or "Player",
            "character_id": character_id or None,
            "is_host": bool(is_host),
            "ts": time.time(),
        }
        roster = self.roster(campaign_id)
        turns = self.all_active_turns(campaign_id)
        self.publish(
            campaign_id,
            "presence",
            {
                "campaign_id": campaign_id,
                "players": roster,
                "active_turn": turns.get("main") or next(iter(turns.values()), None),
                "active_turns": turns,
                "sync_seq": self.current_seq(campaign_id),
            },
        )
        return roster

    def acquire_turn(self, campaign_id: str, *, client_id: str, player_name: str, channel_id: str = "main") -> dict[str, Any] | None:
        chan = self._norm_chan(channel_id)
        existing = self.active_turn_for(campaign_id, chan)
        if existing and existing.get("client_id") != client_id:
            return existing
        info = {"client_id": client_id, "player_name": player_name or "Player", "channel_id": chan, "started_at": time.time()}
        self.active_turns[(campaign_id, chan)] = info
        turns = self.all_active_turns(campaign_id)
        self.publish(
            campaign_id,
            "turn_started",
            {
                "campaign_id": campaign_id,
                "channel_id": chan,
                "active_turn": info,
                "active_turns": turns,
            },
        )
        return None

    def release_turn(self, campaign_id: str, client_id: str, channel_id: str = "main") -> None:
        chan = self._norm_chan(channel_id)
        existing = self.active_turns.get((campaign_id, chan))
        if existing and existing.get("client_id") == client_id:
            del self.active_turns[(campaign_id, chan)]
        turns = self.all_active_turns(campaign_id)
        self.publish(
            campaign_id,
            "turn_finished",
            {
                "campaign_id": campaign_id,
                "channel_id": chan,
                "active_turn": turns.get(chan) or next(iter(turns.values()), None),
                "active_turns": turns,
                "sync_seq": self.current_seq(campaign_id),
            },
        )


def make_api(
    db_path: Path,
    allowed_origins: tuple[str, ...] = (),
    campaign_path=None,
    llm=None,
    settings_path: Path | None = None,
    ui_dist: Path | None = None,
    server_host: str = "127.0.0.1",
    server_port: int = 8765,
    room_pin: str = "",
    allow_server_control: bool = False,
):
    """Serve local rules retrieval and mutable gameplay operations."""
    global Request  # FastAPI resolves postponed annotations in module globals.
    from fastapi import FastAPI, HTTPException, Query, Request

    app = FastAPI(title="Cyberpunk RED Knowledge Engine", version="0.1")

    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles

    async def unavailable(request, exc):
        request_id = uuid.uuid4().hex
        logging.getLogger("uvicorn.error").warning("corebook_unavailable request_id=%s error_type=%s", request_id, type(exc).__name__)
        return JSONResponse(status_code=503, content={"detail": "Corebook retrieval unavailable. Check the local index, embedding dependencies and backend logs.", "request_id": request_id})

    for error_type in (OSError, sqlite3.Error, RuntimeError, ValueError):
        app.add_exception_handler(error_type, unavailable)

    def audit(tool: str, results: list[dict[str, Any]]) -> str:
        request_id = uuid.uuid4().hex
        logging.getLogger("uvicorn.error").info("corebook_tool %s", json.dumps({
            "request_id": request_id, "tool": tool,
            "pdf_pages": [row["pdf_page"] for row in results],
            "source_sha256": results[0].get("source_sha256") if results else None,
        }))
        return request_id

    def resolved_settings_path() -> Path:
        if settings_path is not None:
            return Path(settings_path)
        from turnloop import default_settings_path
        return default_settings_path()

    from auth import AuthError, AuthManager, AuthRateLimitError
    from turnloop import (
        DEFAULT_PROMPT_TEMPLATES,
        load_llm_settings,
        load_prompt_settings,
        load_server_settings,
        masked_llm_settings,
        save_llm_settings,
        save_prompt_settings,
        save_server_settings,
    )

    auth = AuthManager(resolved_settings_path(), room_pin=room_pin or os.environ.get("REDGM_ROOM_PIN", ""))
    resolved_pin = auth.room_pin
    dynamic_origins: set[str] = set(allowed_origins)
    dynamic_origins.update(load_server_settings(resolved_settings_path()).get("allowed_origins") or [])

    if dynamic_origins:
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=sorted(dynamic_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Accept", "Authorization", "Content-Type", "X-RedGM-Client-Id", "X-RedGM-Pin", "X-RedGM-Token"],
        )

    coop = _CoopHub()

    # Constructing GameplayService initializes persistent storage, so defer it
    # until an operation is actually requested.
    service = None
    service_lock = threading.Lock()
    def gameplay_service():
        nonlocal service
        from campaign import DEFAULT_DB
        path = DEFAULT_DB if campaign_path is None else Path(campaign_path)
        if path.expanduser().resolve() == Path(db_path).expanduser().resolve():
            raise ValueError("Campaign database must be separate from the rules index")
        with service_lock:
            if service is None:
                from gameplay import GameplayService
                service = GameplayService(path, db_path)
            return service

    def _extract_token(request: Request) -> str | None:
        hdr = (request.headers.get("x-redgm-token") or "").strip()
        if hdr:
            return hdr
        auth_hdr = (request.headers.get("authorization") or "").strip()
        if auth_hdr.lower().startswith("bearer "):
            return auth_hdr[7:].strip()
        cookie_tok = (request.cookies.get("redgm_token") or "").strip()
        if cookie_tok:
            return cookie_tok
        qp_tok = (request.query_params.get("token") or "").strip()
        return qp_tok or None

    def _session(request: Request) -> dict[str, Any]:
        pin = (request.headers.get("x-redgm-pin") or request.query_params.get("pin") or "").strip()
        return auth.resolve_session(_extract_token(request), pin=pin)

    def _current_allowed_origins() -> set[str]:
        origins = set(dynamic_origins)
        origins.update(load_server_settings(resolved_settings_path()).get("allowed_origins") or [])
        return origins

    def require_player(request: Request, request_id: str):
        sess = _session(request)
        if not auth.has_account_auth():
            return None
        if sess["authenticated"]:
            return None
        return JSONResponse(status_code=401, content={"detail": "Sign in required", "auth_required": True, "request_id": request_id})

    def require_admin(request: Request, request_id: str):
        sess = _session(request)
        if sess["role"] in {"open", "admin"}:
            return None
        if sess["pin_only_mode"] and sess["authenticated"] and not auth.is_admin_configured():
            return None
        if not sess["authenticated"]:
            if sess["pin_only_mode"]:
                return JSONResponse(status_code=401, content={"detail": "Room PIN required", "pin_required": True, "request_id": request_id})
            return JSONResponse(status_code=401, content={"detail": "Sign in required", "auth_required": True, "request_id": request_id})
        return JSONResponse(status_code=403, content={"detail": "Admin privileges required", "admin_required": True, "request_id": request_id})

    def check_mutable_origin(request: Request, request_id: str, *, require_json: bool = True, min_role: str = "user"):
        origin = request.headers.get("origin")
        sec_fetch_site = request.headers.get("sec-fetch-site", "").lower()
        host = request.headers.get("host")
        same_origin = bool(origin and host and origin == f"{request.url.scheme}://{host}")
        origins_now = _current_allowed_origins()
        if sec_fetch_site == "cross-site" and origin not in origins_now:
            return JSONResponse(status_code=403, content={"detail": "Cross-site game requests are forbidden", "request_id": request_id})
        if origin is not None and origin not in origins_now and not same_origin:
            return JSONResponse(status_code=403, content={"detail": "Origin is not allowed", "request_id": request_id})
        sess = _session(request)
        if sess["role"] != "open":
            if not sess["authenticated"]:
                if sess["pin_only_mode"]:
                    return JSONResponse(status_code=401, content={"detail": "Room PIN required", "pin_required": True, "request_id": request_id})
                return JSONResponse(status_code=401, content={"detail": "Sign in required", "auth_required": True, "request_id": request_id})
            if min_role == "admin" and sess["role"] != "admin":
                if not (sess["pin_only_mode"] and not auth.is_admin_configured()):
                    return JSONResponse(status_code=403, content={"detail": "Admin privileges required", "admin_required": True, "request_id": request_id})
        if require_json and request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            return JSONResponse(status_code=415, content={"detail": "Content-Type must be application/json", "request_id": request_id})
        return None

    def _in_docker() -> bool:
        return bool(os.environ.get("REDGM_MANAGED_BY_DOCKER")) or Path("/.dockerenv").exists()

    @app.get("/v1/auth/status")
    def auth_status(request: Request):
        request_id = uuid.uuid4().hex
        llm_cfg = load_llm_settings(resolved_settings_path())
        return {
            **_session(request),
            "require_character_to_speak": bool(llm_cfg.get("require_character_to_speak", True)),
            "request_id": request_id,
        }

    @app.post("/v1/auth/setup")
    async def auth_setup(request: Request):
        request_id = uuid.uuid4().hex
        origin = request.headers.get("origin")
        sec_fetch_site = request.headers.get("sec-fetch-site", "").lower()
        host = request.headers.get("host")
        same_origin = bool(origin and host and origin == f"{request.url.scheme}://{host}")
        origins_now = _current_allowed_origins()
        if sec_fetch_site == "cross-site" and origin not in origins_now:
            return JSONResponse(status_code=403, content={"detail": "Cross-site requests are forbidden", "request_id": request_id})
        if origin is not None and origin not in origins_now and not same_origin:
            return JSONResponse(status_code=403, content={"detail": "Origin is not allowed", "request_id": request_id})
        if not auth.can_bootstrap():
            return JSONResponse(status_code=403, content={"detail": "Admin is already configured; sign in as Admin instead.", "request_id": request_id})
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("Request body must be an object")
            res = await asyncio.to_thread(
                lambda: auth.setup_initial(
                    admin_username=str(body.get("admin_username") or "admin"),
                    admin_password=str(body.get("admin_password") or ""),
                    user_username=str(body.get("user_username") or ""),
                    user_password=str(body.get("user_password") or ""),
                    user_passcode=str(body.get("user_passcode") or ""),
                    allow_guest_users=bool(body.get("allow_guest_users", False)),
                    allow_self_signup=bool(body.get("allow_self_signup", True)),
                )
            )
            resp = JSONResponse(content={**res, "request_id": request_id})
            resp.set_cookie("redgm_token", res["token"], max_age=res["expires_in"], httponly=True, samesite="lax")
            return resp
        except (AuthError, TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.post("/v1/auth/login")
    async def auth_login(request: Request):
        request_id = uuid.uuid4().hex
        origin = request.headers.get("origin")
        sec_fetch_site = request.headers.get("sec-fetch-site", "").lower()
        host = request.headers.get("host")
        same_origin = bool(origin and host and origin == f"{request.url.scheme}://{host}")
        origins_now = _current_allowed_origins()
        if sec_fetch_site == "cross-site" and origin not in origins_now:
            return JSONResponse(status_code=403, content={"detail": "Cross-site requests are forbidden", "request_id": request_id})
        if origin is not None and origin not in origins_now and not same_origin:
            return JSONResponse(status_code=403, content={"detail": "Origin is not allowed", "request_id": request_id})
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("Request body must be an object")
            bucket = request.client.host if request.client else "local"
            res = auth.authenticate(
                mode=str(body.get("mode") or "auto"),
                username=str(body.get("username") or ""),
                password=str(body.get("password") or body.get("passcode") or body.get("pin") or ""),
                bucket=bucket,
            )
            resp = JSONResponse(content={**res, "request_id": request_id})
            resp.set_cookie("redgm_token", res["token"], max_age=res["expires_in"], httponly=True, samesite="lax")
            return resp
        except AuthRateLimitError as exc:
            return JSONResponse(status_code=429, content={"detail": str(exc), "request_id": request_id})
        except (AuthError, TypeError, ValueError) as exc:
            return JSONResponse(status_code=401, content={"detail": str(exc), "request_id": request_id})

    @app.post("/v1/auth/register")
    async def auth_register(request: Request):
        request_id = uuid.uuid4().hex
        origin = request.headers.get("origin")
        sec_fetch_site = request.headers.get("sec-fetch-site", "").lower()
        host = request.headers.get("host")
        same_origin = bool(origin and host and origin == f"{request.url.scheme}://{host}")
        origins_now = _current_allowed_origins()
        if sec_fetch_site == "cross-site" and origin not in origins_now:
            return JSONResponse(status_code=403, content={"detail": "Cross-site requests are forbidden", "request_id": request_id})
        if origin is not None and origin not in origins_now and not same_origin:
            return JSONResponse(status_code=403, content={"detail": "Origin is not allowed", "request_id": request_id})
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("Request body must be an object")
            bucket = request.client.host if request.client else "local"
            res = await asyncio.to_thread(
                lambda: auth.register_user(
                    username=str(body.get("username") or ""),
                    password=str(body.get("password") or ""),
                    bucket=bucket,
                )
            )
            resp = JSONResponse(content={**res, "request_id": request_id})
            resp.set_cookie("redgm_token", res["token"], max_age=res["expires_in"], httponly=True, samesite="lax")
            return resp
        except AuthRateLimitError as exc:
            return JSONResponse(status_code=429, content={"detail": str(exc), "request_id": request_id})
        except (AuthError, TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.post("/v1/auth/logout")
    def auth_logout():
        request_id = uuid.uuid4().hex
        resp = JSONResponse(content={"ok": True, "request_id": request_id})
        resp.delete_cookie("redgm_token")
        return resp

    @app.post("/v1/auth/me")
    async def auth_update_me(request: Request):
        request_id = uuid.uuid4().hex
        blocked = check_mutable_origin(request, request_id, require_json=True, min_role="user")
        if blocked is not None:
            return blocked
        sess = _session(request)
        cur_uname = str(sess.get("username") or "").strip()
        if not cur_uname or not sess.get("authenticated") or sess.get("pin_only_mode"):
            return JSONResponse(
                status_code=403,
                content={"detail": "Sign in with a named account to update username or password.", "request_id": request_id},
            )
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("Request body must be an object")
            res = await asyncio.to_thread(
                lambda: auth.update_self_account(
                    cur_uname,
                    current_password=str(body.get("current_password") or ""),
                    new_username=body.get("new_username"),
                    new_password=body.get("new_password"),
                )
            )
            if res["username"].lower() != cur_uname.lower() or res["username"] != cur_uname:
                affected_camps = await asyncio.to_thread(
                    lambda: gameplay_service().store.rename_owner_username(cur_uname, res["username"])
                )
                for cid in affected_camps:
                    coop.publish(cid, "sync", {"campaign_id": cid, "kind": "campaign"})
            resp = JSONResponse(content={**res, "request_id": request_id})
            resp.set_cookie("redgm_token", res["token"], max_age=res["expires_in"], httponly=True, samesite="lax")
            return resp
        except (AuthError, TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.get("/v1/auth/accounts")
    def auth_list_accounts(request: Request):
        request_id = uuid.uuid4().hex
        blocked = require_admin(request, request_id)
        if blocked is not None:
            return blocked
        return {**auth.list_accounts(), "request_id": request_id}

    @app.post("/v1/auth/accounts")
    async def auth_update_accounts(request: Request):
        request_id = uuid.uuid4().hex
        blocked = check_mutable_origin(request, request_id, require_json=True, min_role="admin")
        if blocked is not None:
            return blocked
        try:
            body = await request.json()
            res = await asyncio.to_thread(lambda: auth.update_access(body))
            return {**res, "request_id": request_id}
        except (AuthError, TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.delete("/v1/auth/accounts/{username}")
    async def auth_delete_account(request: Request, username: str):
        request_id = uuid.uuid4().hex
        blocked = check_mutable_origin(request, request_id, require_json=False, min_role="admin")
        if blocked is not None:
            return blocked
        try:
            res = await asyncio.to_thread(lambda: auth.delete_account(username))
            return {**res, "request_id": request_id}
        except (AuthError, TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    def _effective_role(request: Request, sess: dict[str, Any]) -> str:
        view_override = (request.headers.get("x-redgm-view-role") or "").strip().lower()
        if sess.get("role") in {"admin", "open"} and view_override == "user":
            return "user"
        return str(sess.get("role") or "anon")

    @app.post("/v1/game")
    async def game(request: Request):
        request_id = uuid.uuid4().hex
        try:
            blocked = check_mutable_origin(request, request_id, require_json=True)
            if blocked is not None:
                return blocked
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get("action"), str) or not isinstance(body.get("arguments"), dict):
                raise ValueError("Body must contain string action and object arguments")
            action_name = body["action"]
            args_payload = dict(body["arguments"])
            auto_revision = bool(body.get("auto_revision", False))
            sess = _session(request)
            eff_role = _effective_role(request, sess)
            uname = str(sess.get("username") or "").strip()

            admin_campaign_actions = {
                "create_campaign",
                "update_campaign",
                "start_session",
                "undo_campaign",
                "delete_campaign",
                "set_primary_campaign",
            }
            if action_name in admin_campaign_actions and eff_role == "user" and not sess.get("pin_only_mode"):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Admin permission required to create or modify campaigns and sessions.", "request_id": request_id},
                )

            # Automatically stamp owner_username when a signed-in user creates a character
            if uname and action_name == "create_character":
                det = dict(args_payload.get("detail") or {}) if isinstance(args_payload.get("detail"), dict) else {}
                if not det.get("owner_username"):
                    det["owner_username"] = uname
                args_payload["detail"] = det
            elif uname and action_name == "create_player_character":
                inner_args = dict(args_payload.get("arguments") or {}) if isinstance(args_payload.get("arguments"), dict) else {}
                if not inner_args.get("owner_username"):
                    inner_args["owner_username"] = uname
                args_payload["arguments"] = inner_args

            # Enforce character ownership for normal users on character-mutating actions
            char_mutating_actions = {
                "update_character",
                "update_character_profile",
                "undo",
                "skill_check",
                "role_action",
                "gear_action",
                "health_action",
                "economy_action",
            }
            if eff_role == "user" and uname and action_name in char_mutating_actions:
                target_char_id = args_payload.get("character_id")
                if isinstance(target_char_id, str) and target_char_id:
                    existing_char = await asyncio.to_thread(lambda: gameplay_service().store.get_character(target_char_id))
                    if existing_char:
                        owner = str((existing_char.get("detail") or {}).get("owner_username") or "").strip()
                        if owner and owner.lower() != uname.lower():
                            return JSONResponse(
                                status_code=403,
                                content={
                                    "detail": f"Character '{existing_char.get('name')}' belongs to {owner}. Only its owner or Admin can modify it.",
                                    "request_id": request_id,
                                },
                            )

            read_only_actions = {
                "list_campaigns",
                "get_campaign",
                "campaign_context",
                "campaign_history",
                "get_character",
                "list_characters",
                "history",
                "solo_context",
                "solo_history",
            }

            def _exec_with_optional_auto_rev(camp_id: str | None):
                svc = gameplay_service()
                if auto_revision:
                    if action_name in {"update_character", "update_character_profile", "undo", "skill_check"}:
                        cid = args_payload.get("character_id")
                        if isinstance(cid, str) and cid:
                            cur_c = svc.store.get_character(cid)
                            if cur_c is not None:
                                args_payload["expected_revision"] = cur_c["revision"]
                    elif action_name in {"update_campaign", "attach_character", "start_session", "undo_campaign"}:
                        target_camp = camp_id or args_payload.get("campaign_id")
                        if isinstance(target_camp, str) and target_camp:
                            cur_camp = svc.memory.get_campaign(target_camp)
                            if cur_camp is not None:
                                args_payload["expected_revision"] = cur_camp["revision"]
                    elif camp_id and "expected_revision" in args_payload:
                        try:
                            cur_solo = svc.solo.context(camp_id)
                            args_payload["expected_revision"] = cur_solo["revision"]
                        except Exception:
                            pass
                before_session_num: int | None = None
                if action_name == "start_session":
                    target_camp_pre = camp_id or args_payload.get("campaign_id")
                    if isinstance(target_camp_pre, str) and target_camp_pre:
                        cur_pre = svc.memory.get_campaign(target_camp_pre)
                        if cur_pre is not None:
                            before_session_num = int(cur_pre.get("session_number") or 0)
                res_out = (
                    svc.execute(action_name, args_payload, campaign_id=camp_id)
                    if camp_id is not None
                    else svc.execute(action_name, args_payload)
                )
                if action_name == "start_session" and isinstance(res_out.get("result"), dict):
                    try:
                        from turnloop import ChatTreeStore
                        camp_obj = res_out["result"]
                        sess_num = int(camp_obj.get("session_number") or 1)
                        target_camp = camp_id or camp_obj.get("id")
                        if target_camp and (before_session_num is None or sess_num > before_session_num):
                            ts = ChatTreeStore(svc)
                            main_tree = ts.get_tree(target_camp, channel_id="main")
                            revs = ts._current_revisions(target_camp)
                            ts.append_message(
                                target_camp,
                                parent_id=main_tree.get("active_leaf_id"),
                                role="system",
                                content=f"Session {sess_num} started — Party LUCK refilled.",
                                campaign_revision=revs["campaign_revision"],
                                solo_revision=revs["solo_revision"],
                                channel_id="main",
                                metadata={"session_started": sess_num},
                            )
                            ts.sync_active_leaf_revisions(target_camp, channel_id="main")
                    except Exception:
                        pass
                if auto_revision and camp_id and action_name not in read_only_actions:
                    try:
                        from turnloop import ChatTreeStore
                        ChatTreeStore(svc).sync_active_leaf_revisions(camp_id)
                    except Exception:
                        pass
                if action_name == "campaign_context" and isinstance(res_out.get("result"), dict):
                    try:
                        from turnloop import TurnEngine, build_npc_profiles, compute_party_grouping
                        ctx_res = res_out["result"]
                        camp_obj = ctx_res.get("campaign") or {}
                        camp_id_ctx = camp_obj.get("id")
                        state_obj = camp_obj.get("state") or {}
                        chars_obj = ctx_res.get("characters") or []
                        secrets_obj = TurnEngine(svc, None)._get_gm_secrets(camp_id_ctx) if camp_id_ctx else {}
                        include_hidden = eff_role in {"admin", "open"}
                        ctx_res["npc_profiles"] = build_npc_profiles(state_obj, secrets_obj, include_hidden=include_hidden)
                        ctx_res["party_grouping"] = compute_party_grouping(chars_obj, state_obj)
                    except Exception:
                        pass
                return res_out

            if "campaign_id" in body:
                if not isinstance(body["campaign_id"], str) or not body["campaign_id"]:
                    raise ValueError("campaign_id must be a nonempty string")
                result = await asyncio.to_thread(lambda: _exec_with_optional_auto_rev(body["campaign_id"]))
                if action_name not in read_only_actions:
                    coop.publish(body["campaign_id"], "sync", {"campaign_id": body["campaign_id"], "kind": "game", "action": action_name})
            else:
                result = await asyncio.to_thread(lambda: _exec_with_optional_auto_rev(None))
            return {**result, "request_id": request_id}
        except HTTPException:
            raise
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})
        except (sqlite3.Error, OSError) as exc:
            logging.getLogger("uvicorn.error").warning("campaign_unavailable request_id=%s error_type=%s", request_id, type(exc).__name__)
            return JSONResponse(status_code=503, content={"detail": "Campaign operation unavailable.", "request_id": request_id})

    @app.get("/health")
    def health(request: Request):
        resolved = Path(db_path).expanduser().resolve()
        lan_enabled = server_host in {"0.0.0.0", "::"}
        sess = _session(request)
        if not resolved.is_file():
            payload = {
                "status": "ok",
                "rules_indexed": False,
                "lan_enabled": lan_enabled,
                "pin_required": bool(resolved_pin),
                "auth_enabled": sess["auth_enabled"],
                "detail": "Corebook PDF not indexed yet. Homebrew and campaign play remain available.",
            }
            if sess["role"] in {"open", "admin"}:
                payload["db_path"] = str(resolved)
            return payload
        info = inspect_index(db_path)
        if sess["role"] not in {"open", "admin"}:
            info = {k: v for k, v in info.items() if k != "db_path"}
        return {
            **info,
            "status": "ok",
            "rules_indexed": True,
            "lan_enabled": lan_enabled,
            "pin_required": bool(resolved_pin),
            "auth_enabled": sess["auth_enabled"],
        }

    _COREBOOK_MAX_BYTES = 512 * 1024 * 1024
    corebook_job_lock = threading.Lock()
    corebook_job: dict[str, Any] = {
        "status": "idle",
        "stage": "idle",
        "percent": 0,
        "current": 0,
        "total": 0,
        "filename": None,
        "message": "",
        "warning": None,
        "error": None,
        "started_at": None,
        "finished_at": None,
    }

    def _semantic_available() -> bool:
        return importlib.util.find_spec("fastembed") is not None and importlib.util.find_spec("numpy") is not None

    @app.get("/v1/corebook/status")
    def corebook_status(request: Request):
        request_id = uuid.uuid4().hex
        blocked = require_player(request, request_id)
        if blocked is not None:
            return blocked
        resolved = Path(db_path).expanduser().resolve()
        sess = _session(request)
        indexed_info: dict[str, Any] = {}
        rules_indexed = resolved.is_file()
        if rules_indexed:
            try:
                indexed_info = inspect_index(db_path)
            except (OSError, sqlite3.Error):
                rules_indexed = False
        with corebook_job_lock:
            job_snapshot = dict(corebook_job)
        payload: dict[str, Any] = {
            "rules_indexed": rules_indexed,
            "indexed_pages": int(indexed_info.get("indexed_pages") or 0),
            "pdf_page_count": int(indexed_info.get("pdf_page_count") or indexed_info.get("indexed_pages") or 0),
            "source_filename": indexed_info.get("source_filename"),
            "semantic_available": _semantic_available(),
            "semantic_indexed": bool(indexed_info.get("embedding_model")),
            "job": job_snapshot,
            "request_id": request_id,
        }
        if sess["role"] in {"open", "admin"}:
            payload["db_path"] = str(resolved)
        return payload

    @app.post("/v1/corebook/upload")
    async def corebook_upload(request: Request, run_semantic: bool = False, filename: str = ""):
        from urllib.parse import unquote

        request_id = uuid.uuid4().hex
        blocked = check_mutable_origin(request, request_id, require_json=False, min_role="admin")
        if blocked is not None:
            return blocked

        content_type = (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
        if content_type.startswith("multipart/"):
            return JSONResponse(
                status_code=415,
                content={"detail": "Upload raw PDF bytes with Content-Type: application/pdf.", "request_id": request_id},
            )

        raw_name = unquote((request.headers.get("x-filename") or filename or "Corebook.pdf").strip())
        safe_name = Path(raw_name.replace("\\", "/")).name or "Corebook.pdf"
        if not safe_name.lower().endswith(".pdf"):
            safe_name += ".pdf"

        with corebook_job_lock:
            if corebook_job["status"] == "running":
                return JSONResponse(
                    status_code=409,
                    content={"detail": "A Corebook upload or indexing job is already running.", "job": dict(corebook_job), "request_id": request_id},
                )
            corebook_job.update({
                "status": "running",
                "stage": "uploading",
                "percent": 1,
                "current": 0,
                "total": 0,
                "filename": safe_name,
                "message": f"Receiving {safe_name}...",
                "warning": None,
                "error": None,
                "started_at": time.time(),
                "finished_at": None,
            })

        tmp_path: Path | None = None
        try:
            fd, tmp_str = tempfile.mkstemp(prefix="redgm-corebook-", suffix=".pdf")
            tmp_path = Path(tmp_str)
            total_bytes = 0
            header_buf = b""
            header_checked = False
            with os.fdopen(fd, "wb") as handle:
                async for chunk in request.stream():
                    if not chunk:
                        continue
                    total_bytes += len(chunk)
                    if total_bytes > _COREBOOK_MAX_BYTES:
                        raise OverflowError("PDF exceeds the 512 MB upload limit.")
                    if not header_checked:
                        header_buf += chunk
                        stripped = header_buf.lstrip()
                        if len(stripped) >= 5:
                            if not stripped.startswith(b"%PDF-"):
                                raise ValueError("This file does not appear to be a valid PDF.")
                            header_checked = True
                    handle.write(chunk)
            if total_bytes == 0:
                raise ValueError("Uploaded PDF file is empty.")
            if not header_checked and not header_buf.lstrip().startswith(b"%PDF-"):
                raise ValueError("This file does not appear to be a valid PDF.")
        except OverflowError as exc:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
            with corebook_job_lock:
                corebook_job.update({"status": "error", "stage": "error", "error": str(exc), "message": str(exc), "finished_at": time.time()})
            return JSONResponse(status_code=413, content={"detail": str(exc), "request_id": request_id})
        except (ValueError, OSError) as exc:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
            with corebook_job_lock:
                corebook_job.update({"status": "error", "stage": "error", "error": str(exc), "message": str(exc), "finished_at": time.time()})
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

        def _on_progress(ev: dict[str, Any]) -> None:
            with corebook_job_lock:
                corebook_job.update({
                    "stage": ev.get("stage", "extracting"),
                    "percent": int(ev.get("percent", 0)),
                    "current": int(ev.get("current", 0)),
                    "total": int(ev.get("total", 0)),
                    "message": str(ev.get("message") or ""),
                })

        def _worker(pdf_file: Path, orig_name: str, want_semantic: bool) -> None:
            try:
                info = build_index(
                    pdf_file,
                    Path(db_path),
                    progress_cb=_on_progress,
                    source_filename=orig_name,
                )
                warning_msg: str | None = None
                if want_semantic and _semantic_available():
                    with corebook_job_lock:
                        corebook_job.update({
                            "stage": "embedding",
                            "percent": 99,
                            "message": "Building local AI meaning search embeddings...",
                        })
                    try:
                        from semantic import build_embeddings
                        build_embeddings(Path(db_path))
                    except Exception as sem_exc:
                        warning_msg = f"Corebook indexed, but semantic embeddings skipped: {sem_exc}"
                with corebook_job_lock:
                    corebook_job.update({
                        "status": "completed",
                        "stage": "done",
                        "percent": 100,
                        "message": f"Corebook ready ({info.get('indexed_pages', 0)} pages).",
                        "warning": warning_msg,
                        "error": None,
                        "finished_at": time.time(),
                    })
            except Exception as exc:
                with corebook_job_lock:
                    corebook_job.update({
                        "status": "error",
                        "stage": "error",
                        "error": str(exc),
                        "message": f"Indexing failed: {exc}",
                        "finished_at": time.time(),
                    })
            finally:
                pdf_file.unlink(missing_ok=True)

        worker = threading.Thread(
            target=_worker,
            args=(tmp_path, safe_name, bool(run_semantic)),
            daemon=True,
        )
        worker.start()
        with corebook_job_lock:
            snapshot = dict(corebook_job)
        return JSONResponse(status_code=202, content={"started": True, "job": snapshot, "request_id": request_id})

    @app.get("/v1/search")
    def search(request: Request, q: str = Query(min_length=2), limit: int = Query(5, ge=1, le=20)):
        blocked = require_player(request, uuid.uuid4().hex)
        if blocked is not None:
            return blocked
        results = search_pages(db_path, q, limit)
        return {"query": q, "results": results, "request_id": audit("search_corebook", results),
                "evidence_status": "candidates_not_verified_answers" if results else "no_matches"}

    @app.get("/v1/pages/{page}")
    def page_lookup(request: Request, page: int, numbering: str = "printed"):
        blocked = require_player(request, uuid.uuid4().hex)
        if blocked is not None:
            return blocked
        try:
            result = read_page(db_path, page, numbering)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if result is None:
            audit("read_corebook_page", [])
            raise HTTPException(404, "Page not found")
        result["request_id"] = audit("read_corebook_page", [result])
        return result

    @app.get("/v1/phrase")
    def phrase(request: Request, q: str = Query(min_length=3), limit: int = Query(10, ge=1, le=100)):
        blocked = require_player(request, uuid.uuid4().hex)
        if blocked is not None:
            return blocked
        return {"query": q, "results": find_phrase(db_path, q, limit)}

    @app.get("/v1/catalog")
    def source_catalog(request: Request):
        blocked = require_player(request, uuid.uuid4().hex)
        if blocked is not None:
            return blocked
        from knowledge import catalog
        result = catalog(db_path)
        result["request_id"] = audit("catalog_corebook", [])
        return result

    @app.get("/v1/sections/{section_id}")
    def source_section(request: Request, section_id: str, offset: int = Query(0, ge=0), limit: int = Query(8, ge=1, le=12)):
        blocked = require_player(request, uuid.uuid4().hex)
        if blocked is not None:
            return blocked
        from knowledge import section
        result = section(db_path, section_id, offset, limit)
        result["request_id"] = audit("read_corebook_section", result["pages"])
        return result

    @app.get("/v1/page-batch")
    def source_pages(request: Request, numbers: str, numbering: str = "printed"):
        blocked = require_player(request, uuid.uuid4().hex)
        if blocked is not None:
            return blocked
        from knowledge import pages
        try:
            result = pages(db_path, [int(n) for n in numbers.split(",")], numbering)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        result["request_id"] = audit("read_corebook_pages", result["pages"])
        return result

    @app.get("/v1/skills")
    def skill_catalog(request: Request):
        blocked = require_player(request, uuid.uuid4().hex)
        if blocked is not None:
            return blocked
        if not Path(db_path).expanduser().is_file():
            return {"skills": {}, "rules_indexed": False, "request_id": audit("catalog_corebook_skills", [])}
        from sourcecatalog import skills
        return {"skills": skills(db_path), "rules_indexed": True, "request_id": audit("catalog_corebook_skills", [])}

    @app.get("/v1/creation/reference")
    def creation_reference(request: Request):
        request_id = uuid.uuid4().hex
        blocked = require_player(request, request_id)
        if blocked is not None:
            return blocked
        from creation_reference import build_creation_reference
        payload = build_creation_reference(db_path)
        payload["request_id"] = request_id
        return payload

    @app.post("/v1/creation/ai-assist")
    async def creation_ai_assist(request: Request):
        request_id = uuid.uuid4().hex
        blocked = require_player(request, request_id)
        if blocked is not None:
            return blocked
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(status_code=400, content={"detail": "Invalid JSON body", "request_id": request_id})
        try:
            active_llm = _resolve_active_llm(body.get("llm") if isinstance(body, dict) else None)
        except Exception as exc:
            return JSONResponse(status_code=503, content={"detail": f"LLM settings unavailable: {exc}", "request_id": request_id})
        try:
            from creation_catalog import generate_creation_ai_assist
            result = await generate_creation_ai_assist(
                db_path,
                active_llm,
                body,
                settings_path=resolved_settings_path(),
            )
        except ValueError as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})
        except Exception as exc:
            return JSONResponse(status_code=502, content={"detail": f"AI narrative assist failed: {exc}", "request_id": request_id})
        return {**result, "request_id": request_id}

    def campaign_db_path() -> Path:
        from campaign import DEFAULT_DB as DEFAULT_CAMPAIGN_DB
        return DEFAULT_CAMPAIGN_DB if campaign_path is None else Path(campaign_path)

    @app.get("/v1/library")
    def library_search(
        request: Request,
        q: str = "",
        category: str | None = None,
        campaign_id: str | None = None,
        include_corebook: bool = True,
        include_homebrew: bool = True,
        limit: int = Query(20, ge=1, le=100),
    ):
        request_id = uuid.uuid4().hex
        blocked = require_player(request, request_id)
        if blocked is not None:
            return blocked
        from library import search_library
        try:
            items = search_library(
                db_path,
                q=q,
                category=category,
                campaign_path=campaign_db_path() if campaign_id else None,
                campaign_id=campaign_id,
                include_corebook=include_corebook,
                include_homebrew=include_homebrew,
                limit=limit,
            )
            return {"query": q, "category": category, "items": items, "request_id": request_id}
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.get("/v1/library/{entry_id:path}")
    def library_entry(request: Request, entry_id: str, campaign_id: str | None = None):
        request_id = uuid.uuid4().hex
        blocked = require_player(request, request_id)
        if blocked is not None:
            return blocked
        from library import get_library_entry
        try:
            item = get_library_entry(
                entry_id,
                rules_path=db_path,
                campaign_path=campaign_db_path() if campaign_id else None,
                campaign_id=campaign_id,
            )
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})
        if item is None:
            return JSONResponse(status_code=404, content={"detail": "Library entry not found", "request_id": request_id})
        return {"item": item, "request_id": request_id}

    @app.post("/v1/library/homebrew")
    async def library_add_homebrew(request: Request):
        request_id = uuid.uuid4().hex
        blocked = check_mutable_origin(request, request_id, require_json=True)
        if blocked is not None:
            return blocked
        from library import CampaignLibrary
        try:
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get("campaign_id"), str) or not body["campaign_id"]:
                raise ValueError("campaign_id must be a nonempty string")
            lib = CampaignLibrary(gameplay_service().store, rules_path=db_path)
            entry = await asyncio.to_thread(
                lambda: lib.add_entry(
                    body["campaign_id"],
                    name=body.get("name"),
                    category=body.get("category"),
                    operation_id=body.get("operation_id") or f"hb:{uuid.uuid4().hex[:12]}",
                    summary=body.get("summary", ""),
                    description=body.get("description", ""),
                    stats=body.get("stats"),
                    tags=body.get("tags"),
                    created_by=body.get("created_by", "user"),
                    allow_variant=bool(body.get("allow_variant", False)),
                )
            )
            coop.publish(body["campaign_id"], "sync", {"campaign_id": body["campaign_id"], "kind": "library"})
            return {"item": entry, "request_id": request_id}
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.delete("/v1/library/homebrew/{entry_id:path}")
    async def library_delete_homebrew(request: Request, entry_id: str, campaign_id: str):
        request_id = uuid.uuid4().hex
        blocked = check_mutable_origin(request, request_id, require_json=False)
        if blocked is not None:
            return blocked
        from library import CampaignLibrary
        try:
            lib = CampaignLibrary(gameplay_service().store, rules_path=db_path)
            removed = await asyncio.to_thread(lambda: lib.remove_entry(campaign_id, entry_id))
            if not removed:
                return JSONResponse(status_code=404, content={"detail": "Homebrew entry not found", "request_id": request_id})
            coop.publish(campaign_id, "sync", {"campaign_id": campaign_id, "kind": "library"})
            return {"deleted": True, "entry_id": entry_id, "request_id": request_id}
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.get("/v1/chat/tree")
    def chat_tree(request: Request, campaign_id: str, channel_id: str = "main"):
        request_id = uuid.uuid4().hex
        blocked = require_player(request, request_id)
        if blocked is not None:
            return blocked
        from turnloop import ChatTreeStore
        try:
            tree = ChatTreeStore(gameplay_service()).get_tree(campaign_id, channel_id=channel_id)
            return {**tree, "request_id": request_id}
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.post("/v1/chat/branch")
    async def chat_branch(request: Request):
        request_id = uuid.uuid4().hex
        blocked = check_mutable_origin(request, request_id, require_json=True)
        if blocked is not None:
            return blocked
        from turnloop import ChatTreeStore
        try:
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get("campaign_id"), str) or not isinstance(body.get("message_id"), str):
                raise ValueError("campaign_id and message_id must be strings")
            tree = await asyncio.to_thread(
                lambda: ChatTreeStore(gameplay_service()).switch_branch(body["campaign_id"], body["message_id"])
            )
            coop.publish(body["campaign_id"], "sync", {"campaign_id": body["campaign_id"], "kind": "chat"})
            return {**tree, "request_id": request_id}
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.post("/v1/chat/delete")
    async def chat_delete(request: Request):
        request_id = uuid.uuid4().hex
        blocked = check_mutable_origin(request, request_id, require_json=True)
        if blocked is not None:
            return blocked
        from turnloop import ChatTreeStore
        try:
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get("campaign_id"), str) or not isinstance(body.get("message_id"), str):
                raise ValueError("campaign_id and message_id must be strings")
            scope = body.get("scope", "branch")
            if not isinstance(scope, str) or scope not in {"branch", "single"}:
                raise ValueError("scope must be 'branch' or 'single'")
            tree = await asyncio.to_thread(
                lambda: ChatTreeStore(gameplay_service()).delete_message(body["campaign_id"], body["message_id"], scope=scope)
            )
            coop.publish(body["campaign_id"], "sync", {"campaign_id": body["campaign_id"], "kind": "chat"})
            return {**tree, "request_id": request_id}
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.post("/v1/chat/message/update")
    async def chat_message_update(request: Request):
        request_id = uuid.uuid4().hex
        blocked = check_mutable_origin(request, request_id, require_json=True)
        if blocked is not None:
            return blocked
        from turnloop import ChatTreeStore
        try:
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get("campaign_id"), str) or not isinstance(body.get("message_id"), str) or not isinstance(body.get("content"), str):
                raise ValueError("campaign_id, message_id, and content must be strings")
            tree = await asyncio.to_thread(
                lambda: ChatTreeStore(gameplay_service()).update_message(body["campaign_id"], body["message_id"], body["content"])
            )
            coop.publish(body["campaign_id"], "sync", {"campaign_id": body["campaign_id"], "kind": "chat"})
            return {**tree, "request_id": request_id}
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.get("/v1/chat/export")
    def chat_export(request: Request, campaign_id: str, leaf_id: str | None = None, channel_id: str = "main"):
        request_id = uuid.uuid4().hex
        blocked = require_player(request, request_id)
        if blocked is not None:
            return blocked
        sess = _session(request)
        if _effective_role(request, sess) == "user" and not sess.get("pin_only_mode"):
            return JSONResponse(status_code=403, content={"detail": "Admin permission required to export story logs.", "request_id": request_id})
        from turnloop import ChatTreeStore
        try:
            exported = ChatTreeStore(gameplay_service()).export_branch(campaign_id, leaf_id, channel_id=channel_id)
            return {**exported, "request_id": request_id}
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.get("/v1/network/info")
    def network_info(request: Request, campaign_id: str | None = None):
        request_id = uuid.uuid4().hex
        blocked = require_player(request, request_id)
        if blocked is not None:
            return blocked
        lan_enabled = server_host in {"0.0.0.0", "::"}
        ips = _detect_lan_ips() if lan_enabled else []
        host_header = request.headers.get("host") or f"127.0.0.1:{server_port}"
        scheme = request.url.scheme or "http"
        suffix = f"/?campaign={campaign_id}" if campaign_id else "/"
        srv_cfg = load_server_settings(resolved_settings_path())
        public_url = str(srv_cfg.get("public_url") or "").strip().rstrip("/")
        urls: list[str] = []
        if public_url:
            urls.append(f"{public_url}{suffix}")
        for ip in ips:
            u = f"{scheme}://{ip}:{server_port}{suffix}"
            if u not in urls:
                urls.append(u)
        if not urls:
            urls = [f"{scheme}://{host_header}{suffix}"]
        turns = coop.all_active_turns(campaign_id) if campaign_id else {}
        return {
            "bind_host": server_host,
            "port": server_port,
            "lan_enabled": lan_enabled,
            "pin_required": bool(resolved_pin),
            "public_url": public_url,
            "lan_ips": ips,
            "join_urls": urls,
            "roster": coop.roster(campaign_id) if campaign_id else [],
            "active_turn": turns.get("main") or next(iter(turns.values()), None),
            "active_turns": turns,
            "sync_seq": coop.current_seq(campaign_id) if campaign_id else 0,
            "request_id": request_id,
        }

    @app.post("/v1/campaigns/{campaign_id}/presence")
    async def campaign_presence(request: Request, campaign_id: str):
        request_id = uuid.uuid4().hex
        blocked = check_mutable_origin(request, request_id, require_json=True)
        if blocked is not None:
            return blocked
        try:
            await asyncio.to_thread(lambda: gameplay_service().campaign_context(campaign_id))
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("Body must be a JSON object")
            client_id = str(body.get("client_id") or request.headers.get("x-redgm-client-id") or "").strip()
            if not client_id:
                raise ValueError("client_id must be a nonempty string")
            player_name = str(body.get("player_name") or "Player").strip()
            character_id = body.get("character_id") if isinstance(body.get("character_id"), str) and body["character_id"].strip() else None
            is_host = bool(body.get("is_host", False))
            roster = coop.update_presence(
                campaign_id,
                client_id=client_id,
                player_name=player_name,
                character_id=character_id,
                is_host=is_host,
            )
            turns = coop.all_active_turns(campaign_id)
            return {
                "players": roster,
                "active_turn": turns.get("main") or next(iter(turns.values()), None),
                "active_turns": turns,
                "sync_seq": coop.current_seq(campaign_id),
                "request_id": request_id,
            }
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.get("/v1/campaigns/{campaign_id}/events")
    async def campaign_events(request: Request, campaign_id: str):
        request_id = uuid.uuid4().hex
        sess = _session(request)
        if sess["role"] != "open" and not sess["authenticated"]:
            if sess["pin_only_mode"]:
                return JSONResponse(status_code=401, content={"detail": "Room PIN required", "pin_required": True, "request_id": request_id})
            return JSONResponse(status_code=401, content={"detail": "Sign in required", "auth_required": True, "request_id": request_id})
        try:
            await asyncio.to_thread(lambda: gameplay_service().campaign_context(campaign_id))
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})
        from starlette.responses import StreamingResponse
        q: asyncio.Queue = asyncio.Queue(maxsize=1024)
        subs = coop.subscribers.setdefault(campaign_id, set())
        subs.add(q)

        async def room_stream():
            try:
                turns = coop.all_active_turns(campaign_id)
                init_payload = json.dumps(
                    {
                        "campaign_id": campaign_id,
                        "players": coop.roster(campaign_id),
                        "active_turn": turns.get("main") or next(iter(turns.values()), None),
                        "active_turns": turns,
                        "sync_seq": coop.current_seq(campaign_id),
                    },
                    ensure_ascii=False,
                )
                yield f"event: presence\ndata: {init_payload}\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        msg = await asyncio.wait_for(q.get(), timeout=12.0)
                        payload = json.dumps(msg["data"], ensure_ascii=False)
                        yield f"event: {msg['event']}\ndata: {payload}\n\n"
                    except asyncio.TimeoutError:
                        ping_payload = json.dumps({"ts": time.time(), "sync_seq": coop.current_seq(campaign_id)})
                        yield f"event: ping\ndata: {ping_payload}\n\n"
            finally:
                subs.discard(q)

        return StreamingResponse(
            room_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    def _resolve_active_llm(cfg_raw: dict[str, Any] | None = None):
        if llm is not None:
            return llm
        from turnloop import LLMConfig, OpenAICompatibleLLM, load_llm_settings
        saved = load_llm_settings(resolved_settings_path())
        merged = dict(saved)
        if isinstance(cfg_raw, dict):
            for key in (
                "base_url",
                "model",
                "api_key",
                "temperature",
                "top_p",
                "presence_penalty",
                "frequency_penalty",
                "max_tokens",
                "timeout_s",
                "mode",
                "retry_attempts",
            ):
                if key in cfg_raw and cfg_raw[key] is not None:
                    merged[key] = cfg_raw[key]
        return OpenAICompatibleLLM(
            LLMConfig(
                base_url=str(merged["base_url"]),
                model=str(merged["model"]),
                api_key=str(merged.get("api_key") or ""),
                temperature=float(merged["temperature"]),
                top_p=float(merged.get("top_p", 1.0)),
                presence_penalty=float(merged.get("presence_penalty", 0.0)),
                frequency_penalty=float(merged.get("frequency_penalty", 0.0)),
                max_tokens=int(merged["max_tokens"]),
                timeout_s=float(merged["timeout_s"]),
                mode=str(merged["mode"]),
                retry_attempts=int(merged.get("retry_attempts", 2)),
            )
        )

    def _sse_response(events_iter_fn, request_id: str, on_finish=None):
        from starlette.responses import StreamingResponse

        async def event_stream():
            try:
                async for ev in events_iter_fn():
                    payload = json.dumps(ev["data"], ensure_ascii=False)
                    yield f"event: {ev['event']}\ndata: {payload}\n\n"
            except Exception as exc:
                err = json.dumps({"detail": str(exc), "request_id": request_id}, ensure_ascii=False)
                yield f"event: error\ndata: {err}\n\n"
            finally:
                if on_finish is not None:
                    on_finish()

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.get("/v1/settings/public")
    def get_public_settings(request: Request):
        request_id = uuid.uuid4().hex
        blocked = require_player(request, request_id)
        if blocked is not None:
            return blocked
        sess = _session(request)
        llm_cfg = load_llm_settings(resolved_settings_path())
        return {
            "role": sess["role"],
            "username": sess["username"],
            "auth_enabled": sess["auth_enabled"],
            "mode": llm_cfg["mode"],
            "gm_style": llm_cfg.get("gm_style", "grounded"),
            "narrator_length": llm_cfg.get("narrator_length", "standard"),
            "gm_thinking_mode": llm_cfg.get("gm_thinking_mode", "quality"),
            "require_character_to_speak": bool(llm_cfg.get("require_character_to_speak", True)),
            "enable_chronicler": bool(llm_cfg.get("enable_chronicler", True)),
            "enable_highlights": bool(llm_cfg.get("enable_highlights", True)),
            "allow_ai_homebrew": bool(llm_cfg.get("allow_ai_homebrew", True)),
            "auto_compress_prompt": bool(llm_cfg.get("auto_compress_prompt", True)),
            "history_window": int(llm_cfg.get("history_window", 14)),
            "compression_threshold": int(llm_cfg.get("compression_threshold", 14)),
            "citation_limit": int(llm_cfg.get("citation_limit", 4)),
            "default_time_step_minutes": int(llm_cfg.get("default_time_step_minutes", 0)),
            "request_id": request_id,
        }

    @app.get("/v1/settings/all")
    def get_all_settings(request: Request):
        request_id = uuid.uuid4().hex
        blocked = require_admin(request, request_id)
        if blocked is not None:
            return blocked
        s_path = resolved_settings_path()
        llm_cfg = load_llm_settings(s_path)
        prompts_cfg = load_prompt_settings(s_path)
        server_cfg = load_server_settings(s_path)
        acc_info = auth.list_accounts()
        return {
            "llm": masked_llm_settings(llm_cfg),
            "prompts": prompts_cfg,
            "prompt_defaults": DEFAULT_PROMPT_TEMPLATES,
            "server": server_cfg,
            "auth_policy": {
                "allow_guest_users": acc_info["allow_guest_users"],
                "allow_self_signup": acc_info["allow_self_signup"],
                "user_passcode_configured": acc_info["user_passcode_configured"],
                "admin_configured": auth.is_admin_configured(),
                "user_configured": auth.is_user_configured(),
                "accounts": acc_info["accounts"],
            },
            "runtime": {
                "active_host": server_host,
                "active_port": server_port,
                "in_docker": _in_docker(),
                "restart_supported": bool(allow_server_control),
                "restart_required": (
                    server_cfg["bind_host"] != server_host or int(server_cfg["port"]) != int(server_port)
                ),
            },
            "request_id": request_id,
        }

    @app.get("/v1/settings/llm")
    def get_llm_settings(request: Request):
        request_id = uuid.uuid4().hex
        blocked = require_admin(request, request_id)
        if blocked is not None:
            return blocked
        settings = load_llm_settings(resolved_settings_path())
        return {**masked_llm_settings(settings), "request_id": request_id}

    @app.post("/v1/settings/llm")
    async def update_llm_settings(request: Request):
        request_id = uuid.uuid4().hex
        blocked = check_mutable_origin(request, request_id, require_json=True, min_role="admin")
        if blocked is not None:
            return blocked
        try:
            body = await request.json()
            saved = await asyncio.to_thread(lambda: save_llm_settings(body, resolved_settings_path()))
            return {**masked_llm_settings(saved), "request_id": request_id}
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.post("/v1/settings/prompts")
    async def update_prompt_settings(request: Request):
        request_id = uuid.uuid4().hex
        blocked = check_mutable_origin(request, request_id, require_json=True, min_role="admin")
        if blocked is not None:
            return blocked
        try:
            body = await request.json()
            saved = await asyncio.to_thread(lambda: save_prompt_settings(body, resolved_settings_path()))
            return {"prompts": saved, "prompt_defaults": DEFAULT_PROMPT_TEMPLATES, "request_id": request_id}
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.post("/v1/settings/server")
    async def update_server_settings(request: Request):
        request_id = uuid.uuid4().hex
        blocked = check_mutable_origin(request, request_id, require_json=True, min_role="admin")
        if blocked is not None:
            return blocked
        try:
            body = await request.json()
            saved = await asyncio.to_thread(lambda: save_server_settings(body, resolved_settings_path()))
            dynamic_origins.update(saved.get("allowed_origins") or [])
            return {
                "server": saved,
                "active_host": server_host,
                "active_port": server_port,
                "in_docker": _in_docker(),
                "restart_supported": bool(allow_server_control),
                "restart_required": (
                    saved["bind_host"] != server_host or int(saved["port"]) != int(server_port)
                ),
                "request_id": request_id,
            }
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.post("/v1/settings/server/restart")
    async def restart_server(request: Request):
        request_id = uuid.uuid4().hex
        blocked = check_mutable_origin(request, request_id, require_json=False, min_role="admin")
        if blocked is not None:
            return blocked
        srv = load_server_settings(resolved_settings_path())
        if not allow_server_control:
            return JSONResponse(
                status_code=400,
                content={"detail": "Server self-restart is only available when running via redkb.py serve", "request_id": request_id},
            )

        def _reexec():
            cleaned: list[str] = []
            skip_next = False
            for arg in sys.argv[1:]:
                if skip_next:
                    skip_next = False
                    continue
                if arg in {"--host", "--port"}:
                    skip_next = True
                    continue
                if arg.startswith("--host=") or arg.startswith("--port=") or arg in {"--lan", "--from-settings"}:
                    continue
                cleaned.append(arg)
            if "serve" not in cleaned:
                cleaned.append("serve")
            cleaned.append("--from-settings")
            cmd = [sys.executable, str(Path(__file__).resolve()), *cleaned]
            os.execv(sys.executable, cmd)

        timer = threading.Timer(0.35, _reexec)
        timer.daemon = True
        timer.start()
        return {
            "restarting": True,
            "bind_host": srv["bind_host"],
            "port": srv["port"],
            "in_docker": _in_docker(),
            "request_id": request_id,
        }

    @app.post("/v1/settings/llm/test")
    async def test_llm_settings(request: Request):
        request_id = uuid.uuid4().hex
        blocked = check_mutable_origin(request, request_id, require_json=True, min_role="admin")
        if blocked is not None:
            return blocked
        import httpx
        from turnloop import load_llm_settings
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("Request body must be an object")
            saved = load_llm_settings(resolved_settings_path())
            base_url = str(body.get("base_url") or saved["base_url"]).strip().rstrip("/")
            if not (base_url.startswith("http://") or base_url.startswith("https://")):
                raise ValueError("base_url must start with http:// or https://")
            api_key = str(body["api_key"]).strip() if isinstance(body.get("api_key"), str) and body["api_key"].strip() else str(saved.get("api_key") or "")
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            models_url = base_url[:-len("/chat/completions")] + "/models" if base_url.endswith("/chat/completions") else f"{base_url}/models"
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(models_url, headers=headers)
            if resp.status_code >= 400:
                return {"ok": False, "status_code": resp.status_code, "models": [], "detail": f"Provider returned HTTP {resp.status_code}", "request_id": request_id}
            data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            models = [m.get("id") for m in (data.get("data") or []) if isinstance(m, dict) and m.get("id")]
            return {"ok": True, "status_code": resp.status_code, "models": models[:50], "detail": f"Connected ({len(models)} models found)" if models else "Connected", "request_id": request_id}
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            return {"ok": False, "status_code": 0, "models": [], "detail": f"Connection failed: {exc}", "request_id": request_id}

    def _parse_luck_spend(raw: Any) -> int:
        if raw is None:
            return 0
        if isinstance(raw, bool):
            raise ValueError("luck_spend must be an integer")
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("luck_spend must be an integer") from exc
        if value < 0:
            raise ValueError("luck_spend must be >= 0")
        return value

    def _relay_coop_turn(
        events_iter_fn,
        *,
        campaign_id: str,
        channel_id: str,
        client_id: str,
        speaker_name: str,
        speaker_color: str | None = None,
        speaker_portrait_url: str | None = None,
        user_text: str = "",
        overclock: bool = False,
        truncate_from_id: str | None = None,
    ):
        async def _wrapped():
            delta_buf: list[str] = []
            last_flush = time.monotonic()
            meta_base: dict[str, Any] = {
                "campaign_id": campaign_id,
                "channel_id": channel_id,
                "client_id": client_id,
                "speaker_name": speaker_name,
                **({"speaker_color": speaker_color} if speaker_color else {}),
                **({"speaker_portrait_url": speaker_portrait_url} if speaker_portrait_url else {}),
                "user_text": user_text,
                "overclock": overclock,
                **({"truncate_from_id": truncate_from_id} if truncate_from_id else {}),
            }

            def _flush_deltas():
                nonlocal last_flush
                if not delta_buf:
                    return
                joined = "".join(delta_buf)
                delta_buf.clear()
                last_flush = time.monotonic()
                coop.publish(
                    campaign_id,
                    "peer_stream",
                    {**meta_base, "event": "text_delta", "data": {"delta": joined}},
                )

            done_emitted = False
            try:
                async for ev in events_iter_fn():
                    ev_name = ev.get("event")
                    ev_data = ev.get("data") or {}
                    if ev_name == "user_message":
                        coop.publish(
                            campaign_id,
                            "peer_user_message",
                            {
                                "campaign_id": campaign_id,
                                "channel_id": channel_id,
                                "client_id": client_id,
                                "message": ev_data.get("message"),
                            },
                        )
                        coop.publish(
                            campaign_id,
                            "sync",
                            {"campaign_id": campaign_id, "kind": "chat", "channel_id": channel_id},
                        )
                        continue
                    if ev_name == "text_delta":
                        piece = str(ev_data.get("delta") or "")
                        if piece:
                            delta_buf.append(piece)
                            now_m = time.monotonic()
                            if sum(len(x) for x in delta_buf) >= 24 or (now_m - last_flush) >= 0.045:
                                _flush_deltas()
                    elif ev_name in {"rule_citation", "dice_roll", "state_patch", "library_added", "warning"}:
                        _flush_deltas()
                        coop.publish(
                            campaign_id,
                            "peer_stream",
                            {**meta_base, "event": ev_name, "data": ev_data},
                        )
                    elif ev_name == "turn_done":
                        _flush_deltas()
                        done_emitted = True
                        coop.publish(
                            campaign_id,
                            "peer_turn_done",
                            {
                                "campaign_id": campaign_id,
                                "channel_id": channel_id,
                                "client_id": client_id,
                                **ev_data,
                            },
                        )
                        coop.publish(
                            campaign_id,
                            "sync",
                            {"campaign_id": campaign_id, "kind": "chat", "channel_id": channel_id},
                        )
                    yield ev
            finally:
                if not done_emitted:
                    _flush_deltas()
                    coop.publish(
                        campaign_id,
                        "peer_turn_done",
                        {
                            "campaign_id": campaign_id,
                            "channel_id": channel_id,
                            "client_id": client_id,
                            "aborted": True,
                        },
                    )
                    coop.publish(
                        campaign_id,
                        "sync",
                        {"campaign_id": campaign_id, "kind": "chat", "channel_id": channel_id},
                    )

        return _wrapped

    @app.post("/v1/chat/turn")
    async def chat_turn(request: Request):
        request_id = uuid.uuid4().hex
        blocked = check_mutable_origin(request, request_id, require_json=True)
        if blocked is not None:
            return blocked
        from turnloop import ChatTreeStore, TurnEngine
        try:
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get("campaign_id"), str) or not isinstance(body.get("user_text"), str):
                raise ValueError("campaign_id and user_text must be strings")
            campaign_id = body["campaign_id"]
            user_text = body["user_text"]
            if not user_text.strip():
                raise ValueError("user_text must be nonempty")
            channel_id = ChatTreeStore._norm_channel(body.get("channel_id"))
            luck_spend = _parse_luck_spend(body.get("luck_spend"))
            client_id = str(body.get("client_id") or request.headers.get("x-redgm-client-id") or request_id)
            player_name = str(body.get("player_name") or body.get("speaker_name") or "Player")
            gm_mode = str(body.get("gm_mode") or "auto").strip().lower()
            if gm_mode not in {"auto", "force_gm", "hold_gm"}:
                raise ValueError("gm_mode must be 'auto', 'force_gm', or 'hold_gm'")
            is_intro = bool(body.get("is_intro", False))
            sess = _session(request)
            eff_role = _effective_role(request, sess)
            uname = str(sess.get("username") or "").strip()
            llm_cfg = load_llm_settings(resolved_settings_path())

            active_llm = _resolve_active_llm(body.get("llm_config"))
            engine = TurnEngine(gameplay_service(), active_llm, settings_path=resolved_settings_path())
            ctx = engine.gameplay.campaign_context(campaign_id)
            chars = ctx.get("characters") or []
            speaker_char_id = body.get("speaker_character_id")
            speaker_info = engine._resolve_speaker(chars, speaker_char_id, body.get("speaker_name"))

            # Enforce character ownership & characterless speaking restriction for non-admin users
            if eff_role == "user" and not is_intro and not sess.get("pin_only_mode"):
                if isinstance(speaker_char_id, str) and speaker_char_id.strip():
                    matched_char = next((c for c in chars if c["id"] == speaker_char_id.strip()), None)
                    if matched_char is None:
                        return JSONResponse(status_code=400, content={"detail": "Selected speaking character is not attached to this campaign.", "request_id": request_id})
                    owner = str((matched_char.get("detail") or {}).get("owner_username") or "").strip()
                    if uname and owner and owner.lower() != uname.lower():
                        return JSONResponse(status_code=403, content={"detail": f"You cannot speak as {matched_char.get('name')} (owned by {owner}).", "request_id": request_id})
                elif bool(llm_cfg.get("require_character_to_speak", True)):
                    return JSONResponse(
                        status_code=403,
                        content={
                            "detail": "You must create or claim a character before speaking in chat (Admin has 'Require Character to Speak' enabled).",
                            "request_id": request_id,
                        },
                    )

            if body.get("parent_id") is not None:
                engine.tree.get_branch_to(campaign_id, body["parent_id"])
            if gm_mode != "hold_gm":
                busy_turn = coop.acquire_turn(campaign_id, client_id=client_id, player_name=player_name, channel_id=channel_id)
                if busy_turn is not None:
                    return JSONResponse(status_code=409, content={"detail": f"GM is currently resolving {busy_turn['player_name']}'s turn", "request_id": request_id})
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

        coop_count = max(1, len(coop.roster(campaign_id)))

        def finish_turn():
            if gm_mode != "hold_gm":
                coop.release_turn(campaign_id, client_id, channel_id=channel_id)
            coop.publish(campaign_id, "sync", {"campaign_id": campaign_id, "kind": "chat", "channel_id": channel_id})

        relayed = _relay_coop_turn(
            lambda: engine.run_turn(
                campaign_id,
                user_text,
                parent_id=body.get("parent_id"),
                branch_from_root=bool(body.get("branch_from_root", False)),
                overclock=bool(body.get("overclock", False)),
                luck_spend=luck_spend,
                mode=body.get("mode"),
                speaker_character_id=body.get("speaker_character_id"),
                speaker_name=body.get("speaker_name"),
                is_intro=is_intro,
                gm_mode=gm_mode,
                coop_player_count=coop_count,
                channel_id=channel_id,
            ),
            campaign_id=campaign_id,
            channel_id=channel_id,
            client_id=client_id,
            speaker_name=speaker_info.get("name") or player_name,
            speaker_color=speaker_info.get("color"),
            speaker_portrait_url=speaker_info.get("portrait_url"),
            user_text=user_text,
            overclock=bool(body.get("overclock", False)),
            truncate_from_id=str(body["replace_message_id"]).strip() if body.get("replace_message_id") else None,
        )
        return _sse_response(
            relayed,
            request_id,
            on_finish=finish_turn,
        )

    @app.post("/v1/chat/roll")
    async def chat_manual_roll(request: Request):
        request_id = uuid.uuid4().hex
        blocked = check_mutable_origin(request, request_id, require_json=True)
        if blocked is not None:
            return blocked
        from turnloop import ChatTreeStore
        try:
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get("campaign_id"), str) or not isinstance(body.get("character_id"), str):
                raise ValueError("campaign_id and character_id are required")
            campaign_id = body["campaign_id"].strip()
            character_id = body["character_id"].strip()
            stat = str(body.get("stat") or "REF").strip().upper()
            skill = str(body.get("skill") or "").strip() or None
            dv = int(body.get("dv", 13))
            modifier = int(body.get("modifier", 0))
            luck = _parse_luck_spend(body.get("luck", 0))
            reason = str(body.get("reason") or "Manual skill roll").strip() or "Manual skill roll"

            sess = _session(request)
            eff_role = _effective_role(request, sess)
            uname = str(sess.get("username") or "").strip()

            def _do_roll():
                svc = gameplay_service()
                char = svc.store.get_character(character_id)
                if char is None:
                    raise ValueError("Character not found")
                d = char.get("detail") or {}
                owner = str(d.get("owner_username") or "").strip()
                if eff_role == "user" and uname and owner and owner.lower() != uname.lower():
                    raise PermissionError(f"You cannot roll for {char.get('name')} (owned by {owner}).")
                check_res = svc.execute(
                    "skill_check",
                    {
                        "character_id": character_id,
                        "expected_revision": char["revision"],
                        "stat": stat,
                        "skill": skill,
                        "dv": dv,
                        "modifier": modifier,
                        "luck": luck,
                        "reason": reason,
                        "operation_id": f"mroll-{uuid.uuid4().hex[:12]}",
                    },
                    campaign_id=campaign_id,
                )["result"]
                speaker_label = str(d.get("handle") or char["name"])
                roll_card = {
                    "actor": speaker_label,
                    "character_id": character_id,
                    "stat": stat,
                    "skill": skill,
                    "dv": dv,
                    "modifier": modifier,
                    "luck_spent": luck,
                    "reason": reason,
                    "total": check_res["total"],
                    "die": check_res.get("die"),
                    "dice": check_res.get("dice"),
                    "base": check_res.get("base"),
                    "explosion": check_res.get("explosion", 0),
                    "wound_modifier": check_res.get("wound_modifier", 0),
                    "success": check_res["success"],
                }
                channel_id = ChatTreeStore._norm_channel(body.get("channel_id"))
                tree_store = ChatTreeStore(svc)
                cur_tree = tree_store.get_tree(campaign_id, channel_id=channel_id)
                revs = tree_store._current_revisions(campaign_id)
                verdict = "SUCCESS" if check_res["success"] else "FAIL"
                skill_label = f"{skill} ({stat})" if skill else stat
                msg_text = f"Rolled **{skill_label}** vs DV {dv} — **{check_res['total']}** ({verdict}) · *{reason}*"
                meta: dict[str, Any] = {
                    "speaker_character_id": character_id,
                    "speaker_name": speaker_label,
                    "channel_id": channel_id,
                    "manual_roll": True,
                    "gm_deferred": True,
                    "defer_reason": "Manual skill roll posted to table",
                    "rolls": [roll_card],
                }
                if isinstance(d.get("color"), str) and d["color"].strip():
                    meta["speaker_color"] = d["color"].strip()
                if isinstance(d.get("portrait_url"), str) and d["portrait_url"].strip():
                    meta["speaker_portrait_url"] = d["portrait_url"].strip()
                msg = tree_store.append_message(
                    campaign_id,
                    parent_id=cur_tree.get("active_leaf_id"),
                    role="user",
                    content=msg_text,
                    campaign_revision=revs["campaign_revision"],
                    solo_revision=revs["solo_revision"],
                    channel_id=channel_id,
                    metadata=meta,
                )
                updated_tree = tree_store.sync_active_leaf_revisions(campaign_id, channel_id=channel_id)
                return {"roll": roll_card, "result": check_res, "message": msg, "tree": updated_tree}

            out = await asyncio.to_thread(_do_roll)
            coop.publish(campaign_id, "sync", {"campaign_id": campaign_id, "kind": "chat"})
            return {**out, "request_id": request_id}
        except PermissionError as exc:
            return JSONResponse(status_code=403, content={"detail": str(exc), "request_id": request_id})
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.post("/v1/chat/sync-revisions")
    async def chat_sync_revisions(request: Request):
        request_id = uuid.uuid4().hex
        blocked = check_mutable_origin(request, request_id, require_json=True)
        if blocked is not None:
            return blocked
        from turnloop import ChatTreeStore
        try:
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get("campaign_id"), str) or not body["campaign_id"].strip():
                raise ValueError("campaign_id is required")
            campaign_id = body["campaign_id"].strip()
            chan = ChatTreeStore._norm_channel(body.get("channel_id"))
            tree = await asyncio.to_thread(lambda: ChatTreeStore(gameplay_service()).sync_active_leaf_revisions(campaign_id, channel_id=chan))
            coop.publish(campaign_id, "sync", {"campaign_id": campaign_id, "kind": "chat", "channel_id": chan})
            return {**tree, "request_id": request_id}
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.post("/v1/chat/regenerate")
    async def chat_regenerate(request: Request):
        request_id = uuid.uuid4().hex
        blocked = check_mutable_origin(request, request_id, require_json=True)
        if blocked is not None:
            return blocked
        from turnloop import ChatTreeStore, TurnEngine
        try:
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get("campaign_id"), str) or not isinstance(body.get("message_id"), str):
                raise ValueError("campaign_id and message_id must be strings")
            campaign_id = body["campaign_id"]
            message_id = body["message_id"]
            client_id = str(body.get("client_id") or request.headers.get("x-redgm-client-id") or request_id)
            player_name = str(body.get("player_name") or "Player")
            active_llm = _resolve_active_llm(body.get("llm_config"))
            engine = TurnEngine(gameplay_service(), active_llm, settings_path=resolved_settings_path())
            engine.gameplay.campaign_context(campaign_id)
            target = engine.tree.get_message(campaign_id, message_id)
            if target is None:
                raise ValueError(f"message not found in campaign: {message_id}")
            target_channel = ChatTreeStore._norm_channel(target.get("channel_id"))
            regen_luck = (
                _parse_luck_spend(body["luck_spend"])
                if "luck_spend" in body and body["luck_spend"] is not None
                else None
            )
            busy_turn = coop.acquire_turn(campaign_id, client_id=client_id, player_name=player_name, channel_id=target_channel)
            if busy_turn is not None:
                return JSONResponse(status_code=409, content={"detail": f"GM is currently resolving {busy_turn['player_name']}'s turn", "request_id": request_id})
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

        def finish_regen():
            coop.release_turn(campaign_id, client_id, channel_id=target_channel)
            coop.publish(campaign_id, "sync", {"campaign_id": campaign_id, "kind": "chat", "channel_id": target_channel})

        relayed_regen = _relay_coop_turn(
            lambda: engine.regenerate_turn(
                campaign_id,
                message_id,
                overclock=body["overclock"] if "overclock" in body and body["overclock"] is not None else None,
                luck_spend=regen_luck,
                mode=body.get("mode"),
                guidance=body.get("guidance"),
            ),
            campaign_id=campaign_id,
            channel_id=target_channel,
            client_id=client_id,
            speaker_name=str((target.get("metadata") or {}).get("speaker_name") or player_name),
            speaker_color=(target.get("metadata") or {}).get("speaker_color"),
            speaker_portrait_url=(target.get("metadata") or {}).get("speaker_portrait_url"),
            user_text=str(target.get("content") or ""),
            truncate_from_id=message_id if target.get("role") == "assistant" else None,
        )
        return _sse_response(
            relayed_regen,
            request_id,
            on_finish=finish_regen,
        )

    @app.post("/v1/chat/compress")
    async def chat_compress(request: Request):
        request_id = uuid.uuid4().hex
        blocked = check_mutable_origin(request, request_id, require_json=True)
        if blocked is not None:
            return blocked
        from turnloop import TurnEngine
        try:
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get("campaign_id"), str) or not body["campaign_id"].strip():
                raise ValueError("campaign_id is required")
            campaign_id = body["campaign_id"]
            leaf_id = body.get("leaf_id")
            active_llm = _resolve_active_llm(body.get("llm_config"))
            engine = TurnEngine(gameplay_service(), active_llm, settings_path=resolved_settings_path())
            result = await engine.compress_memory(campaign_id, leaf_id=leaf_id)
            coop.publish(campaign_id, "sync", {"campaign_id": campaign_id, "kind": "campaign"})
            coop.publish(campaign_id, "sync", {"campaign_id": campaign_id, "kind": "library"})
            return {**result, "request_id": request_id}
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.get("/v1/campaigns/{campaign_id}/clocks")
    def campaign_clocks_list(campaign_id: str, request: Request, leaf_id: str | None = None):
        request_id = uuid.uuid4().hex
        blocked = require_player(request, request_id)
        if blocked is not None:
            return blocked
        from turnloop import TurnEngine
        try:
            clocks = TurnEngine(gameplay_service(), None, settings_path=resolved_settings_path()).list_public_clocks(campaign_id, leaf_id=leaf_id)
            return {"campaign_id": campaign_id, "clocks": clocks, "request_id": request_id}
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.post("/v1/campaigns/{campaign_id}/clocks")
    async def campaign_clocks_mutate(campaign_id: str, request: Request):
        request_id = uuid.uuid4().hex
        blocked = check_mutable_origin(request, request_id, require_json=True, min_role="admin")
        if blocked is not None:
            return blocked
        sess = _session(request)
        if _effective_role(request, sess) == "user" and not (sess.get("pin_only_mode") and not auth.is_admin_configured()):
            return JSONResponse(status_code=403, content={"detail": "Admin permission required to modify world clocks.", "request_id": request_id})
        from turnloop import TurnEngine
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("Request body must be a JSON object")
            clocks = TurnEngine(gameplay_service(), None).mutate_public_clock(
                campaign_id,
                body,
                leaf_id=body.get("leaf_id"),
            )
            coop.publish(campaign_id, "sync", {"campaign_id": campaign_id, "kind": "campaign"})
            return {"campaign_id": campaign_id, "clocks": clocks, "request_id": request_id}
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.post("/v1/campaigns/{campaign_id}/npc-identity")
    async def campaign_npc_identity(campaign_id: str, request: Request):
        request_id = uuid.uuid4().hex
        blocked = check_mutable_origin(request, request_id, require_json=True, min_role="admin")
        if blocked is not None:
            return blocked
        sess = _session(request)
        eff_role = _effective_role(request, sess)
        from turnloop import TurnEngine, _normalize_campaign_changes, build_npc_profiles
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("Request body must be a JSON object")
            handle = str(body.get("handle") or "").strip()[:100]
            if not handle:
                raise ValueError("handle is required")
            delete_npc = bool(body.get("delete", False))
            description = str(body.get("description") or "").strip()[:2000]
            real_name = str(body.get("real_name") or "").strip()[:100] if isinstance(body.get("real_name"), str) else ""
            real_name_hidden = bool(body.get("real_name_hidden", True))

            def _apply():
                svc = gameplay_service()
                ctx = svc.campaign_context(campaign_id)
                camp = ctx["campaign"]
                eng = TurnEngine(svc, None)
                existing_sec = eng._get_gm_secrets(campaign_id)
                sec_key = f"__npc_real:{handle}"
                effective_real_name = real_name or str(existing_sec.get(sec_key) or "").strip()
                raw_changes: dict[str, Any] = {}
                if delete_npc:
                    raw_changes["npcs"] = {handle: None}
                    raw_changes["npc_identities"] = {handle: None}
                else:
                    if description:
                        raw_changes["npcs"] = {handle: description}
                    raw_changes["npc_identities"] = {
                        handle: {
                            "real_name": effective_real_name,
                            "real_name_hidden": real_name_hidden,
                        }
                    }
                changes, _ = _normalize_campaign_changes(
                    raw_changes,
                    camp["state"],
                    characters=ctx["characters"],
                    existing_secrets=existing_sec,
                )
                if changes:
                    svc.execute(
                        "update_campaign",
                        {
                            "campaign_id": campaign_id,
                            "expected_revision": camp["revision"],
                            "changes": changes,
                            "reason": f"Update NPC identity: {handle}",
                            "operation_id": f"npcid-{uuid.uuid4().hex[:12]}",
                        },
                        campaign_id=campaign_id,
                    )
                if delete_npc or not real_name_hidden or not effective_real_name:
                    eng.update_gm_secrets(campaign_id, {sec_key: None})
                else:
                    eng.update_gm_secrets(campaign_id, {sec_key: effective_real_name})
                eng.tree.sync_active_leaf_revisions(campaign_id)
                fresh_ctx = svc.campaign_context(campaign_id)
                fresh_sec = eng._get_gm_secrets(campaign_id)
                profiles = build_npc_profiles(
                    fresh_ctx["campaign"]["state"],
                    fresh_sec,
                    include_hidden=(eff_role in {"admin", "open"}),
                )
                return {"campaign": fresh_ctx["campaign"], "npc_profiles": profiles}

            res = await asyncio.to_thread(_apply)
            coop.publish(campaign_id, "sync", {"campaign_id": campaign_id, "kind": "campaign"})
            return {**res, "request_id": request_id}
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.post("/v1/campaigns/{campaign_id}/party-location")
    async def campaign_party_location(campaign_id: str, request: Request):
        request_id = uuid.uuid4().hex
        blocked = check_mutable_origin(request, request_id, require_json=True)
        if blocked is not None:
            return blocked
        sess = _session(request)
        eff_role = _effective_role(request, sess)
        uname = str(sess.get("username") or "").strip().lower()
        from turnloop import ChatTreeStore, _normalize_campaign_changes, _resolve_character, compute_party_grouping
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("Request body must be a JSON object")
            action = str(body.get("action") or "update").strip().lower()
            pc_locations = body.get("pc_locations") if isinstance(body.get("pc_locations"), dict) else None
            location = str(body.get("location") or "").strip()[:160]
            append_notice = bool(body.get("append_notice", True))

            def _apply():
                svc = gameplay_service()
                ctx = svc.campaign_context(campaign_id)
                camp = ctx["campaign"]
                chars = ctx["characters"]
                if eff_role == "user" and not sess.get("pin_only_mode"):
                    if action == "reunite":
                        raise PermissionError("Only the GM/Admin can reunite all party members at once.")
                    if isinstance(pc_locations, dict):
                        for raw_actor in pc_locations.keys():
                            matched = _resolve_character(str(raw_actor), chars)
                            if matched is None:
                                raise PermissionError(f"Unknown character '{raw_actor}'.")
                            owner = str((matched.get("detail") or {}).get("owner_username") or "").strip().lower()
                            if not uname or (owner and owner != uname):
                                raise PermissionError(f"You can only update your own character's location (not {matched.get('name')}).")
                before_grouping = compute_party_grouping(chars, camp["state"])
                raw_changes: dict[str, Any] = {}
                if action == "reunite":
                    target_loc = location or str(camp["state"].get("scene") or "").strip() or "Main Scene"
                    raw_changes["all_together"] = target_loc
                    if location:
                        raw_changes["scene"] = target_loc
                elif pc_locations:
                    raw_changes["pc_locations"] = pc_locations
                else:
                    raise ValueError("Provide pc_locations or action='reunite'")
                changes, _ = _normalize_campaign_changes(raw_changes, camp["state"], characters=chars)
                updated_camp = camp
                if changes:
                    updated_camp = svc.execute(
                        "update_campaign",
                        {
                            "campaign_id": campaign_id,
                            "expected_revision": camp["revision"],
                            "changes": changes,
                            "reason": "Update party locations / grouping",
                            "operation_id": f"ploc-{uuid.uuid4().hex[:12]}",
                        },
                        campaign_id=campaign_id,
                    )["result"]
                after_grouping = compute_party_grouping(chars, updated_camp["state"])
                tree_store = ChatTreeStore(svc)
                if append_notice and before_grouping["mode"] != after_grouping["mode"]:
                    main_tree = tree_store.get_tree(campaign_id, channel_id="main")
                    revs = tree_store._current_revisions(campaign_id)
                    if after_grouping["mode"] == "split":
                        parts = [f"{', '.join(ch['handles'])} -> {ch['location']}" for ch in after_grouping["channels"]]
                        notice = f"*Party split into separate scene channels: {'; '.join(parts)}.*"
                    else:
                        notice = f"*Party reunited at {after_grouping['active_location']} (Main Table).* "
                    tree_store.append_message(
                        campaign_id,
                        parent_id=main_tree.get("active_leaf_id"),
                        role="system",
                        content=notice.strip(),
                        campaign_revision=revs["campaign_revision"],
                        solo_revision=revs["solo_revision"],
                        channel_id="main",
                        metadata={"party_transition": after_grouping["mode"]},
                    )
                tree_store.sync_active_leaf_revisions(campaign_id, channel_id="main")
                return {"campaign": updated_camp, "party_grouping": after_grouping}

            res = await asyncio.to_thread(_apply)
            coop.publish(campaign_id, "sync", {"campaign_id": campaign_id, "kind": "all"})
            return {**res, "request_id": request_id}
        except PermissionError as exc:
            return JSONResponse(status_code=403, content={"detail": str(exc), "request_id": request_id})
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.post("/v1/campaigns/{campaign_id}/bootstrap")
    async def campaign_bootstrap(campaign_id: str, request: Request):
        request_id = uuid.uuid4().hex
        blocked = check_mutable_origin(request, request_id, require_json=True, min_role="admin")
        if blocked is not None:
            return blocked
        sess = _session(request)
        if _effective_role(request, sess) == "user" and not (sess.get("pin_only_mode") and not auth.is_admin_configured()):
            return JSONResponse(status_code=403, content={"detail": "Admin permission required to modify campaign setup.", "request_id": request_id})
        from turnloop import TurnEngine
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("Request body must be a JSON object")

            def _apply():
                svc = gameplay_service()
                ctx = svc.campaign_context(campaign_id)
                camp = ctx["campaign"]
                changes: dict[str, Any] = {}
                for field in ("scene", "summary"):
                    val = body.get(field)
                    if isinstance(val, str) and val.strip():
                        changes[field] = val.strip()
                for map_field in ("npcs", "objectives", "discoveries", "unresolved"):
                    val = body.get(map_field)
                    if isinstance(val, dict) and val:
                        cleaned = {
                            str(k).strip(): str(v).strip()
                            for k, v in val.items()
                            if str(k).strip() and str(v).strip()
                        }
                        if cleaned:
                            changes[map_field] = cleaned
                if changes:
                    camp = svc.execute(
                        "update_campaign",
                        {
                            "campaign_id": campaign_id,
                            "expected_revision": camp["revision"],
                            "changes": changes,
                            "reason": "Initialize campaign world & premise",
                            "operation_id": f"camp-boot-{uuid.uuid4().hex[:12]}",
                        },
                        campaign_id=campaign_id,
                    )["result"]
                secrets_in = body.get("gm_secrets")
                secrets_map: dict[str, str] | None = None
                if isinstance(secrets_in, str) and secrets_in.strip():
                    secrets_map = {"Premise Secret": secrets_in.strip()}
                elif isinstance(secrets_in, dict):
                    secrets_map = {
                        str(k).strip(): str(v).strip()
                        for k, v in secrets_in.items()
                        if str(k).strip() and str(v).strip()
                    }
                opening_clock = body.get("opening_clock") if isinstance(body.get("opening_clock"), dict) else None
                eng = TurnEngine(svc, None)
                gm_seed = eng.seed_initial_gm_state(
                    campaign_id,
                    secrets=secrets_map,
                    opening_clock=opening_clock,
                )
                eng.tree.sync_active_leaf_revisions(campaign_id)
                return {"campaign": camp, **gm_seed}

            res = await asyncio.to_thread(_apply)
            coop.publish(campaign_id, "sync", {"campaign_id": campaign_id, "kind": "campaign"})
            return {**res, "request_id": request_id}
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.post("/v1/campaigns/{campaign_id}/primary")
    async def campaign_set_primary(campaign_id: str, request: Request):
        request_id = uuid.uuid4().hex
        blocked = check_mutable_origin(request, request_id, require_json=False, min_role="admin")
        if blocked is not None:
            return blocked
        try:
            res = await asyncio.to_thread(
                lambda: gameplay_service().execute("set_primary_campaign", {"campaign_id": campaign_id})["result"]
            )
            coop.publish(campaign_id, "sync", {"campaign_id": campaign_id, "kind": "campaign"})
            return {"campaign": res, "request_id": request_id}
        except ValueError as exc:
            return JSONResponse(status_code=404, content={"detail": str(exc), "request_id": request_id})

    @app.delete("/v1/campaigns/{campaign_id}")
    async def campaign_delete(campaign_id: str, request: Request):
        request_id = uuid.uuid4().hex
        blocked = check_mutable_origin(request, request_id, require_json=False, min_role="admin")
        if blocked is not None:
            return blocked
        try:
            res = await asyncio.to_thread(
                lambda: gameplay_service().execute("delete_campaign", {"campaign_id": campaign_id})["result"]
            )
            coop.publish(campaign_id, "sync", {"campaign_id": campaign_id, "kind": "campaign_deleted"})
            return {**res, "request_id": request_id}
        except ValueError as exc:
            return JSONResponse(status_code=404, content={"detail": str(exc), "request_id": request_id})

    resolved_ui = Path(ui_dist) if ui_dist is not None else Path(__file__).resolve().parent / "ui" / "dist"
    index_html = resolved_ui / "index.html"
    if index_html.is_file():
        assets_dir = resolved_ui / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="ui-assets")
        ui_root = resolved_ui.resolve()

        @app.get("/", include_in_schema=False)
        def ui_index():
            return FileResponse(index_html)

        @app.get("/{full_path:path}", include_in_schema=False)
        def ui_spa(full_path: str):
            if full_path == "health" or full_path == "v1" or full_path.startswith("v1/"):
                return JSONResponse(status_code=404, content={"detail": "Not found"})
            candidate = (ui_root / full_path).resolve()
            if candidate.is_file() and candidate.is_relative_to(ui_root):
                return FileResponse(candidate)
            return FileResponse(index_html)

    return app


def serve_mcp(db_path: Path, campaign_path=None) -> None:
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("Cyberpunk RED Corebook")
    from campaign import DEFAULT_DB
    from gameplay import GameplayService
    selected_campaign = DEFAULT_DB if campaign_path is None else Path(campaign_path)
    if selected_campaign.expanduser().resolve() == Path(db_path).expanduser().resolve():
        raise ValueError("Campaign database must be separate from the rules index")
    service = None

    @server.tool()
    def game_action(action: str, arguments: dict[str, Any], campaign_id: str | None = None) -> dict[str, Any]:
        """Perform gameplay or campaign memory actions. Supply campaign_id to scope character access.

        Campaign actions: create_campaign(name,operation_id), list_campaigns(),
        get_campaign(campaign_id), campaign_context(campaign_id),
        update_campaign(campaign_id,expected_revision,changes,reason,operation_id),
        attach_character(campaign_id,character_id,expected_revision,reason,operation_id),
        start_session(campaign_id,expected_revision,reason,operation_id),
        campaign_history(campaign_id), undo_campaign(campaign_id,expected_revision,reason,operation_id).
        Start sessions only on explicit player request; this refills attached characters' LUCK.
        Narrative changes may replace scene/summary text or npcs/objectives/discoveries/unresolved maps.
        Other character, roll and check actions are documented in docs/GAMEPLAY.md.
        """
        nonlocal service
        if service is None:
            service = GameplayService(selected_campaign, db_path)
        return service.execute(action, arguments, campaign_id=campaign_id)

    @server.tool()
    def search_corebook(query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Find candidate source passages with citations. Read full pages for context; candidates are not verified rulings."""
        return search_pages(db_path, query, limit)

    @server.tool()
    def read_corebook_page(printed_page: int) -> dict[str, Any]:
        """Open the actual printed page number, returning source text, not a summary."""
        return read_page(db_path, printed_page) or {"error": "Page not found"}

    @server.tool()
    def find_corebook_phrase(phrase: str) -> list[dict[str, Any]]:
        """Search literal phrases across all pages, useful for exact named rules."""
        return find_phrase(db_path, phrase)

    @server.tool()
    def catalog_corebook() -> dict[str, Any]:
        """List source-derived Corebook sections and exact section identifiers."""
        from knowledge import catalog
        return catalog(db_path)

    @server.tool()
    def read_corebook_section(section_id: str, offset: int = 0, limit: int = 8) -> dict[str, Any]:
        """Read a bounded source section with original page labels and table coordinates."""
        from knowledge import section
        return section(db_path, section_id, offset, limit)

    @server.tool()
    def read_corebook_pages(page_numbers: list[int], numbering: str = "printed") -> dict[str, Any]:
        """Read up to twelve exact source pages together, never approximate matches."""
        from knowledge import pages
        return pages(db_path, page_numbers, numbering)

    server.run(transport="stdio")


def cli() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"SQLite rules-index path (default: {DEFAULT_DB})")
    from campaign import DEFAULT_DB as DEFAULT_CAMPAIGN_DB
    parser.add_argument("--campaign-db", type=Path, default=DEFAULT_CAMPAIGN_DB, help=f"Campaign SQLite path (default: {DEFAULT_CAMPAIGN_DB})")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("index", help="Atomically extract and index a local PDF")
    p.add_argument("pdf", type=Path)
    p = sub.add_parser("search", help="Search indexed text with exact keyword matching")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--lexical-only", action="store_true", help="Explicitly disable semantic retrieval for diagnostics")
    p = sub.add_parser("page", help="Open original printed or PDF page")
    p.add_argument("number", type=int)
    p.add_argument("--numbering", choices=["printed", "pdf"], default="printed")
    p = sub.add_parser("phrase", help="Search for exact phrase, ignoring line wraps")
    p.add_argument("query")
    p = sub.add_parser("eval", help="Run golden-query recall evaluation")
    p.add_argument("cases", type=Path)
    sub.add_parser("status", help="Report index and ingestion statistics")
    sub.add_parser("catalog", help="List source-derived Corebook sections")
    sub.add_parser("build-library", help="Materialize the organized rulebook library tables on an existing rules index")
    p = sub.add_parser("section", help="Read a bounded source-derived section")
    p.add_argument("section_id")
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--limit", type=int, default=8)
    p = sub.add_parser("game", help="Perform a campaign operation (modifies campaign state)")
    p.add_argument("action")
    p.add_argument("arguments", help="Operation arguments as a JSON object")
    p.add_argument("--campaign-id")
    sub.add_parser("embed", help="Build optional local semantic passage embeddings (may download public model)")
    sub.add_parser("rerank-prepare", help="Cache the optional local cross-encoder reranker model and activate it")
    p = sub.add_parser("serve", help="Serve local HTTP API for retrieval and mutable campaign play")
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--lan", action="store_true", help="Listen on all interfaces (0.0.0.0) for LAN co-op play")
    p.add_argument("--from-settings", action="store_true", help="Use bind IP/port persisted in settings.json")
    p.add_argument("--pin", default="", help="Optional room passcode required from players for mutations/live sync")
    p.add_argument("--allow-origin", action="append", default=[], help="Allow this exact browser origin to read the index (repeatable; no wildcard)")
    sub.add_parser("mcp", help="Run stdio MCP server for supporting clients")
    args = parser.parse_args()
    try:
        if args.command == "index": result = build_index(args.pdf, args.db)
        elif args.command == "search": result = search_pages(args.db, args.query, args.limit, lexical_only=args.lexical_only)
        elif args.command == "page": result = read_page(args.db, args.number, args.numbering)
        elif args.command == "phrase": result = find_phrase(args.db, args.query)
        elif args.command == "eval": result = evaluate(args.db, args.cases)
        elif args.command == "status": result = inspect_index(args.db)
        elif args.command == "catalog":
            from knowledge import catalog
            result = catalog(args.db)
        elif args.command == "build-library":
            from library import materialize_library
            result = materialize_library(args.db)
        elif args.command == "section":
            from knowledge import section
            result = section(args.db, args.section_id, args.offset, args.limit)
        elif args.command == "embed":
            from semantic import build_embeddings
            result = build_embeddings(args.db)
        elif args.command == "rerank-prepare":
            from reranker import prepare_reranker
            result = prepare_reranker(args.db)
        elif args.command == "serve":
            import uvicorn
            from urllib.parse import urlsplit
            from turnloop import load_server_settings
            srv_cfg = load_server_settings()
            origins: list[str] = []
            for raw_origin in [*(args.allow_origin or []), *(srv_cfg.get("allowed_origins") or [])]:
                cleaned_origin = str(raw_origin).strip().rstrip("/")
                if cleaned_origin and cleaned_origin not in origins:
                    origins.append(cleaned_origin)
            for origin in origins:
                parsed = urlsplit(origin)
                if (parsed.scheme not in {"http", "https"} or not parsed.netloc or
                        parsed.username is not None or parsed.password is not None or
                        parsed.path or parsed.query or parsed.fragment or "*" in origin):
                    raise ValueError("--allow-origin must be an exact HTTP(S) origin without a path or wildcard")
            if args.from_settings:
                bind_host = str(srv_cfg.get("bind_host") or "127.0.0.1")
                bind_port = int(srv_cfg.get("port") or 8765)
            else:
                bind_host = "0.0.0.0" if args.lan else (args.host or str(srv_cfg.get("bind_host") or "127.0.0.1"))
                bind_port = int(args.port if args.port is not None else (srv_cfg.get("port") or 8765))
            if bind_host in {"127.0.0.1", "localhost"}:
                local_origin = f"http://{bind_host}:{bind_port}"
                if local_origin not in origins:
                    origins.append(local_origin)
            uvicorn.run(
                make_api(
                    args.db,
                    tuple(origins),
                    args.campaign_db,
                    server_host=bind_host,
                    server_port=bind_port,
                    room_pin=args.pin,
                    allow_server_control=True,
                ),
                host=bind_host,
                port=bind_port,
            )
            return
        elif args.command == "mcp":
            serve_mcp(args.db, args.campaign_db)
            return
        elif args.command == "game":
            from gameplay import GameplayService
            if args.campaign_db.expanduser().resolve() == args.db.expanduser().resolve():
                raise ValueError("Campaign database must be separate from the rules index")
            arguments = json.loads(args.arguments)
            if not isinstance(arguments, dict):
                raise ValueError("arguments must be a JSON object")
            result = GameplayService(args.campaign_db, args.db).execute(args.action, arguments, campaign_id=args.campaign_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.command == "eval" and result["passed"] != result["total"]:
            raise SystemExit(1)
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    cli()
