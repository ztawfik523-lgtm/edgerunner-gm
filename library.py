"""Organized Rulebook Library and campaign-scoped homebrew catalog."""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from campaign import CampaignStore, STAT_NAMES, _json
from memory import CampaignMemory
import sourcecatalog

ALLOWED_CATEGORIES = frozenset(
    {
        "skill",
        "weapon",
        "armor",
        "cyberware",
        "program",
        "hardware",
        "gear",
        "fashion",
        "role",
        "rule",
        "npc",
        "faction",
        "location",
        "vehicle",
        "drug",
        "ammo",
        "attachment",
        "housing",
        "service",
        "streetslang",
        "mook",
        "encounter",
        "screamsheet",
    }
)
_DICE_RE = re.compile(r"^\d{1,2}d(?:6|10)(?:\s*[+-]\s*\d{1,2})?$", re.I)
_CATEGORY_ALIASES = {
    "skills": "skill",
    "weapons": "weapon",
    "armors": "armor",
    "cyberwares": "cyberware",
    "programs": "program",
    "roles": "role",
    "rules": "rule",
    "npcs": "npc",
    "factions": "faction",
    "locations": "location",
    "vehicles": "vehicle",
    "drugs": "drug",
    "ammos": "ammo",
    "ammunition": "ammo",
    "attachments": "attachment",
    "housings": "housing",
    "services": "service",
    "streetslangs": "streetslang",
    "slang": "streetslang",
    "mooks": "mook",
    "opponent": "mook",
    "opponents": "mook",
    "encounters": "encounter",
    "screamsheets": "screamsheet",
    "exotic": "weapon",
    "exotics": "weapon",
}

def _slug(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-") or "entry"


def normalize_category(category: str | None) -> str | None:
    if category is None:
        return None
    if not isinstance(category, str):
        raise ValueError("category must be a string")
    value = _CATEGORY_ALIASES.get(category.strip().casefold(), category.strip().casefold())
    if value not in ALLOWED_CATEGORIES:
        raise ValueError(f"Unsupported library category: {category!r}")
    return value


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


_summarize = sourcecatalog._summarize


def _hardcoded_topup(entries: list[dict[str, Any]], digest: str) -> None:
    """TEMPORARY: append hand-typed catalog rows the extraction does not yet cover.

    Delete this function and its single call in build_library once consumers
    read rule_entries only.
    """
    import creation_catalog

    seen_pairs = {(e["category"], e["norm_name"]) for e in entries}
    seen_ids = {e["id"] for e in entries}
    for cur in creation_catalog.build_library_corebook_entries(digest):
        pair = (cur["category"], cur["norm_name"])
        if pair in seen_pairs or cur["id"] in seen_ids:
            continue
        seen_pairs.add(pair)
        seen_ids.add(cur["id"])
        entries.append(cur)


def build_library(conn: sqlite3.Connection) -> int:
    """Materialize rule_tables, rule_entries and rule_entries_fts inside an open writable rules connection."""
    conn.executescript(
        """
        DROP TABLE IF EXISTS rule_entries_fts;
        DROP TABLE IF EXISTS rule_entries;
        CREATE TABLE rule_entries (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            norm_name TEXT NOT NULL,
            category TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'corebook',
            summary TEXT NOT NULL,
            description TEXT NOT NULL,
            stats_json TEXT NOT NULL,
            tags_json TEXT NOT NULL,
            pdf_page INTEGER,
            printed_page INTEGER,
            section_id TEXT,
            source_sha256 TEXT NOT NULL,
            source_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX rule_entries_cat_idx ON rule_entries(category);
        CREATE INDEX rule_entries_norm_idx ON rule_entries(norm_name);
        CREATE VIRTUAL TABLE rule_entries_fts USING fts5(
            entry_id UNINDEXED,
            name,
            category,
            summary,
            description,
            tags_text,
            tokenize='porter unicode61'
        );
        """
    )
    tables, entries = sourcecatalog.extract(conn)
    sourcecatalog.write_rule_tables(conn, tables)
    _hardcoded_topup(entries, entries[0]["source_sha256"] if entries else
                     conn.execute("SELECT value FROM metadata WHERE key='source_sha256'").fetchone()[0])
    for entry in entries:
        conn.execute(
            """
            INSERT INTO rule_entries(
                id, name, norm_name, category, source, summary, description,
                stats_json, tags_json, pdf_page, printed_page, section_id, source_sha256, source_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                entry["id"],
                entry["name"],
                entry["norm_name"],
                entry["category"],
                entry["source"],
                entry["summary"],
                entry["description"],
                _json(entry["stats"]),
                _json(entry["tags"]),
                entry["pdf_page"],
                entry["printed_page"],
                entry["section_id"],
                entry["source_sha256"],
                _json(entry.get("source_ref") or {}),
            ),
        )
        stats_text = " ".join(f"{k} {v}" for k, v in entry["stats"].items())
        conn.execute(
            "INSERT INTO rule_entries_fts(entry_id, name, category, summary, description, tags_text) VALUES (?,?,?,?,?,?)",
            (
                entry["id"],
                entry["name"],
                entry["category"],
                entry["summary"],
                entry["description"],
                " ".join([*entry["tags"], stats_text]).strip(),
            ),
        )
    return len(entries)


def list_category(rules_path: str | Path, category: str) -> list[dict[str, Any]]:
    """Every Corebook entry in one category (no limit), in library entry shape."""
    clean = normalize_category(category)
    return [
        {**{k: e[k] for k in ("id", "name", "category", "source", "summary", "description", "stats", "tags",
                              "pdf_page", "printed_page", "section_id", "source_sha256")},
         "created_by": "corebook", "campaign_id": None}
        for e in sourcecatalog.entries(rules_path, clean)
    ]


def _row_to_entry(row: sqlite3.Row, *, campaign_id: str | None = None) -> dict[str, Any]:
    keys = set(row.keys())
    return {
        "id": row["id"],
        "name": row["name"],
        "category": row["category"],
        "source": row["source"],
        "created_by": row["created_by"] if "created_by" in keys else "corebook",
        "summary": row["summary"],
        "description": row["description"],
        "stats": json.loads(row["stats_json"]),
        "tags": json.loads(row["tags_json"]),
        "pdf_page": row["pdf_page"] if "pdf_page" in keys else None,
        "printed_page": row["printed_page"] if "printed_page" in keys else None,
        "section_id": row["section_id"] if "section_id" in keys else None,
        "source_sha256": row["source_sha256"] if "source_sha256" in keys else None,
        "campaign_id": row["campaign_id"] if "campaign_id" in keys else campaign_id,
    }


_STOPWORDS = frozenset(
    {
        "i", "me", "my", "we", "you", "your", "our", "they", "them", "their", "he", "him", "his", "she", "her",
        "a", "an", "the", "and", "or", "but", "with", "to", "of", "in", "on", "at", "by", "for", "is", "are",
        "was", "were", "be", "been", "being", "it", "its", "this", "that", "these", "those", "from", "into",
        "yo", "hey", "hi", "hello", "sup", "yes", "no", "ok", "okay", "yeah", "yep", "nah",
        "want", "wanna", "have", "has", "had", "do", "does", "did", "dont", "didnt", "doesnt",
        "wasnt", "werent", "isnt", "arent", "havent", "cant", "wont", "couldnt", "wouldnt", "shouldnt",
        "make", "made", "what", "why", "who", "where", "when", "how", "even", "there", "here", "already",
        "just", "now", "then", "some", "any", "all", "more", "very", "really", "actually", "something",
        "anything", "nothing", "smth", "idk", "wait", "tell", "ask", "asked", "asking", "look", "looking",
        "see", "saw", "seen", "get", "got", "go", "going", "went", "come", "came", "say", "said", "says",
        "talk", "talked", "talking", "question", "questions", "character", "characters", "can", "could",
        "would", "should", "will", "shall", "may", "might", "must", "not", "im", "ive", "ill", "youre",
        "thats", "about", "around", "like", "know", "think", "mean", "use", "using", "used", "try", "trying",
    }
)


def _query_tokens(query: str, *, include_fallback: bool = True) -> list[str]:
    raw = [t.casefold() for t in re.findall(r"[A-Za-z0-9]+", query) if t]
    meaningful = [t for t in raw if t not in _STOPWORDS and len(t) > 1]
    if meaningful:
        return meaningful[:12]
    return raw[:12] if include_fallback else []


def _fts_query(tokens: list[str]) -> str:
    return " OR ".join(f'"{t}"*' for t in tokens[:10])


def _matches_strict_name(entry: dict[str, Any], norm_q: str, tokens: list[str]) -> bool:
    norm_name = sourcecatalog._normalize(entry["name"])
    if len(norm_name) >= 3 and norm_q:
        if norm_q == norm_name or re.search(rf"\b{re.escape(norm_name)}\b", norm_q):
            return True
    name_words = set(re.findall(r"[a-z0-9]+", norm_name))
    tag_words = {
        w
        for t in (entry.get("tags") or [])
        for w in re.findall(r"[a-z0-9]+", sourcecatalog._normalize(str(t)))
    }
    strict_toks = [t for t in tokens if len(t) >= 3 and t not in _STOPWORDS]
    return any(tok in name_words or tok in tag_words for tok in strict_toks)


def _entry_haystack(entry: dict[str, Any]) -> str:
    stats_text = " ".join(f"{k} {v}" for k, v in (entry.get("stats") or {}).items())
    return " ".join(
        [entry["name"], entry["summary"], entry["description"], " ".join(entry.get("tags") or []), stats_text]
    ).casefold()


def _rank_entry(entry: dict[str, Any], norm_q: str, tokens: list[str]) -> tuple[int, int, int, str]:
    norm_name = sourcecatalog._normalize(entry["name"])
    hay = _entry_haystack(entry)
    name_hits = sum(1 for tok in tokens if tok in norm_name)
    hay_hits = sum(1 for tok in tokens if tok in hay)
    if norm_q and norm_name == norm_q:
        tier = 0
    elif norm_q and norm_name.startswith(norm_q):
        tier = 1
    elif norm_q and (norm_q in norm_name or (len(norm_name) >= 3 and re.search(rf"\b{re.escape(norm_name)}\b", norm_q))):
        tier = 2
    elif tokens and all(tok in norm_name for tok in tokens):
        tier = 3
    elif name_hits > 0:
        tier = 4
    else:
        tier = 5
    page = entry.get("printed_page")
    page_key = int(page) if isinstance(page, int) else 999999
    return (tier, -(name_hits * 3 + hay_hits), page_key, norm_name)


def validate_entry_payload(
    *,
    name: Any,
    category: Any,
    summary: Any = "",
    description: Any = "",
    stats: Any = None,
    tags: Any = None,
    created_by: Any = "user",
) -> dict[str, Any]:
    """Validate campaign homebrew entries against Cyberpunk RED universe bounds."""
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
        raise ValueError("name must be a nonempty string of at most 120 characters")
    clean_name = name.strip()
    clean_cat = normalize_category(category)
    if clean_cat is None:
        raise ValueError("category is required")
    if not isinstance(created_by, str) or created_by not in {"user", "gm", "ai"}:
        raise ValueError("created_by must be one of: user, gm, ai")
    if not isinstance(description, str) or len(description) > 4000:
        raise ValueError("description must be a string of at most 4000 characters")
    clean_desc = description.strip() or f"{clean_name} ({clean_cat})."
    if not isinstance(summary, str) or len(summary) > 400:
        raise ValueError("summary must be a string of at most 400 characters")
    clean_summary = summary.strip() or _summarize(clean_desc)

    if stats is None:
        stats = {}
    if not isinstance(stats, dict):
        raise ValueError("stats must be an object")
    clean_stats: dict[str, Any] = {}
    for key, val in stats.items():
        if not isinstance(key, str) or not key.strip() or len(key) > 64:
            raise ValueError("stat keys must be nonempty strings of at most 64 characters")
        if key == "stat":
            if not isinstance(val, str) or val.upper() not in STAT_NAMES:
                raise ValueError(f"stat must be one of: {', '.join(STAT_NAMES)}")
            clean_stats["stat"] = val.upper()
        elif key == "cost_multiplier":
            if isinstance(val, bool) or val not in (1, 2):
                raise ValueError("cost_multiplier must be 1 or 2")
            clean_stats["cost_multiplier"] = val
        elif key == "cost_eb":
            if isinstance(val, bool) or not isinstance(val, int) or not 0 <= val <= 1_000_000:
                raise ValueError("cost_eb must be an integer between 0 and 1,000,000")
            clean_stats["cost_eb"] = val
        elif key == "rof":
            if isinstance(val, bool) or not isinstance(val, int) or not 1 <= val <= 4:
                raise ValueError("rof must be an integer between 1 and 4")
            clean_stats["rof"] = val
        elif key == "sp":
            if isinstance(val, bool) or not isinstance(val, int) or not 0 <= val <= 25:
                raise ValueError("sp must be an integer between 0 and 25")
            clean_stats["sp"] = val
        elif key == "armor_penalty":
            if isinstance(val, bool) or not isinstance(val, int) or not -10 <= val <= 0:
                raise ValueError("armor_penalty must be an integer between -10 and 0")
            clean_stats["armor_penalty"] = val
        elif key == "hands":
            if isinstance(val, bool) or not isinstance(val, int) or not 1 <= val <= 2:
                raise ValueError("hands must be 1 or 2")
            clean_stats["hands"] = val
        elif key == "magazine":
            if isinstance(val, bool) or not isinstance(val, int) or not 1 <= val <= 200:
                raise ValueError("magazine must be an integer between 1 and 200")
            clean_stats["magazine"] = val
        elif key == "damage":
            if not isinstance(val, str) or not _DICE_RE.fullmatch(val.strip()):
                raise ValueError("damage must be a valid dice formula like 2d6 or 4d6")
            clean_stats["damage"] = val.strip().lower()
        elif key in {"hl", "humanity_loss"}:
            if isinstance(val, int) and not isinstance(val, bool):
                if not 0 <= val <= 60:
                    raise ValueError("humanity_loss must be between 0 and 60 or a dice formula")
                clean_stats[key] = val
            elif isinstance(val, str) and _DICE_RE.fullmatch(val.strip()):
                clean_stats[key] = val.strip().lower()
            else:
                raise ValueError("humanity_loss must be an integer (0..60) or dice formula like 2d6")
        else:
            if not isinstance(val, (str, int, float, bool)) or isinstance(val, str) and len(val) > 200:
                raise ValueError(f"Unsupported or oversized stat value for {key!r}")
            clean_stats[key] = val

    if clean_cat == "skill" and "stat" in clean_stats and clean_stats["stat"] not in STAT_NAMES:
        raise ValueError("Skill stat must be a valid Cyberpunk RED STAT")

    if tags is None:
        tags = []
    if not isinstance(tags, list) or len(tags) > 12 or any(not isinstance(t, str) or not t.strip() or len(t) > 40 for t in tags):
        raise ValueError("tags must be a list of at most 12 short strings")
    clean_tags = [t.strip() for t in tags]

    return {
        "name": clean_name,
        "norm_name": sourcecatalog._normalize(clean_name),
        "category": clean_cat,
        "summary": clean_summary,
        "description": clean_desc,
        "stats": clean_stats,
        "tags": clean_tags,
        "created_by": created_by,
    }


class CampaignLibrary:
    """Manage campaign-scoped homebrew / AI-created rulebook entries in campaign.sqlite."""

    def __init__(self, campaign_or_store: CampaignStore | str | Path, rules_path: str | Path | None = None):
        if isinstance(campaign_or_store, CampaignStore):
            self.store = campaign_or_store
        else:
            self.store = CampaignStore(campaign_or_store)
        self.memory = CampaignMemory(self.store)
        self.rules_path = Path(rules_path).expanduser().resolve() if rules_path else None
        if self.rules_path and self.rules_path == self.store.path.expanduser().resolve():
            raise ValueError("Campaign storage must be separate from the rules index")
        with closing(self.store._connect()) as conn:
            existing_tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('campaign_library', 'library_events')"
                )
            }
        if not {"campaign_library", "library_events"}.issubset(existing_tables):
            with closing(self.store._connect()) as conn, conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS campaign_library (
                        id TEXT PRIMARY KEY,
                        campaign_id TEXT NOT NULL REFERENCES campaigns(id),
                        name TEXT NOT NULL,
                        norm_name TEXT NOT NULL,
                        category TEXT NOT NULL,
                        source TEXT NOT NULL DEFAULT 'homebrew',
                        created_by TEXT NOT NULL DEFAULT 'user',
                        summary TEXT NOT NULL,
                        description TEXT NOT NULL,
                        stats_json TEXT NOT NULL,
                        tags_json TEXT NOT NULL,
                        revision INTEGER NOT NULL DEFAULT 1,
                        operation_id TEXT UNIQUE NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_campaign_library_camp ON campaign_library(campaign_id, category, norm_name)"
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS library_events (
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                        campaign_id TEXT NOT NULL,
                        entry_id TEXT NOT NULL,
                        operation_id TEXT UNIQUE NOT NULL,
                        payload TEXT NOT NULL,
                        result TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )

    def _reject_cross_table_op(self, conn: sqlite3.Connection, operation_id: str) -> None:
        self.store._reject_roll_id(conn, operation_id)
        if conn.execute("SELECT 1 FROM audit WHERE operation_id=?", (operation_id,)).fetchone():
            raise ValueError("operation_id was already used for a character change")

    def add_entry(
        self,
        campaign_id: str,
        *,
        name: str,
        category: str,
        operation_id: str,
        summary: str = "",
        description: str = "",
        stats: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        created_by: str = "user",
        allow_variant: bool = False,
    ) -> dict[str, Any]:
        """Create a campaign homebrew/dossier library entry, rejecting duplicates unless allow_variant=True."""
        return self._write_entry(
            campaign_id,
            name=name,
            category=category,
            operation_id=operation_id,
            summary=summary,
            description=description,
            stats=stats,
            tags=tags,
            created_by=created_by,
            allow_variant=allow_variant,
            upsert=False,
        )

    def upsert_entry(
        self,
        campaign_id: str,
        *,
        name: str,
        category: str,
        operation_id: str,
        summary: str = "",
        description: str = "",
        stats: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        created_by: str = "ai",
        allow_variant: bool = False,
    ) -> dict[str, Any]:
        """Create or update an existing campaign entry matching (campaign_id, category, norm_name)."""
        return self._write_entry(
            campaign_id,
            name=name,
            category=category,
            operation_id=operation_id,
            summary=summary,
            description=description,
            stats=stats,
            tags=tags,
            created_by=created_by,
            allow_variant=allow_variant,
            upsert=True,
        )

    def _write_entry(
        self,
        campaign_id: str,
        *,
        name: str,
        category: str,
        operation_id: str,
        summary: str,
        description: str,
        stats: dict[str, Any] | None,
        tags: list[str] | None,
        created_by: str,
        allow_variant: bool,
        upsert: bool,
    ) -> dict[str, Any]:
        if not isinstance(operation_id, str) or not operation_id.strip() or len(operation_id) > 200:
            raise ValueError("operation_id must be a nonempty string of at most 200 characters")
        has_summary = isinstance(summary, str) and bool(summary.strip())
        has_description = isinstance(description, str) and bool(description.strip())
        cleaned = validate_entry_payload(
            name=name,
            category=category,
            summary=summary,
            description=description,
            stats=stats,
            tags=tags,
            created_by=created_by,
        )
        action_name = "upsert_homebrew" if upsert else "add_homebrew"
        payload = _json(
            {
                "action": action_name,
                "campaign_id": campaign_id,
                "has_summary": has_summary,
                "has_description": has_description,
                **cleaned,
            }
        )

        if (
            not allow_variant
            and cleaned["category"] not in {"npc", "faction", "location"}
            and self.rules_path
            and self.rules_path.is_file()
        ):
            existing = search_library(
                self.rules_path,
                q=cleaned["name"],
                category=cleaned["category"],
                include_corebook=True,
                include_homebrew=False,
                limit=50,
            )
            if any(sourcecatalog._normalize(item["name"]) == cleaned["norm_name"] for item in existing):
                raise ValueError(
                    f"Cannot overwrite official Corebook {cleaned['category']} '{cleaned['name']}'; choose a distinct name or set allow_variant=True"
                )

        now = datetime.now(timezone.utc).isoformat()
        with closing(self.store._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            self._reject_cross_table_op(conn, operation_id)
            prior_event = conn.execute(
                "SELECT payload, result FROM library_events WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if prior_event is not None:
                if prior_event["payload"] != payload:
                    raise ValueError("operation_id was already used for another library change")
                return json.loads(prior_event["result"])
            prior = conn.execute("SELECT * FROM campaign_library WHERE operation_id=?", (operation_id,)).fetchone()
            if prior is not None:
                prior_record = _row_to_entry(prior)
                prior_payload = _json(
                    {
                        "action": action_name,
                        "campaign_id": prior["campaign_id"],
                        "has_summary": bool(str(prior["summary"] or "").strip()),
                        "has_description": bool(str(prior["description"] or "").strip()),
                        "name": prior["name"],
                        "norm_name": prior["norm_name"],
                        "category": prior["category"],
                        "summary": prior["summary"],
                        "description": prior["description"],
                        "stats": json.loads(prior["stats_json"]),
                        "tags": json.loads(prior["tags_json"]),
                        "created_by": prior["created_by"],
                    }
                )
                if prior_payload != payload:
                    raise ValueError("operation_id was already used for another library change")
                return prior_record
            if not conn.execute("SELECT 1 FROM campaigns WHERE id=?", (campaign_id,)).fetchone():
                raise ValueError(f"campaign not found: {campaign_id}")
            dup = conn.execute(
                "SELECT * FROM campaign_library WHERE campaign_id=? AND category=? AND norm_name=?",
                (campaign_id, cleaned["category"], cleaned["norm_name"]),
            ).fetchone()
            if dup is not None and upsert:
                existing_stats = json.loads(dup["stats_json"])
                merged_stats = {**existing_stats, **cleaned["stats"]}
                existing_tags = json.loads(dup["tags_json"])
                merged_tags = list(dict.fromkeys([*existing_tags, *cleaned["tags"]]))[:12]
                next_summary = cleaned["summary"] if (has_summary or not str(dup["summary"] or "").strip()) else dup["summary"]
                next_desc = cleaned["description"] if (has_description or not str(dup["description"] or "").strip()) else dup["description"]
                conn.execute(
                    """
                    UPDATE campaign_library
                    SET name=?, summary=?, description=?, stats_json=?, tags_json=?, revision=revision+1, operation_id=?
                    WHERE id=?
                    """,
                    (
                        cleaned["name"],
                        next_summary,
                        next_desc,
                        _json(merged_stats),
                        _json(merged_tags),
                        operation_id,
                        dup["id"],
                    ),
                )
                row = conn.execute("SELECT * FROM campaign_library WHERE id=?", (dup["id"],)).fetchone()
                result = _row_to_entry(row)
                conn.execute(
                    "INSERT INTO library_events(campaign_id, entry_id, operation_id, payload, result, created_at) VALUES (?,?,?,?,?,?)",
                    (campaign_id, result["id"], operation_id, payload, _json(result), now),
                )
                return result
            if dup and not allow_variant:
                raise ValueError(
                    f"Campaign already has homebrew {cleaned['category']} '{cleaned['name']}'"
                )
            base_id = f"homebrew:{campaign_id[:8]}:{cleaned['category']}:{_slug(cleaned['name'])}"
            entry_id = base_id
            suffix = 2
            while conn.execute("SELECT 1 FROM campaign_library WHERE id=?", (entry_id,)).fetchone():
                entry_id = f"{base_id}-{suffix}"
                suffix += 1
            conn.execute(
                """
                INSERT INTO campaign_library(
                    id, campaign_id, name, norm_name, category, source, created_by,
                    summary, description, stats_json, tags_json, revision, operation_id, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    entry_id,
                    campaign_id,
                    cleaned["name"],
                    cleaned["norm_name"],
                    cleaned["category"],
                    "homebrew",
                    cleaned["created_by"],
                    cleaned["summary"],
                    cleaned["description"],
                    _json(cleaned["stats"]),
                    _json(cleaned["tags"]),
                    1,
                    operation_id,
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM campaign_library WHERE id=?", (entry_id,)).fetchone()
            result = _row_to_entry(row)
            conn.execute(
                "INSERT INTO library_events(campaign_id, entry_id, operation_id, payload, result, created_at) VALUES (?,?,?,?,?,?)",
                (campaign_id, result["id"], operation_id, payload, _json(result), now),
            )
            return result

    def list_entries(self, campaign_id: str, *, category: str | None = None) -> list[dict[str, Any]]:
        clean_cat = normalize_category(category)
        with closing(self.store._connect()) as conn:
            if clean_cat:
                rows = conn.execute(
                    "SELECT * FROM campaign_library WHERE campaign_id=? AND category=? ORDER BY name COLLATE NOCASE, id",
                    (campaign_id, clean_cat),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM campaign_library WHERE campaign_id=? ORDER BY category, name COLLATE NOCASE, id",
                    (campaign_id,),
                ).fetchall()
            return [_row_to_entry(r) for r in rows]

    def get_entry(self, campaign_id: str, entry_id: str) -> dict[str, Any] | None:
        with closing(self.store._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM campaign_library WHERE campaign_id=? AND id=?",
                (campaign_id, entry_id),
            ).fetchone()
            return _row_to_entry(row) if row else None

    def remove_entry(self, campaign_id: str, entry_id: str) -> bool:
        if isinstance(entry_id, str) and entry_id.startswith("corebook:"):
            raise ValueError("Official Corebook entries cannot be deleted")
        with closing(self.store._connect()) as conn, conn:
            cur = conn.execute(
                "DELETE FROM campaign_library WHERE campaign_id=? AND id=?",
                (campaign_id, entry_id),
            )
            return cur.rowcount > 0


def _read_campaign_homebrew_entries(
    campaign_path: str | Path,
    campaign_id: str,
    *,
    category: str | None = None,
) -> list[dict[str, Any]]:
    camp_resolved = Path(campaign_path).expanduser().resolve()
    if not camp_resolved.is_file():
        return []
    conn = sqlite3.connect(camp_resolved.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        if not _table_exists(conn, "campaign_library"):
            return []
        if category:
            rows = conn.execute(
                "SELECT * FROM campaign_library WHERE campaign_id=? AND category=? ORDER BY name COLLATE NOCASE, id",
                (campaign_id, category),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM campaign_library WHERE campaign_id=? ORDER BY category, name COLLATE NOCASE, id",
                (campaign_id,),
            ).fetchall()
        return [_row_to_entry(r) for r in rows]
    finally:
        conn.close()


def _read_campaign_homebrew_entry(
    campaign_path: str | Path,
    campaign_id: str,
    entry_id: str,
) -> dict[str, Any] | None:
    camp_resolved = Path(campaign_path).expanduser().resolve()
    if not camp_resolved.is_file():
        return None
    conn = sqlite3.connect(camp_resolved.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        if not _table_exists(conn, "campaign_library"):
            return None
        row = conn.execute(
            "SELECT * FROM campaign_library WHERE campaign_id=? AND id=?",
            (campaign_id, entry_id),
        ).fetchone()
        return _row_to_entry(row) if row else None
    finally:
        conn.close()


def search_library(
    rules_path: str | Path | None,
    *,
    q: str = "",
    category: str | None = None,
    campaign_path: str | Path | None = None,
    campaign_id: str | None = None,
    include_corebook: bool = True,
    include_homebrew: bool = True,
    strict_names: bool = False,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Search unified Corebook and campaign homebrew entries, ranked for lookup and autocomplete."""
    clean_cat = normalize_category(category)
    query = q.strip() if isinstance(q, str) else ""
    norm_q = sourcecatalog._normalize(query) if query else ""
    tokens = _query_tokens(query, include_fallback=not strict_names)
    if strict_names and not tokens:
        return []
    bound_limit = max(1, int(limit))

    results: list[dict[str, Any]] = []
    if include_corebook and rules_path is not None:
        resolved = Path(rules_path).expanduser().resolve()
        if resolved.is_file():
            conn = sqlite3.connect(resolved.as_uri() + "?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            try:
                if query:
                    fts = " OR ".join(f'"{t}"' for t in tokens[:10]) if strict_names else _fts_query(tokens)
                    sql = (
                        "SELECT e.* FROM rule_entries_fts f "
                        "JOIN rule_entries e ON e.id = f.entry_id "
                        "WHERE rule_entries_fts MATCH ?"
                    )
                    params: list[Any] = [fts]
                    if clean_cat:
                        sql += " AND e.category = ?"
                        params.append(clean_cat)
                    sql += " ORDER BY rank LIMIT ?"
                    params.append(max(bound_limit * 6, 60))
                    try:
                        rows = conn.execute(sql, params).fetchall() if fts else []
                    except sqlite3.OperationalError:
                        rows = []
                    if not rows and not strict_names:
                        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                        like = f"%{escaped}%"
                        like_sql = ("SELECT * FROM rule_entries WHERE (name LIKE ? ESCAPE '\\' OR summary LIKE ? ESCAPE '\\'"
                                    " OR description LIKE ? ESCAPE '\\')")
                        like_params: list[Any] = [like, like, like]
                        if clean_cat:
                            like_sql += " AND category = ?"
                            like_params.append(clean_cat)
                        like_sql += " LIMIT ?"
                        like_params.append(max(bound_limit * 4, 40))
                        rows = conn.execute(like_sql, like_params).fetchall()
                elif clean_cat:
                    rows = conn.execute(
                        "SELECT * FROM rule_entries WHERE category=? ORDER BY name COLLATE NOCASE LIMIT ?",
                        (clean_cat, max(bound_limit * 4, 80)),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM rule_entries ORDER BY category, name COLLATE NOCASE LIMIT ?",
                        (max(bound_limit * 4, 80),),
                    ).fetchall()
                results.extend(_row_to_entry(r) for r in rows)
            finally:
                conn.close()

    if include_homebrew and campaign_path is not None and campaign_id:
        for item in _read_campaign_homebrew_entries(campaign_path, campaign_id, category=clean_cat):
            if tokens:
                hay = _entry_haystack(item)
                if not any(tok in hay for tok in tokens):
                    continue
            results.append(item)

    if strict_names:
        results = [item for item in results if _matches_strict_name(item, norm_q, tokens)]

    results.sort(key=lambda item: _rank_entry(item, norm_q, tokens))
    deduped: list[dict[str, Any]] = []
    seen_keys: set[tuple[Any, Any, str]] = set()
    for item in results:
        key = (
            item.get("source"),
            item.get("category"),
            sourcecatalog._normalize(str(item.get("name") or "")),
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(item)
        if len(deduped) >= bound_limit:
            break
    return deduped


def get_library_entry(
    entry_id: str,
    *,
    rules_path: str | Path | None = None,
    campaign_path: str | Path | None = None,
    campaign_id: str | None = None,
) -> dict[str, Any] | None:
    if not isinstance(entry_id, str) or not entry_id.strip():
        return None
    if entry_id.startswith("corebook:") and rules_path is not None:
        resolved = Path(rules_path).expanduser().resolve()
        if not resolved.is_file():
            return None
        conn = sqlite3.connect(resolved.as_uri() + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM rule_entries WHERE id=?", (entry_id,)).fetchone()
            return _row_to_entry(row) if row else None
        finally:
            conn.close()
        return None
    if campaign_path is not None and campaign_id:
        return _read_campaign_homebrew_entry(campaign_path, campaign_id, entry_id)
    return None
