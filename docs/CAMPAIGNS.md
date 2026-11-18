# Campaigns & Narrative Memory

Edgerunner GM persists campaigns, characters, branching chat trees, world clocks, and campaign-scoped homebrew in `campaign.sqlite`, separate from the optional BYOC `rules.sqlite` Corebook index.

## Web UI Campaign Workflow

1. **Create or select a campaign:** Use the **Campaign Architect** (`New` in the top bar) or select an existing campaign from the top-bar dropdown. The Campaign Architect bootstraps world data, Beat Chart hooks, and starter notes using any OpenAI-compatible LLM.
2. **Attach characters:** Create characters in the **Character Creator** (`Streetrat`, `Edgerunner`, `Complete Package` when Corebook PDF is indexed, or `Freeform` at any time) and attach them to the campaign. Each character belongs to one campaign.
3. **Start a session:** Click the session-start button in the top bar to refill all attached characters' LUCK in one transaction. Reopening the browser or restarting the server resumes saved state without a refill.
4. **Branching & Timeline Controls:**
   - Every chat message is stored in `chat_messages` as a branching tree.
   - Edit messages in-place, swipe/regenerate GM replies (with optional Director Notes), or switch branches; `revision_mismatch` warns when the active leaf's saved `(campaign_revision, solo_revision)` lags behind live state.
   - Use **Compress to Library** (`POST /v1/chat/compress`) to distill long branches into structured `npc`, `faction`, `location`, item, or rule dossiers inside the campaign's Homebrew Library.
   - Track public and branch-scoped secret **World Clocks** per timeline leaf.

## Memory & Separation of Concerns

- **Narrative memory:** Scene, summary, NPCs, objectives, discoveries, unresolved threads, and `[Category: Name]`-cited compressions live in `campaign.sqlite` and are reconciled by the two-pass turn loop and post-turn Chronicler pass.
- **Deterministic state:** Exact character stats, HP, Humanity, LUCK, money, inventory, and dice outcomes are owned by the backend (`campaign.py`, `gameplay.py`, `mechanics.py`), never invented by the model.
- **Undo & history:** Updates require `expected_revision`, `reason`, and `operation_id`. Identical retries reuse the saved result; narrative undo reverses the latest narrative event without erasing history.

## Storage & Privacy

Campaigns live in `campaign.sqlite` (default `~/.local/share/cyberpunk-red-gm/campaign.sqlite`, mode `0600`, or `/data/campaign.sqlite` in Docker). Override with `REDGM_CAMPAIGN_DB` or `--campaign-db PATH`. Never commit databases, `.env`, logs, or play transcripts.

## Legacy SillyTavern Extension (Optional)

If using the optional [SillyTavern extension](../sillytavern-extension/README.md), chat-level slash commands bind a SillyTavern chat to a campaign ID:

- `/red-campaign create <name>` / `/red-campaign list` / `/red-campaign use <id>`
- `/red-session` (refills attached characters' LUCK)
- `/red-campaign status` / `/red-campaign refresh` / `/red-campaign unbind`
- `/red-history` / `/red-undo`

See [Library & Turn Loop](LIBRARY_AND_TURNLOOP.md) for the HTTP API endpoints powering the Web UI.
