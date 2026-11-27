#!/usr/bin/env python3
"""Cyberpunk RED page-aware rules search, independent of the GM model.

Only the PDF owner runs ingestion. The PDF, index and user data remain local.
Search is deterministic and returns actual source pages, never LLM-generated rules.
"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
import hashlib
import json
import os
import re
import socket
import sqlite3
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Callable, Iterator

from index_lock import index_lock
from server.coop import _CoopHub
from server.security import (
    _AUTH_JSON_MAX_BYTES,
    _JSON_MAX_BYTES,
    _JsonBodyLimitMiddleware,
    create_server_context,
)

DEFAULT_DB = Path(os.environ.get("REDKB_DB", Path.home() / ".local/share/cyberpunk-red-gm/rules.sqlite"))
STOP_WORDS = set("a an and are as at be by can could do does for from how i in into is it me of on or page pages please red rule rules show tell the this to under use using what when where with you cyberpunk corebook happens work my character book say".split())


def clean_text(text: str) -> str:
    """Normalize noisy PDF characters in queries and phrases."""
    return unicodedata.normalize("NFKC", text).replace("\u00ad", "").replace("\u200b", "").replace("\x00", "").strip()


def _sweep_stale_builds(db_path: Path) -> None:
    """Remove temporary databases left behind by a killed build (caller holds the index lock)."""
    for stale in db_path.parent.glob(db_path.name + ".building-*"):
        stale.unlink(missing_ok=True)


def _write_pages(conn: sqlite3.Connection, pages: list[dict[str, Any]]) -> tuple[int, int]:
    """Insert furniture-free page text and overlapping passages."""
    from layout import body_text
    populated = without_printed = 0
    for page in pages:
        text = body_text(page)
        if text:
            populated += 1
        printed = page.get("printed_page")
        if printed is None:
            without_printed += 1
        headings = (" ".join(b["text"].split()) for b in page["blocks"] if b.get("role") == "heading")
        header = page.get("running_header") or next(headings, "")
        conn.execute(
            "INSERT INTO pages(pdf_page, printed_page, header, text, chars) VALUES(?,?,?,?,?)",
            (page["pdf_page"], printed, header[:180], text, len(text)),
        )
        page_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        words = text.split()
        for start in range(0, len(words), 75):
            end = min(start + 150, len(words))
            conn.execute("INSERT INTO passages(page_id,start_word,end_word,text) VALUES(?,?,?,?)",
                         (page_id, start, end, " ".join(words[start:end])))
    return populated, without_printed


def write_index(
    conn: sqlite3.Connection,
    pages: list[dict[str, Any]],
    toc: list[Any],
    metadata: dict[str, str],
    emit: Callable[..., None] = lambda *a, **k: None,
) -> None:
    """Write every index table from one layout pass (``layout.read_page`` dicts)."""
    import layout
    from knowledge import build_structure
    from library import build_library

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
    count = len(pages)
    layout.merge_drop_caps(pages)
    layout.apply_hyphenation(pages)
    evidence = layout.classify_blocks(pages)
    emit("structure", 78, "Organizing Corebook chapters and sections...", current=count, total=count)
    populated, without_printed = _write_pages(conn, pages)
    build_structure(conn, toc, pages)
    for key, value in {
        "schema_version": "3",
        "extraction_method": "layout_blocks+line_tables_v2",
        "passage_window_words": "150",
        "passage_stride_words": "75",
        "pdf_page_count": str(count),
        "populated_pages": str(populated),
        "pages_without_printed_number": str(without_printed),
        "body_font_size": str(evidence["body_size"]),
        **metadata,
    }.items():
        conn.execute("INSERT INTO metadata(key,value) VALUES(?,?)", (key, value))
    emit("library", 86, "Building searchable skills, roles, gear & cyberware library...", current=count, total=count)
    build_library(conn)
    emit("fts", 94, "Building fast keyword search index...", current=count, total=count)
    conn.execute("INSERT INTO page_fts(page_fts) VALUES('rebuild')")
    conn.execute("INSERT INTO passage_fts(passage_fts) VALUES('rebuild')")


def build_index(
    pdf_path: Path,
    db_path: Path,
    *,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
    source_filename: str | None = None,
) -> dict[str, Any]:
    """Build a fresh index atomically; incomplete runs do not corrupt the old DB."""
    import pymupdf as fitz
    import layout

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
    # One build at a time per index: the lock makes sweeping stale temp files safe.
    with index_lock(db_path):
        _sweep_stale_builds(db_path)
        fd, temporary = tempfile.mkstemp(prefix=db_path.name + ".building-", dir=db_path.parent)
        os.close(fd)
        temp_path = Path(temporary)
        conn = sqlite3.connect(temp_path)
        try:
            # Hash precisely the immutable byte snapshot used for extraction.
            source_bytes = pdf_path.read_bytes()
            source_sha256 = hashlib.sha256(source_bytes).hexdigest()
            with fitz.open(stream=source_bytes, filetype="pdf") as pdf:
                count = len(pdf)
                _emit("extracting", 5, f"Reading {count} pages from Corebook PDF...", current=0, total=count)
                pages = []
                for index, page in enumerate(pdf):
                    pages.append(layout.read_page(page, index + 1))
                    if count > 0 and ((index + 1) % 5 == 0 or index + 1 == count):
                        pct = 5 + int(((index + 1) / count) * 70)
                        _emit("extracting", pct, f"Reading page {index + 1} of {count}...", current=index + 1, total=count)
                toc = pdf.get_toc() or []
            metadata = {"source_filename": source_filename or pdf_path.name, "source_sha256": source_sha256}
            if db_path.is_file():
                # Optional retrieval add-ons that do not depend on extracted text survive a rebuild.
                with closing(sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)) as old:
                    try:
                        row = old.execute("SELECT value FROM metadata WHERE key='reranker_model'").fetchone()
                    except sqlite3.Error:
                        row = None
                if row and row[0]:
                    metadata["reranker_model"] = row[0]
            write_index(conn, pages, toc, metadata, _emit)
            conn.commit()
        except BaseException:
            conn.close()
            temp_path.unlink(missing_ok=True)
            raise
        conn.close()
        _emit("saving", 98, "Saving Corebook database...", current=count, total=count)
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


_PAGE_REF = re.compile(r"(?:(pdf)\s+|printed\s+)?(?:page|pg\.?|p\.)\s*(\d+)", re.I)
# Words that may surround a bare page request without making it a content query.
_PAGE_FILLER = frozenset(
    "open read show display give pull up go to goto jump turn flip look at see check the a an of on in from is are "
    "what whats does do did say says said written there tell me about can could you i please corebook book rulebook "
    "rules rule text contents content".split())


def _page_reference(query: str) -> tuple[int, str] | None:
    """Route to a page only when the query is essentially just a page reference."""
    match = _PAGE_REF.search(query)
    if not match:
        return None
    rest = (query[:match.start()] + " " + query[match.end():]).casefold()
    if any(word not in _PAGE_FILLER for word in re.findall(r"[a-z0-9]+", rest)):
        return None
    numbering = "pdf" if match.group(1) and match.group(1).lower() == "pdf" else "printed"
    return int(match.group(2)), numbering


def search_pages(db_path: Path, query: str, limit: int = 5, *, lexical_only: bool = False) -> list[dict[str, Any]]:
    """Exact pages bypass search; otherwise rank passages lexically or with local hybrid RRF."""
    limit = max(1, min(int(limit), 20))
    page_ref = _page_reference(query)
    if page_ref is not None:
        number, numbering = page_ref
        if number < 1:
            return []
        result = read_page(db_path, number, numbering)
        if result is None:
            return []
        result["excerpt"] = _excerpt(result["text"], _terms(query))
        return [result]
    expanded_query = _expanded_vehicle_query(query)
    retrieval_query = expanded_query or query
    terms = _terms(retrieval_query)
    if not terms:
        return []
    quoted = ['"' + t.replace('"', '""') + '"' for t in terms]
    with _open(db_path) as conn:
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
    from fastapi import FastAPI
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles

    from server.routes_chat import register_chat_routes
    from server.routes_game import register_game_routes
    from server.routes_settings import register_settings_routes

    app = FastAPI(title="Cyberpunk RED Knowledge Engine", version="0.1")
    ctx = create_server_context(
        app,
        db_path,
        allowed_origins=allowed_origins,
        campaign_path=campaign_path,
        llm=llm,
        settings_path=settings_path,
        server_host=server_host,
        server_port=server_port,
        room_pin=room_pin,
        allow_server_control=allow_server_control,
        entrypoint_path=Path(__file__).resolve(),
    )

    register_settings_routes(app, ctx)
    register_game_routes(app, ctx)
    register_chat_routes(app, ctx)

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


create_app = make_api


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
