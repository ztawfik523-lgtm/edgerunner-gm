# Gameplay & Mechanics Tools

The backend owns dice rolls, skill checks, character stats, HP, Humanity, LUCK, money, inventory, and undo history. The AI GM applies changes during play through the two-pass turn loop (`turn_engine/`) or tool calls, recording before/after snapshots for every mutation.

## Interfaces

- **Web UI (`ui/`):** Calls `POST /v1/chat/turn` (streaming SSE) and `POST /v1/game` (wrapped in `{ "result": ... }`).
- **HTTP API:** `POST /v1/game` with `{ "action": "...", "arguments": {...} }` and optional `campaign_id`.
- **Stdio MCP & SillyTavern:** Exposes `game_action` and `campaign_action`.
- **CLI:**
  ```bash
  .venv/bin/python redkb.py game list_characters '{}'
  .venv/bin/python redkb.py game roll_dice '{"count":2,"sides":6,"reason":"damage","operation_id":"unique-roll-1"}'
  .venv/bin/python redkb.py game history '{"character_id":"CHARACTER-ID"}'
  .venv/bin/python redkb.py game undo '{"character_id":"CHARACTER-ID","expected_revision":2,"reason":"reverse mistaken change","operation_id":"unique-undo-1"}'
  ```

## `game_action` Operations

- `create_character`: `name`, `stats` (`INT`, `REF`, `DEX`, `TECH`, `COOL`, `WILL`, `LUCK`, `MOVE`, `BODY`, `EMP`), optional `skills`, `operation_id`.
- `list_characters` / `get_character`: Read stored sheets.
- `update_character`: `character_id`, `expected_revision`, `changes` (`hp`, `money`, `inventory`), `reason`, `operation_id`.
- `update_character_profile`: Updates `character.detail` (`backstory`, `lifepath`, `appearance`, `roles`).
- `history` / `undo`: Read before/after snapshots and reverse the latest change with a compensating event (undoing an undo restores that change).
- `roll_dice`: `count`, `sides`, `reason`, `operation_id`.
- `skill_check`: `character_id`, `expected_revision`, `stat`, `skill` (or `null` if untrained), `dv`, `reason`, `operation_id`, plus optional `modifier`, `luck`, `complementary`, `extra_time`.

Stale revisions are rejected. Reusing an `operation_id` returns the saved result without rerolling or spending LUCK again.

## Rules & Modules

- **Starting HP & Humanity:** Starting HP is `10 + 5 * ceil((BODY + WILL) / 2)` (Corebook p. 79); starting Humanity is `EMP * 10` (p. 80).
- **Exploding d10s:** Checks strictly exceed the DV. A natural `10` adds one `d10`; a natural `1` subtracts one `d10` without recursion or automatic success/failure (pp. 129–130).
- **Wound Penalties & LUCK:** `skill_check` reads stored stats/skills, applies wound penalties automatically (p. 186), and deducts declared LUCK atomically.
- **Corebook required:** Character creation, gear purchases, hustles, and monthly housing and lifestyle costs read the indexed Corebook and fail with an error without it. `housing` and `lifestyle` take the book's names (for example `Cargo Container` and `Kibble`).
- **Encounter NPCs:** The GM or user supplies each NPC's stat block: `name`, `stats` (`REF`, `DEX`, `BODY`, `WILL`, `MOVE`), `hp`, `weapons`, and optionally `skills`, `sp_body`, `sp_head`.
- **Creation & Domain Modules:** `creation.py` and `creation_reference.py` handle `streetrat`, `edgerunner`, and `complete_package` builds. Domain mechanics live in `combat.py`, `health.py`, `netrunning.py`, `neteffects.py`, `roles.py`, `substances.py`, `encounters.py`, `gear.py`, `economy.py`, and `lifecycle.py`.

## Storage & Access Control

- State lives in `campaign.sqlite` (default `~/.local/share/cyberpunk-red-gm/campaign.sqlite`, mode `0600`). Override with `REDGM_CAMPAIGN_DB` or `--campaign-db PATH`.
- When hosting on LAN or Docker (`--lan` or `0.0.0.0`), enable Admin/Player authentication (`auth.py`, configured via `.env` or the browser setup modal) and/or a room `--pin`.
