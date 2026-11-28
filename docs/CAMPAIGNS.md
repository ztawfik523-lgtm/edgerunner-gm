# Campaigns & Narrative Memory

Edgerunner GM stores campaigns, characters, branching chat trees, world clocks, and campaign-scoped homebrew in `campaign.sqlite`. The Corebook index built from your own PDF, which the app requires, lives separately in `rules.sqlite`.

## Web UI Workflow

1. **Create or select a campaign:** Open the **Campaign Architect** (`New` in the top bar) or pick an existing campaign from the top-bar selector. The Campaign Architect can bootstrap starter world data, Beat Chart hooks, and notes using your configured LLM. Districts, corporations, gangs, zone types, threat ratings and screamsheet headline words come from your Corebook. **Suggest Caper Outlines** and **Suggest Screamsheet Hooks** ask your model for new ideas grounded in that lore; pick one to fill the caper style and Beat Chart, or the hook field. Without a reachable model they show an error instead of stock text.
2. **Attach characters:** Build characters in the **Character Creator** (`Streetrat`, `Edgerunner`, or `Complete Package`, all read from your indexed Corebook) and attach them to the campaign. Each character belongs to one campaign.
3. **Start a session:** Use the session-start control in the top bar to refill all attached characters' LUCK in one transaction. Reopening the browser or restarting the server resumes saved state without refilling LUCK.
4. **Branching & Timeline Controls:**
   - Messages are stored in `chat_messages` as a tree.
   - Edit messages in-place, swipe or regenerate GM replies (with optional Director Notes), or switch branches. `revision_mismatch` warns when the active leaf's saved `(campaign_revision, solo_revision)` lags behind the live database.
   - **Compress to Library** (`POST /v1/chat/compress`) distills a branch into `npc`, `faction`, `location`, item, or rule dossiers in the campaign's Homebrew Library.
   - Public and branch-scoped secret **World Clocks** track timers per timeline leaf.

## Encounters

The GM can build combatants from the Corebook's NPC stat blocks by name (mooks, lieutenants, mini bosses and the boss), overriding any value, or supply a complete stat block for other NPCs. Gang and Night City people write-ups appear in the Library as `faction` and `npc` entries.

## Memory & State Boundaries

- **Narrative memory:** Scene, summary, NPCs, objectives, discoveries, unresolved threads, and `[Category: Name]`-cited compressions live in `campaign.sqlite` and are updated by the two-pass turn loop and post-turn Chronicler pass.
- **Mechanical state:** Character stats, HP, Humanity, LUCK, money, inventory, and dice results are owned by the backend (`campaign.py`, `gameplay.py`, `mechanics.py`).
- **Undo & retries:** State updates require `expected_revision`, `reason`, and `operation_id`. Retrying with the same `operation_id` returns the saved result; narrative undo appends a compensating event while preserving history.

## Storage

Campaigns are saved in `campaign.sqlite` (default `~/.local/share/cyberpunk-red-gm/campaign.sqlite`, mode `0600`, or `/data/campaign.sqlite` in Docker). Override with `REDGM_CAMPAIGN_DB` or `--campaign-db PATH`.

## Optional SillyTavern Extension

When using the [SillyTavern extension](../sillytavern-extension/README.md), chat slash commands bind a SillyTavern chat to a campaign:

- `/red-campaign create <name>` / `/red-campaign list` / `/red-campaign use <id>`
- `/red-session` (refills attached characters' LUCK)
- `/red-campaign status` / `/red-campaign refresh` / `/red-campaign unbind`
- `/red-history` / `/red-undo`

See [Library & Turn Loop](LIBRARY_AND_TURNLOOP.md) for the HTTP API endpoints used by the Web UI.
