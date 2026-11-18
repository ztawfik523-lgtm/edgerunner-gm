# Edgerunner GM

**Edgerunner GM** is a self-hosted, model-agnostic AI Game Master and tabletop companion for **Cyberpunk RED (2045)** built around a **Bring-Your-Own-Corebook (BYOC)** architecture. It pairs a React/TypeScript web workspace with a deterministic Python/SQLite backend that owns dice rolls, skill checks, character sheets, campaign state, branching chat trees, and optional local Corebook retrieval.

> Repository: [`ztawfik523-lgtm/edgerunner-gm`](https://github.com/ztawfik523-lgtm/edgerunner-gm)

---

## Bring Your Own Corebook (BYOC) & Homebrew Policy

This repository **does not include** any copyrighted Corebook PDF, full rulebook prose, or private campaign databases.

### What works out of the box (`rules_indexed: false`)
You can run **Edgerunner GM** immediately without a PDF:
- **Full Web UI & AI Turn Loop:** Create campaigns, play solo or co-op sessions, stream GM turns, branch/swipe/edit messages, and track world clocks.
- **Freeform Character Creation:** Build characters with custom stats, skills, gear, lifepath, and AI-assisted backstory/contacts.
- **Campaign-Scoped Homebrew Library:** Create, search, and manage custom `npc`, `faction`, `location`, `skill`, `weapon`, `armor`, `cyberware`, `program`, `hardware`, `gear`, `fashion`, `role`, and `rule` entries per campaign (`campaign.sqlite`).
- **Deterministic Mechanics & Reference Catalogs:** Server-side `d10`/`d6` dice, wound penalties, LUCK spending, Overclock (`-2` Humanity for `+2` check bonus), revision-checked state patches, undo history, and structured reference catalogs (`corebook_gm_data.py`, `creation_catalog.py`).

### What unlocks when you index your own Corebook (`rules_indexed: true`)
Index your own legally owned Cyberpunk RED Corebook PDF locally:

```bash
.venv/bin/python redkb.py index /absolute/path/to/CPR-Corebook.pdf
```

Indexing builds a local derived SQLite database (`rules.sqlite`, default `~/.local/share/cyberpunk-red-gm/rules.sqlite`) and unlocks:
- **Exact Page & Full-Text Search:** Printed/PDF page lookup (`/v1/page/{page}`) and passage-level BM25 search (`/v1/search`), plus optional CPU-only local semantic search & cross-encoder reranking.
- **Organized Rulebook Library:** Materialized `rule_entries` and `rule_entries_fts` tables inside `rules.sqlite` for instant browsing and AI turn-loop rule citations.
- **Corebook Character Creation Methods:** Unlocks `Streetrat`, `Edgerunner`, and `Complete Package` in the Character Creator (`CharacterCreatorModal.tsx`) using extracted role STAT templates, role skill packages, and Corebook skills alongside `Freeform`.

> *Edgerunner GM is unofficial content provided under the Homebrew Content Policy of R. Talsorian Games and is not approved or endorsed by RTG. This content references materials that are the property of R. Talsorian Games and its licensees.*

---

## Key Features

- **Custom React + TypeScript Web UI (`ui/`):**
  - Split-pane tabletop layout with live **Character Sheet** (`Sheet`, `Bio`, `History`, `Inventory`), **Campaign Panel**, **Rulebook & Homebrew Library**, and **Command Palette** (`Ctrl+K`).
  - **Character Creator (`CharacterCreatorModal.tsx`):** Sheet-style builder with hover/focus rules breakdowns, Lifepath generation, shopping/loadout cart, and AI backstory/contact expansion.
  - **Campaign Architect (`CampaignCreatorModal.tsx`):** Guided campaign setup with districts, Beat Chart structure, and starter bootstrapping.
  - **World Clocks & Pre-Roll LUCK:** Track public/secret campaign clocks per branch and commit pre-roll LUCK spend on primary checks.
- **Model-Agnostic Two-Pass AI Turn Loop (`turnloop.py`):**
  - Works with any OpenAI-compatible `/v1/chat/completions` endpoint (Ollama, llama.cpp, KoboldCpp, OpenRouter, NVIDIA NIM, etc.).
  - **Two-Pass Execution:** Pass 1 plans structured checks, state operations, and homebrew proposals at low temperature; Python validates and executes them deterministically; Pass 2 streams narration grounded in the locked results. Includes a `GM Quality` / `GM Balanced` thinking toggle and a post-turn Chronicler pass.
  - **Branching Chat Tree:** Edit messages in-place, swipe/regenerate GM replies with optional Director Notes, delete subtrees, compress long branches into Library dossiers, and export Markdown/JSON transcripts.
- **Co-op / LAN & Role-Based Access (`auth.py`):**
  - Host on local Wi-Fi/LAN (`--lan`, optional `--pin`) with live SSE party updates and character seat claiming (`CoopModal.tsx`).
  - Optional Admin vs. User sign-in accounts (`AuthGateModal.tsx`) with HMAC-signed cookies and an Admin Control Center (`SettingsModal.tsx`: `Connection`, `Tuning`, `Prompts`, `Network`, `Access`).
- **Optional Local Semantic Search & Reranking (`semantic.py`, `reranker.py`):**
  - CPU-only `BAAI/bge-small-en-v1.5` embeddings (via FastEmbed) fused with BM25 via reciprocal-rank fusion, plus `Xenova/ms-marco-MiniLM-L-6-v2` cross-encoder reranking. No rulebook text is sent to remote embedding or reranking services.

---

## Quick Start

### 1. Local Setup (Backend + Web UI)

```bash
git clone https://github.com/ztawfik523-lgtm/edgerunner-gm.git
cd edgerunner-gm

python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

npm --prefix ui install
npm --prefix ui run build
```

Start the combined backend + Web UI server on loopback:

```bash
.venv/bin/python redkb.py serve --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765` in your browser and configure your AI provider in the top-right settings dialog.

For local Wi-Fi / LAN co-op play with friends:

```bash
.venv/bin/python redkb.py serve --lan --pin 4242
```

### 2. Index Your Corebook PDF (Optional BYOC Step)

```bash
.venv/bin/python redkb.py index /absolute/path/to/CPR-Corebook.pdf
.venv/bin/python redkb.py status
```

To enable local CPU semantic search and cross-encoder reranking (optional):

```bash
.venv/bin/python -m pip install -r requirements-semantic.txt
.venv/bin/python redkb.py embed
.venv/bin/python redkb.py rerank-prepare
```

> Override the rules database location with `REDKB_DB` or `--db /path/to/rules.sqlite` before the subcommand, and the campaign database with `REDGM_CAMPAIGN_DB` or `--campaign-db /path/to/campaign.sqlite`. Indexing replaces derived data, so re-run `embed` and `rerank-prepare` after rebuilding `rules.sqlite`.

### 3. Docker Compose (Self-Hosting)

Multi-arch (`linux/amd64` and `linux/arm64`) setup with persistent `/data` storage and environment-based or browser-based Admin/User setup (see [.env.example](.env.example)):

```bash
cp .env.example .env
# Edit .env as needed (set INSTALL_SEMANTIC=true to include local ONNX semantic retrieval)
docker compose up -d --build
```

### 4. Linux One-Click Desktop Launcher (Optional)

For daily local use via a single user-level systemd unit (`redgm-backend.service`) and desktop entry (see [launcher guide](docs/LAUNCHER.md)):

```bash
.venv/bin/python launcher.py install
.venv/bin/python launcher.py start
```

### 5. Optional MCP & Legacy SillyTavern Extension

- **Stdio MCP:**
  ```bash
  .venv/bin/python -m pip install -r requirements-mcp.txt
  .venv/bin/python redkb.py mcp
  ```
- **Legacy SillyTavern Extension:** See [sillytavern-extension/README.md](sillytavern-extension/README.md) and `gm_probe.py` for driving SillyTavern's function-calling proxy against `redkb.py serve --allow-origin http://127.0.0.1:8000`.

---

## Repository Layout

| Path | Purpose |
| :--- | :--- |
| `redkb.py` | FastAPI HTTP server, CLI entry point, PDF indexer, BM25/RRF search, and optional MCP server |
| `turnloop.py` | Model-agnostic OpenAI-compatible LLM adapter, branching chat tree, and two-pass/chronicler turn engine |
| `library.py` | Organized Rulebook Library materializer and campaign-scoped homebrew catalog |
| `campaign.py`, `gameplay.py`, `mechanics.py` | Campaign persistence (`campaign.sqlite`), deterministic dice/skill checks, character state, and audit/undo history |
| `creation.py`, `creation_reference.py`, `creation_catalog.py` | Character creation validation, Corebook/BYOC reference assembly, and armory/gear/AI-assist catalogs |
| `corebook_gm_data.py` | Structured 2045 GM reference tables, opponents/mooks, encounters, and item catalogs |
| `combat.py`, `health.py`, `netrunning.py`, `neteffects.py`, `roles.py`, `substances.py`, `encounters.py`, `gear.py`, `economy.py`, `lifecycle.py`, `memory.py` | Domain mechanics, solo action ledger, and campaign lifecycle modules |
| `auth.py` | Role-based Admin/User authentication, HMAC session cookies, and persistent `settings.json` |
| `semantic.py`, `reranker.py`, `index_lock.py`, `layout.py`, `sourcecatalog.py`, `knowledge.py`, `benchmark.py` | Optional local FastEmbed/ONNX semantic search, cross-encoder reranking, indexing locks, and retrieval benchmarks |
| `launcher.py` | Linux user-systemd desktop launcher |
| `ui/` | React + TypeScript + Tailwind + Vite web frontend |
| `tests/` | Python (`pytest`), UI (`vitest`), and extension (`node`) test suites |
| `docs/` | Architecture, deployment, API, and historical development docs |
| `sillytavern-extension/` | Optional legacy SillyTavern function-tool extension |

---

## Verification

Run the Web UI unit tests and production TypeScript/Vite build:

```bash
cd ui && npm test -- --run && npm run build
```

Run the core Python API, BYOC, creation, library, campaign, gameplay, and auth tests (requires `requirements-dev.txt`; no Corebook PDF needed):

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests/test_creation.py tests/test_creation_catalog.py tests/test_library.py tests/test_campaign.py tests/test_api.py tests/test_gameplay.py tests/test_gameplay_api.py tests/test_auth_and_settings.py -q
```

Run the optional SillyTavern extension contract tests:

```bash
node tests/test_extension.mjs
```

If you have a local `rules.sqlite` indexed from your Corebook PDF, you can also run the retrieval benchmark:

```bash
.venv/bin/python benchmark.py tests/corebook_goldens.json tests/natural_language_goldens.json tests/corebook_questions.json
```

---

## Documentation

- [Library, Turn Loop & HTTP API](docs/LIBRARY_AND_TURNLOOP.md)
- [Linux One-Click Launcher](docs/LAUNCHER.md)
- [Campaigns & Narrative Memory](docs/CAMPAIGNS.md)
- [Gameplay & Mechanics Tools](docs/GAMEPLAY.md)

Never commit your Corebook PDF, `rules.sqlite`, `campaign.sqlite`, `.env`, credentials, or private play transcripts.
