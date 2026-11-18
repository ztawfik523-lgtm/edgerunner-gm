# Gameplay & Mechanics Tools

The backend owns all deterministic dice rolls, skill checks, character stats, HP, Humanity, LUCK, money, inventory, and audit/undo history. The AI GM can apply changes directly during play via the two-pass turn loop (`turnloop.py`) or tool calls, with full before/after snapshots and compensating undo.

## Interfaces

- **Web UI (`ui/`):** Calls `POST /v1/chat/turn` (streaming SSE) and `POST /v1/game` (wrapped in `{ "result": ... }`).
- **HTTP API:** `POST /v1/game` with `{ "action": "...", "arguments": {...} }` (plus optional `campaign_id`).
- **Stdio MCP & Legacy SillyTavern:** Exposes `game_action` and `campaign_action`.
- **CLI:**
  ```bash
  .venv/bin/python redkb.py game list_characters '{}'
  .venv/bin/python redkb.py game roll_dice '{"count":2,"sides":6,"reason":"damage","operation_id":"unique-roll-1"}'
  .venv/bin/python redkb.py game history '{"character_id":"CHARACTER-ID"}'
  .venv/bin/python redkb.py game undo '{"character_id":"CHARACTER-ID","expected_revision":2,"reason":"reverse mistaken change","operation_id":"unique-undo-1"}'
  ```

## Core `game_action` Operations

- `create_character`: `name`, `stats` (`INT`, `REF`, `DEX`, `TECH`, `COOL`, `WILL`, `LUCK`, `MOVE`, `BODY`, `EMP`), optional `skills`, `operation_id`.
- `list_characters` / `get_character`: Inspect stored sheets.
- `update_character`: `character_id`, `expected_revision`, `changes` (`hp`, `money`, `inventory`), `reason`, `operation_id`.
- `update_character_profile`: Updates `character.detail` (`backstory`, `lifepath`, `appearance`, `roles`) separately from numeric sheet stats.
- `history` / `undo`: Inspect before/after snapshots and reverse the latest change via a compensating event (undoing an undo restores that change).
- `roll_dice`: `count`, `sides`, `reason`, `operation_id`.
- `skill_check`: `character_id`, `expected_revision`, `stat`, `skill` (or `null` if untrained), `dv`, `reason`, `operation_id`, plus optional `modifier`, `luck`, `complementary`, `extra_time`.

Stale revisions are rejected, not overwritten. Reuse an `operation_id` only for an identical retry so the backend returns the saved result without rerolling or spending LUCK again.

## Rules & Boundaries

- **Starting HP & Humanity:** Starting HP is `10 + 5 * ceil((BODY + WILL) / 2)` (Corebook p. 79); starting Humanity is `EMP * 10` (p. 80).
- **Exploding d10s:** Checks strictly exceed the DV. A natural `10` adds one `d10`; a natural `1` subtracts one `d10` without recursion or automatic success/failure (pp. 129–130).
- **Wound Penalties & LUCK:** `skill_check` reads stored stats/skills, applies wound penalties automatically (p. 186), and deducts declared LUCK atomically.
- **Character Creation & Domain Modules:** `creation.py` / `creation_reference.py` handle `streetrat`, `edgerunner`, `complete_package` (when Corebook PDF is indexed via BYOC), and `freeform` builds. Additional domain mechanics live in `combat.py`, `health.py`, `netrunning.py`, `neteffects.py`, `roles.py`, `substances.py`, `encounters.py`, `gear.py`, `economy.py`, and `lifecycle.py`.

## Storage & Access Control

- State lives in `campaign.sqlite` (default `~/.local/share/cyberpunk-red-gm/campaign.sqlite`, mode `0600`), separate from the replaceable BYOC `rules.sqlite` index.
- Override with `REDGM_CAMPAIGN_DB` or global `--campaign-db PATH`.
- When hosting on LAN or Docker (`--lan` / `0.0.0.0`), enable Admin/User authentication in `auth.py` (via `.env` or the browser setup modal) and/or a room `--pin`. Never commit databases, `.env`, logs, or play transcripts.
