# Technical & Developer Reference

This document is the authoritative technical reference for **Edgerunner GM** — covering architecture, storage boundaries, CLI tools, HTTP endpoints, environment variables, and verification tests.

For user-facing setup and gameplay instructions, see [README.md](../README.md) and [Player & GM Guide](PLAYER_GUIDE.md).

---

## 1. Architecture & Project Layout

| Path | Responsibility |
| :--- | :--- |
| [redkb.py](../redkb.py) | FastAPI HTTP server, CLI entry point, PDF indexer (`build_index`), BM25/RRF search, Corebook upload worker, and stdio MCP server |
| [turn_engine/](../turn_engine/) | OpenAI-compatible LLM adapter, settings/prompt persistence (`settings.json`), branching chat tree, and two-pass / single-pass turn loop |
| [library.py](../library.py) | Corebook `rule_entries` materializer and campaign-scoped homebrew catalog |
| [campaign.py](../campaign.py), [gameplay.py](../gameplay.py), [mechanics.py](../mechanics.py) | SQLite campaign store (`campaign.sqlite`), `d10`/`d6` rolls, skill checks, wound penalties, and undo history |
| [creation.py](../creation.py), [creation_reference.py](../creation_reference.py), [creation_catalog.py](../creation_catalog.py) | Character creation validation, BYOC reference assembly, gear catalogs, and AI narrative co-writer |
| [corebook_gm_data.py](../corebook_gm_data.py) | 2045 reference tables and item catalogs |
| [combat.py](../combat.py), [health.py](../health.py), [netrunning.py](../netrunning.py), [neteffects.py](../neteffects.py), [roles.py](../roles.py), [substances.py](../substances.py), [encounters.py](../encounters.py), [gear.py](../gear.py), [economy.py](../economy.py), [lifecycle.py](../lifecycle.py), [memory.py](../memory.py) | Domain mechanics, solo runtime, and campaign lifecycle modules |
| [auth.py](../auth.py) | Admin/User scrypt password auth, HMAC session tokens/cookies, rate limiting, and access policies |
| [semantic.py](../semantic.py), [reranker.py](../reranker.py), [index_lock.py](../index_lock.py), [layout.py](../layout.py), [sourcecatalog.py](../sourcecatalog.py), [knowledge.py](../knowledge.py), [benchmark.py](../benchmark.py) | Optional CPU ONNX embeddings (`BAAI/bge-small-en-v1.5`), cross-encoder reranking (`Xenova/ms-marco-MiniLM-L-6-v2`), indexing file locks, and retrieval benchmarks |
| [launcher.py](../launcher.py) | Linux user-systemd desktop launcher (`redgm-backend.service`) |
| [ui/](../ui/) | React + TypeScript + Tailwind + Vite frontend (`ui/dist/` served by `redkb.py`) |
| [sillytavern-extension/](../sillytavern-extension/) | Optional SillyTavern function-tool extension |

---

## 2. Storage & Database Boundaries

Edgerunner GM strictly separates derived Corebook data from mutable campaign data:

- **`rules.sqlite`** (default `~/.local/share/cyberpunk-red-gm/rules.sqlite`, or `/data/rules.sqlite` in Docker; override with `REDKB_DB` or `--db PATH`):
  - Derived atomically from the owner's Corebook PDF via `redkb.py index` or `POST /v1/corebook/upload`.
  - Contains `pages`, `passages`, FTS5 virtual tables, `sections`, materialized `rule_entries`, and optional dense embeddings.
  - When absent, `/health` returns `rules_indexed: false` and Freeform/Homebrew mode remains active.
- **`campaign.sqlite`** (default `~/.local/share/cyberpunk-red-gm/campaign.sqlite`, mode `0600`, or `/data/campaign.sqlite` in Docker; override with `REDGM_CAMPAIGN_DB` or `--campaign-db PATH`):
  - Stores campaigns, characters, audit trails, `chat_messages` branching trees, `turn_gm_snapshots` (branch-scoped `gm_secrets` and `clocks`), and `campaign_library` homebrew entries.
- **`settings.json`** (default `~/.local/share/cyberpunk-red-gm/settings.json`, mode `0600`, or `/data/settings.json` in Docker; override with `REDGM_SETTINGS_FILE`):
  - Persists LLM provider settings, tuning parameters, customized prompt templates, network bind/origin settings, and scrypt-hashed auth accounts.

Keep PDFs, `rules.sqlite`, `campaign.sqlite`, `settings.json`, `.env`, and play transcripts uncommitted.

---

## 3. CLI Reference (`redkb.py`)

```bash
# Start web UI + HTTP API
.venv/bin/python redkb.py serve --host 127.0.0.1 --port 8765
.venv/bin/python redkb.py serve --lan --pin 4242
.venv/bin/python redkb.py serve --from-settings

# Index Corebook PDF from CLI (alternative to Settings -> Corebook PDF upload)
.venv/bin/python redkb.py index /absolute/path/to/CPR-Corebook.pdf
.venv/bin/python redkb.py status
.venv/bin/python redkb.py build-library

# Optional local CPU semantic search & cross-encoder reranking
.venv/bin/python -m pip install -r requirements-semantic.txt
.venv/bin/python redkb.py embed
.venv/bin/python redkb.py rerank-prepare

# Direct retrieval & campaign CLI
.venv/bin/python redkb.py search "cyberdeck" --limit 5
.venv/bin/python redkb.py page 129
.venv/bin/python redkb.py game list_characters '{}'

# Optional stdio MCP server
.venv/bin/python -m pip install -r requirements-mcp.txt
.venv/bin/python redkb.py mcp
```

---

## 4. HTTP API Overview

Mutating endpoints enforce trusted-origin checks (`--allow-origin` / `allowed_origins`) and role-based auth (`admin` vs `user`) when auth is configured. A room PIN grants player access only; it never grants Admin privileges. Initial browser Admin setup requires the operator-configured `REDGM_BOOTSTRAP_TOKEN` (at least 32 characters); preconfigured Admin credentials bypass browser bootstrap. JSON request bodies are limited to 64 KiB on `/v1/auth/*` and 8 MiB on other routes; Corebook PDF uploads retain their separate 512 MiB streamed limit. Login throttling is in-memory and per server process, so public multi-worker deployments should also apply shared rate limiting at a trusted proxy. Saved-account tokens are revoked per account on password/role changes and deletion; changing a shared player passcode revokes all sessions.

Authentication details:
- Browsers authenticate with the httpOnly `redgm_token` cookie set by `/v1/auth/login`, `/v1/auth/register` and `/v1/auth/setup`. Non-browser clients (the SillyTavern extension, `gm_probe.py`) send `Authorization: Bearer <token>`. A room PIN may be sent as `X-RedGM-Pin` (or `?pin=` for EventSource).
- Shared-passcode and room-PIN sessions are all the same identity, `player`, whatever username is typed. `player` is reserved: saved accounts cannot use it, so shared players never own an account's characters.
- Account renames move character ownership and chat authorship in the same commit as the account change; deleting an account releases its characters (they become unclaimed) and clears its chat authorship.
- With no Admin, account or PIN configured, callers get admin-equivalent `open` access only when the server is bound to loopback. `redkb.py serve` refuses a non-loopback bind in that state unless `REDGM_BOOTSTRAP_TOKEN` is set; until browser setup creates the Admin, public callers are anonymous.
- Browser origins allowed for CORS and mutations are `--allow-origin` flags plus the saved `allowed_origins` setting, read on every request, so saving new origins takes effect without a restart.

- **Health & Corebook Upload:**
  - `GET /health` — Backend status, `rules_indexed`, `indexed_pages`, `lan_enabled`, `auth_enabled`
  - `GET /v1/corebook/status` — Detailed Corebook index status, `semantic_available`, and background upload/indexing `job` progress
  - `POST /v1/corebook/upload` *(Admin)* — Streams raw PDF bytes (`Content-Type: application/pdf`, optional `X-Filename` header, `?run_semantic=true`) and runs atomic indexing in a background thread (`202 Accepted`)
- **Settings & Auth:**
  - `GET /v1/auth/status`, `POST /v1/auth/setup`, `POST /v1/auth/login`, `POST /v1/auth/register`, `POST /v1/auth/logout`
  - `GET|POST /v1/auth/accounts`, `DELETE /v1/auth/accounts/{username}` *(Admin)*
  - `GET /v1/settings/public` — Non-sensitive runtime mode & tuning flags
  - `GET /v1/settings/all` *(Admin)* — Masked LLM settings, prompts + defaults, server settings, auth policy, runtime info
  - `GET|POST /v1/settings/llm`, `POST /v1/settings/llm/test` *(Admin)*
  - `POST /v1/settings/prompts` *(Admin)* — Updates any subset of `DEFAULT_PROMPT_TEMPLATES` (`max 16000` chars/field) or `{"reset": true}`
  - `POST /v1/settings/server`, `POST /v1/settings/server/restart` *(Admin)*
- **Rules, Library & Creation:**
  - `GET /v1/search`, `GET /v1/pages/{page}`, `GET /v1/phrase`, `GET /v1/catalog`, `GET /v1/sections/{section_id}`, `GET /v1/page-batch`, `GET /v1/skills`
  - `GET /v1/creation/reference`, `POST /v1/creation/ai-assist`
  - `GET /v1/library`, `GET /v1/library/{entry_id}`, `POST /v1/library/homebrew`, `DELETE /v1/library/homebrew/{entry_id}`
- **Gameplay, Chat Tree & Co-op:**
  - `POST /v1/game` — Deterministic character/campaign/dice actions (wrapped in `{ "action": ..., "result": ... }`)
  - `GET /v1/chat/tree`, `POST /v1/chat/branch`, `POST /v1/chat/turn` (SSE), `POST /v1/chat/regenerate` (SSE), `POST /v1/chat/compress`, `POST /v1/chat/delete`, `POST /v1/chat/message/update`, `GET /v1/chat/export`
  - `GET|POST /v1/campaigns/{id}/clocks`, `POST /v1/campaigns/{id}/bootstrap`, `POST /v1/campaigns/{id}/primary`, `DELETE /v1/campaigns/{id}`
  - `GET /v1/network/info`, `POST /v1/campaigns/{id}/presence`, `GET /v1/campaigns/{id}/events` (SSE)

See also: [Library & Turn Loop Internals](LIBRARY_AND_TURNLOOP.md), [Campaigns & Narrative Memory](CAMPAIGNS.md), [Gameplay & Mechanics Tools](GAMEPLAY.md).

---

## 5. Environment Variables & Docker

See [.env.example](../.env.example) for all Docker/server variables:
- `REDKB_DB`, `REDGM_CAMPAIGN_DB`, `REDGM_SETTINGS_FILE`
- `REDGM_HOST`, `REDGM_PORT`, `REDGM_PUBLIC_URL`, `REDGM_ALLOWED_ORIGINS`
- `REDGM_LLM_URL`, `REDGM_LLM_MODEL`, `REDGM_LLM_API_KEY`
- `REDGM_ADMIN_USER`, `REDGM_ADMIN_PASS`, `REDGM_USER_USER`, `REDGM_USER_PASS`, `REDGM_ROOM_PIN`
- `REDGM_BOOTSTRAP_TOKEN` — required for initial browser Admin setup; generate a random secret of at least 32 characters
- `INSTALL_SEMANTIC=true` (Docker build arg to include `requirements-semantic.txt`)

---

## 6. Verification & Tests

```bash
# Web UI unit tests & strict TypeScript/Vite build
cd ui && npm test -- --run && npm run build

# Targeted Python API, auth/settings, creation, library, campaign, gameplay & turnloop tests
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests/test_creation.py tests/test_creation_catalog.py tests/test_library.py tests/test_campaign.py tests/test_api.py tests/test_gameplay.py tests/test_gameplay_api.py tests/test_auth_and_settings.py tests/test_turnloop.py tests/test_launcher.py -q

# SillyTavern extension contract tests
node tests/test_extension.mjs

# Retrieval benchmark (requires an indexed rules.sqlite)
.venv/bin/python benchmark.py tests/corebook_goldens.json tests/natural_language_goldens.json tests/corebook_questions.json
```
