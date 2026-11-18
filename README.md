# Edgerunner GM

Run solo or co-op **Cyberpunk RED (2045)** campaigns with an AI Game Master. A React web workspace connects to a local Python and SQLite backend that handles dice rolls, skill checks, character sheets, campaign history, and optional Corebook search.

## Bring Your Own Corebook

This repository includes no Corebook PDF, rulebook prose, or private campaign data.

Out of the box (`rules_indexed: false`), you can run full campaigns in **Freeform & Homebrew mode**:
- Play solo or LAN co-op sessions in the web UI with the two-pass AI turn loop.
- Build Freeform characters with custom stats, skills, gear, lifepath, and optional AI backstory assist.
- Create and search campaign-scoped homebrew entries (`npc`, `faction`, `location`, `skill`, `weapon`, `armor`, `cyberware`, `program`, `hardware`, `gear`, `fashion`, `role`, `rule`) stored in `campaign.sqlite`.
- Roll server-side `d10`/`d6` checks with wound penalties, LUCK spend, Overclock (`-2` Humanity for `+2` on a check), revision-checked state patches, and undo history.

Indexing your own legally owned Cyberpunk RED Corebook PDF (`rules_indexed: true`) adds:
- Exact printed/PDF page lookup (`/v1/page/{page}`) and passage-level BM25 search (`/v1/search`), plus optional local CPU semantic search and cross-encoder reranking.
- Materialized rulebook entries in `rules.sqlite` for the Library browser and AI rule citations.
- `Streetrat`, `Edgerunner`, and `Complete Package` character creation with extracted role STAT templates, role skill packages, and Corebook skills.

```bash
.venv/bin/python redkb.py index /absolute/path/to/CPR-Corebook.pdf
```

> *Edgerunner GM is unofficial content provided under the Homebrew Content Policy of R. Talsorian Games and is not approved or endorsed by RTG. This content references materials that are the property of R. Talsorian Games and its licensees.*

## Features

- **Web Workspace (`ui/`):** Split-pane layout with a live Character Sheet (`Sheet`, `Bio`, `History`, `Inventory`), Campaign Panel, Rulebook & Homebrew Library, Command Palette (`Ctrl+K`), World Clocks, and a pre-roll LUCK stepper.
- **Character & Campaign Builders:** Sheet-style Character Creator (`CharacterCreatorModal.tsx`) with hover rules breakdowns and Lifepath generation, plus a Campaign Architect (`CampaignCreatorModal.tsx`) with Beat Chart hooks.
- **Two-Pass Turn Loop (`turnloop.py`):** Connects to any OpenAI-compatible `/v1/chat/completions` endpoint (Ollama, llama.cpp, KoboldCpp, OpenRouter, NVIDIA NIM, etc.). Pass 1 plans checks and state updates at low temperature, Python validates and executes them, and Pass 2 streams narration grounded in the results. Includes a `GM Quality` / `GM Balanced` toggle and a post-turn Chronicler pass.
- **Branching Chat Tree:** Edit messages in-place, swipe or regenerate GM replies with optional Director Notes, delete subtrees, compress long branches into Library dossiers, and export Markdown or JSON transcripts.
- **LAN Co-op & Auth (`auth.py`):** Host on local Wi-Fi (`--lan`, optional `--pin`) with live SSE party updates and character seat claiming, plus optional Admin and Player accounts.
- **Local Semantic Search (`semantic.py`, `reranker.py`):** Optional CPU-only `BAAI/bge-small-en-v1.5` embeddings fused with BM25 via reciprocal-rank fusion, plus `Xenova/ms-marco-MiniLM-L-6-v2` cross-encoder reranking.

## Quick Start

### Local Setup

```bash
git clone https://github.com/ztawfik523-lgtm/edgerunner-gm.git
cd edgerunner-gm

python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

npm --prefix ui install
npm --prefix ui run build

.venv/bin/python redkb.py serve --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765` and configure your AI provider in the top-right settings dialog.

For local Wi-Fi co-op:

```bash
.venv/bin/python redkb.py serve --lan --pin 4242
```

### Corebook Indexing & Optional Semantic Search

```bash
.venv/bin/python redkb.py index /absolute/path/to/CPR-Corebook.pdf
.venv/bin/python redkb.py status
```

To add local CPU semantic search and reranking:

```bash
.venv/bin/python -m pip install -r requirements-semantic.txt
.venv/bin/python redkb.py embed
.venv/bin/python redkb.py rerank-prepare
```

Override the rules database path with `REDKB_DB` or `--db /path/to/rules.sqlite` before the subcommand, and the campaign database with `REDGM_CAMPAIGN_DB` or `--campaign-db /path/to/campaign.sqlite`. Re-run `embed` and `rerank-prepare` after rebuilding `rules.sqlite`.

### Docker Compose

Multi-arch (`linux/amd64`, `linux/arm64`) setup with persistent `/data` storage and environment or browser-based Admin/Player setup (see [.env.example](.env.example)):

```bash
cp .env.example .env
docker compose up -d --build
```

Set `INSTALL_SEMANTIC=true` in `.env` to include local ONNX semantic retrieval in the image.

### Linux Desktop Launcher

Install a user-level systemd service (`redgm-backend.service`) and desktop entry (see [launcher guide](docs/LAUNCHER.md)):

```bash
.venv/bin/python launcher.py install
.venv/bin/python launcher.py start
```

### Optional MCP & SillyTavern Extension

- **Stdio MCP:**
  ```bash
  .venv/bin/python -m pip install -r requirements-mcp.txt
  .venv/bin/python redkb.py mcp
  ```
- **SillyTavern Extension:** See [sillytavern-extension/README.md](sillytavern-extension/README.md) and `gm_probe.py`.

## Project Layout

| Path | Role |
| :--- | :--- |
| `redkb.py` | FastAPI server, CLI entry point, PDF indexer, BM25/RRF search, and MCP server |
| `turnloop.py` | OpenAI-compatible LLM client, branching chat tree, and two-pass turn engine |
| `library.py` | Organized Rulebook Library materializer and campaign homebrew catalog |
| `campaign.py`, `gameplay.py`, `mechanics.py` | Campaign store (`campaign.sqlite`), dice/skill checks, character state, and undo history |
| `creation.py`, `creation_reference.py`, `creation_catalog.py` | Character creation validation, BYOC reference assembly, and gear/AI-assist catalogs |
| `corebook_gm_data.py` | 2045 reference tables and item catalogs |
| `combat.py`, `health.py`, `netrunning.py`, `neteffects.py`, `roles.py`, `substances.py`, `encounters.py`, `gear.py`, `economy.py`, `lifecycle.py`, `memory.py` | Domain mechanics and campaign lifecycle modules |
| `auth.py` | Admin/Player authentication, HMAC session cookies, and `settings.json` |
| `semantic.py`, `reranker.py`, `index_lock.py`, `layout.py`, `sourcecatalog.py`, `knowledge.py`, `benchmark.py` | Optional local ONNX embeddings, cross-encoder reranking, indexing locks, and benchmarks |
| `launcher.py` | Linux user-systemd desktop launcher |
| `ui/` | React, TypeScript, Tailwind, and Vite frontend |
| `tests/` | Python (`pytest`), UI (`vitest`), and extension (`node`) test suites |
| `docs/` | API, launcher, campaign, and gameplay documentation |
| `sillytavern-extension/` | Optional SillyTavern function-tool extension |

## Verification

Web UI tests and production build:

```bash
cd ui && npm test -- --run && npm run build
```

Core Python API, BYOC, creation, library, campaign, gameplay, and auth tests:

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests/test_creation.py tests/test_creation_catalog.py tests/test_library.py tests/test_campaign.py tests/test_api.py tests/test_gameplay.py tests/test_gameplay_api.py tests/test_auth_and_settings.py tests/test_turnloop.py tests/test_launcher.py -q
```

SillyTavern extension contract tests:

```bash
node tests/test_extension.mjs
```

Retrieval benchmark (requires a locally indexed `rules.sqlite`):

```bash
.venv/bin/python benchmark.py tests/corebook_goldens.json tests/natural_language_goldens.json tests/corebook_questions.json
```

## Documentation

- [Library, Turn Loop & HTTP API](docs/LIBRARY_AND_TURNLOOP.md)
- [Linux One-Click Launcher](docs/LAUNCHER.md)
- [Campaigns & Narrative Memory](docs/CAMPAIGNS.md)
- [Gameplay & Mechanics Tools](docs/GAMEPLAY.md)

Keep your Corebook PDF, `rules.sqlite`, `campaign.sqlite`, `.env`, credentials, and play transcripts uncommitted.
