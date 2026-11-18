# Organized Library & Native AI Turn Loop Reference

## Authority and Scope

- **Status:** Implemented backend runtime in [library.py](../library.py), [turnloop.py](../turnloop.py), and [redkb.py](../redkb.py), built specifically to power the custom React Web UI (`ui/`) without requiring SillyTavern or a specific LLM.
- **Database boundary (BYOC):** Official indexed Corebook entries live read-only/derived inside `rules.sqlite` (optional under Bring-Your-Own-Corebook; when absent, `/health` reports `rules_indexed: false` and structured reference catalogs in `corebook_gm_data.py` / `creation_catalog.py` plus campaign homebrew remain active); all campaign-created homebrew entries, message trees, dice rolls, character sheets, and audit trails live in `campaign.sqlite`.

---

## 1. Organized Rulebook Library ([library.py](../library.py))

### Corebook Materialization & Caching
- **Build once on index:** `build_index` in `redkb.py` automatically calls `library.build_library(conn)` after writing index metadata, populating `rule_entries` and `rule_entries_fts` inside `rules.sqlite`.
- **One-time upgrade for existing indexes:** Run `.venv/bin/python redkb.py build-library` (`materialize_library`) under `index_lock` to materialize tables without re-extracting the PDF.
- **Unmaterialized DB fallback:** If queried against an older read-only `rules.sqlite` that lacks `rule_entries`, entries are extracted once and cached in memory keyed by `(path, mtime_ns, size, source_sha256)`.

### Entry Schema & Categories
Every entry returned by `search_library` / `get_library_entry` / `/v1/library` has a uniform JSON shape:
- **Categories (`ALLOWED_CATEGORIES`):** `skill`, `weapon`, `armor`, `cyberware`, `program`, `hardware`, `gear`, `fashion`, `role`, `rule`
- **Fields:** `id`, `name`, `category`, `source` (`"corebook"` or `"homebrew"`), `created_by` (`"corebook"`, `"user"`, `"gm"`, or `"ai"`), `summary`, `description`, `stats`, `tags`, `pdf_page`, `printed_page`, `section_id`, `source_sha256`, `campaign_id`
- **Skills (pp. 82–85):** Attach the full prose description beneath each dot-leader header plus `stats` (`stat`, `cost_multiplier`, `specializable`).
- **Gear / Cyberware / Weapons / Armor:** Parse structured columns into `stats` (`cost_eb`, `damage`, `rof`, `sp`, `armor_penalty`, `humanity_loss`, `install`, `skill`, `magazine`, `hands`, `concealable`) alongside descriptions and page numbers.

### Campaign-Scoped Homebrew (`CampaignLibrary`)
- Stores custom user/GM/AI creations in `campaign_library` inside `campaign.sqlite`, isolated per `campaign_id`.
- **Within-universe validation (`validate_entry_payload`):** Enforces allowed categories, valid `STAT_NAMES`, non-negative integer `cost_eb` (`0..1_000_000`), valid dice formulas (`\d{1,2}d(6|10)`), bounded `rof` (`1..4`), `sp` (`0..25`), `armor_penalty` (`-10..0`), and `humanity_loss`.
- **Official rules protection:** Rejects adding a duplicate name+category over an existing official Corebook entry unless `allow_variant=True`, and rejects `DELETE` on `corebook:*` IDs. Supports idempotent `operation_id`.

---

## 2. AI Turn Loop & Message Tree ([turnloop.py](../turnloop.py))

### Model-Agnostic LLM Adapter (`OpenAICompatibleLLM` + `LLMConfig`)
- Connects via `httpx` to any OpenAI-compatible `/v1/chat/completions` endpoint (Ollama, llama.cpp, KoboldCpp, OpenRouter, or cloud APIs) with configurable `base_url`, `model`, `api_key`, `temperature`, `max_tokens`, `timeout_s`, and `mode`.
- Environment defaults: `REDGM_LLM_URL` (`http://127.0.0.1:11434/v1`), `REDGM_LLM_MODEL` (`llama3`), `REDGM_LLM_API_KEY`. Requests to `POST /v1/chat/turn` can also supply per-request `llm_config`.

### Branching Chat Tree & Revision Sync (`ChatTreeStore`)
- Persists every message in `chat_messages` (`id`, `campaign_id`, `parent_id`, `role`, `content`, `raw_content`, `model`, `campaign_revision`, `solo_revision`, `metadata_json`, `is_active`, `created_at`).
- Supports editing earlier turns or swiping/regenerating GM replies by passing `parent_id` to `/v1/chat/turn`.
- `get_tree` computes `sibling_index`, `sibling_count`, and `sibling_ids` per node plus `active_branch` and `revision_mismatch` (comparing the active leaf's saved `(campaign_revision, solo_revision)` against live DB revisions).
- **Chat QoL:** `delete_message` deletes a message and its descendant subtree (reactivating a remaining sibling), `update_message` edits message text in-place (marking `metadata.edited = True`), `export_branch` formats a clean Markdown/JSON transcript, `run_turn` accepts `speaker_character_id`/`speaker_name` attribution, and `regenerate_turn` accepts an optional `guidance` Director Note.

### 3-Phase Hybrid Turn Pipeline (`TurnEngine.run_turn`)
1. **Preprocess:** Reads live campaign/character snapshot (`GameplayService.campaign_context`), resolves the active/target branch, rolls deterministic server dice entropy pools (`d10`, `d6`) stored in `rolls`, auto-retrieves relevant `library.py` entries for the message + current scene, and checks branch length (`>= 14` messages triggers a summary-compression reminder).
2. **Plan & Execute (`two_pass` or `single_pass_tagged`):**
   - **`two_pass` (default):** Pass 1 prompts the model at low temperature (`0.1`) for strict JSON (`checks`, `state_ops`, `new_homebrew`, `gm_notes`); Python validates and executes everything deterministically before Pass 2 streams narration grounded in the locked outcomes.
   - **`single_pass_tagged`:** Streams prose in a single model pass while stripping trailing `<gm_ops>{...}</gm_ops>` or `[[GM_STATE:{...}]]` control tags live before saving clean prose in `content` and raw output in `raw_content`, then executes the extracted plan.
   - **Guardrails:** Fuzzy character name resolution (`_resolve_character`), skill/stat hallucination guard (`_verify_skill` requiring Corebook or campaign homebrew skill definition), Overclock mechanic (`overclock=True`: audited `-2` Humanity in `audit` for `+2` check bonus), and before/after `state_patch` capture.
3. **Typed SSE Events (`POST /v1/chat/turn`):**
   - `rule_citation` (retrieved library entries + pre-rolled dice pools)
   - `dice_roll` (authoritative `GameplayService` check result + actor/modifier details)
   - `state_patch` (before/after character or campaign changes)
   - `library_added` (newly persisted campaign homebrew items)
   - `warning` (blocked unverified skills, revision/compression hints)
   - `text_delta` (streamed clean narration chunks)
   - `turn_done` (saved `user_message`, `assistant_message`, and full turn summary)

---

## 3. HTTP Endpoints ([redkb.py](../redkb.py))

All mutating endpoints enforce trusted-origin (`--allow-origin`) and `Content-Type: application/json` checks consistent with `POST /v1/game`.

| Method & Path | Purpose | Key Params / Body |
| :--- | :--- | :--- |
| `GET /v1/library` | Search Corebook + optional campaign homebrew | `q`, `category`, `campaign_id`, `include_corebook`, `include_homebrew`, `limit` |
| `GET /v1/library/{entry_id}` | Fetch one rulebook or homebrew entry | `campaign_id` (required for `homebrew:*` IDs) |
| `POST /v1/library/homebrew` | Add campaign homebrew entry | JSON: `campaign_id`, `name`, `category`, `summary`, `description`, `stats`, `tags`, `operation_id`, `created_by`, `allow_variant` |
| `DELETE /v1/library/homebrew/{entry_id}` | Delete a campaign homebrew entry | Query: `campaign_id` |
| `GET /v1/chat/tree` | Fetch full message tree & active branch | Query: `campaign_id` |
| `POST /v1/chat/branch` | Switch active branch/swipe node | JSON: `campaign_id`, `message_id` |
| `POST /v1/chat/turn` | Execute turn & stream typed SSE events | JSON: `campaign_id`, `user_text`, optional `parent_id`, `branch_from_root`, `overclock`, `luck_spend`, `speaker_character_id`, `speaker_name`, `mode`, `llm_config` |
| `POST /v1/chat/regenerate` | Swipe/regenerate GM reply on an existing user turn | JSON: `campaign_id`, `message_id`, optional `guidance`, `overclock`, `luck_spend`, `mode`, `llm_config` |
| `POST /v1/chat/compress` | Distill branch history into structured Library dossiers (`npc`, `faction`, `location`, items/rules) + compact `[Category: Name]`-cited summary | JSON: `campaign_id`, optional `leaf_id`, `llm_config` |
| `GET /v1/campaigns/{id}/clocks` | List public world/heat clocks for the active branch | Query: optional `leaf_id` |
| `POST /v1/campaigns/{id}/clocks` | Create, tick, set, or delete a public world/heat clock | JSON: `action` (`create`/`tick`/`set`/`delete`), `name`/`clock_id`, `max`, `delta`, `trigger`, optional `leaf_id` |
| `POST /v1/chat/delete` | Delete a message node and its descendant subtree | JSON: `campaign_id`, `message_id` |
| `POST /v1/chat/message/update` | Edit message text in-place | JSON: `campaign_id`, `message_id`, `content` |
| `GET /v1/chat/export` | Export active branch as JSON + Markdown | Query: `campaign_id`, optional `leaf_id` |
| `GET /v1/network/info` | LAN hosting status, join URLs, roster & turn lock | Optional query: `campaign_id` |
| `POST /v1/campaigns/{id}/presence` | Register or refresh Co-op seat presence | JSON: `client_id`, `player_name`, `character_id` |
| `GET /v1/campaigns/{id}/events` | Subscribe to live Co-op SSE updates | Query: optional `pin` |
| `GET /v1/settings/llm` | Read saved LLM connection settings (key masked) | — |
| `POST /v1/settings/llm` | Save persistent LLM connection settings | JSON: `base_url`, `model`, `api_key`, `clear_api_key`, `temperature`, `max_tokens`, `timeout_s`, `mode` |
| `POST /v1/settings/llm/test` | Probe provider `/models` endpoint | JSON: `base_url`, optional `api_key` |

When built (`ui/dist/index.html` present), [redkb.py](../redkb.py) also serves the custom React web UI directly on `GET /` and `/assets/*` alongside the API.

### Turn Loop Mechanics & Memory Extensions

- **Categories & Upsert ([library.py](../library.py)):** `ALLOWED_CATEGORIES` includes `npc`, `faction`, and `location` alongside gear/cyberware/skills/rules, and `CampaignLibrary.upsert_entry` updates or inserts named dossiers cleanly.
- **Pre-Roll `luck_spend`, Time & `solo_ops` ([turnloop.py](../turnloop.py), [lifecycle.py](../lifecycle.py)):** `TurnEngine.run_turn` / `regenerate_turn` accept `luck_spend` (committed on the primary check only when a check executes), Planner `time_elapsed_minutes` / `SoloService.advance_time` syncing `runtime.clock_minutes` with character `detail.clock_minutes`, and `solo_ops` routed through `SoloService.execute`. For live `OpenAICompatibleLLM` calls, a 3rd post-turn Chronicler pass reconciles newly narrated NPCs/clues/time after streaming completes, with 429/503 retry backoff.
- **Branch-Scoped Private State & Clocks ([turnloop.py](../turnloop.py)):** `turn_gm_snapshots` isolates `gm_secrets` and `campaign_clocks` (`public` vs `secret`) per timeline leaf across regenerates/branches/forks; `compress_memory()` updates `campaign_compressions` and `[Category: Name]` auto-retrieval citations without exposing `gm_secrets`.

---

## 4. Verification Scope

- Covered by targeted unit and API tests in [tests/test_library.py](../tests/test_library.py), [tests/test_turnloop.py](../tests/test_turnloop.py), [tests/test_api.py](../tests/test_api.py), [tests/test_gameplay_api.py](../tests/test_gameplay_api.py), and [tests/test_redkb.py](../tests/test_redkb.py), plus the Web UI Vitest suite (`ui/`) and extension contract tests (`node tests/test_extension.mjs`).
