# Phased Plan: Mandatory BYOC, License/Copyright Hygiene & Creator UX Overhaul

Each phase below is **self-contained and independently executable**. You can paste or reference any individual phase in a new chat session without needing prior conversation history.

**Global Repo Conventions (Applies to All Phases)**
- Read `AGENTS.md` / `docs/TECHNICAL.md` if present; follow `cyberpunk-red-gm` skill rules.
- **UI checks**: `cd ui && npm test -- --run && npm run build`
- **Python targeted checks**: `.venv/bin/python -m pytest tests/test_creation.py tests/test_creation_catalog.py tests/test_library.py tests/test_campaign.py tests/test_api.py tests/test_gameplay.py tests/test_gameplay_api.py tests/test_auth_and_settings.py tests/test_turnloop.py tests/test_launcher.py -q`

---

## Phase 1: License, Disclaimer & Strict Mandatory BYOC Gate

### Context & Goal
Transition the app from optional BYOC + `Freeform` fallback to **strictly mandatory BYOC (Bring Your Own Corebook)** and align licensing with R. Talsorian Games's (RTG) Homebrew Content Policy:
- Switch `LICENSE` from MIT to **PolyForm Noncommercial License 1.0.0** (permits free use, modification, and sharing while blocking commercial use / selling forks).
- Add RTG's mandatory unofficial disclaimer to `README.md` and Settings → BYOC.
- Remove `Freeform` character creation mode and hardcoded Night City `FALLBACK_PRESETS` from the UI, and gate Character Creator, Campaign Architect, `/v1/creation/reference`, `/v1/creation/ai-assist`, and character creation actions behind `rules_indexed === true`.

### Exact Files & Changes
1. **`LICENSE` & `README.md`**:
   - Replace `LICENSE` text with **PolyForm Noncommercial License 1.0.0** (preserving the existing copyright holder/year).
   - Add RTG's Unofficial Homebrew Content Policy disclaimer to `README.md` and update BYOC docs to state BYOC is required.
2. **`redkb.py`**:
   - `/health` (lines ~1127–1154): update unindexed `detail` message from `"Corebook PDF not indexed yet. Homebrew and campaign play remain available."` to state BYOC PDF upload is required (`Settings -> BYOC`).
   - `/v1/creation/ai-assist` (lines ~1434–1460): return `409 Conflict` when `not Path(db_path).expanduser().is_file()`.
   - `/v1/game` (around `create_character` / `create_player_character`, lines ~939–949): reject character creation when `rules_path` / `db_path` is not indexed.
3. **`creation_reference.py`**:
   - Remove `"freeform"` from `METHODS_REFERENCE`.
   - `build_creation_reference(rules_path)` (lines ~1516–1725): when `not rules_indexed`, return `{"rules_indexed": False, ...}` with empty lists/maps (`roles: []`, `methods: []`, `stats: []`, `skills: []`, `shop_items: {}`, `lifepath_tables: {}`, `campaign_presets: {"districts": [], "factions": [], "caper_styles": []}`).
4. **`ui/src/types.ts`, `ui/src/components/TopBar.tsx`, `ui/src/components/SettingsModal.tsx`, `ui/src/App.tsx`**:
   - `types.ts` (line ~541): remove `"freeform"` from `CreationMethodInfo["id"]`.
   - `TopBar.tsx` (lines ~178–198): update `No BYOC` badge tooltip from `(Freeform & Homebrew play works without it)` to `"BYOC Required: Upload your Corebook PDF in Settings -> BYOC"`.
   - `SettingsModal.tsx` (lines ~1585–1695): change `"BYOC — Bring Your Own Corebook (Optional)"` → `"BYOC — Bring Your Own Corebook (Required)"`, `"No BYOC Yet (Freeform Mode)"` → `"BYOC Setup Required"`, `"Without a PDF, you can still create Freeform characters and homebrew rules."` → `"Upload your PDF to unlock Character Creator, Campaign Architect, and rulebook search."`, and display the RTG unofficial disclaimer.
   - `App.tsx` (lines ~1145–1207): pass `rulesIndexed={Boolean(health?.rules_indexed)}` and `onOpenByocSettings` (for admins) into `CharacterCreatorModal` and `CampaignCreatorModal`.
5. **`ui/src/components/CharacterCreatorModal.tsx` & `ui/src/components/CampaignCreatorModal.tsx`**:
   - `CharacterCreatorModal.tsx`: remove `"freeform"` method state (line ~380), `freeformMoney` (line ~490), `FALLBACK_METHODS` freeform entry (line ~1874), `"Switch to Freeform Instead"` (line ~4848), and all `method === "freeform"` branches. When `rulesIndexed === false` (or `refData !== null && !refData.rules_indexed`), render a **BYOC Setup Required** gate (with `"Open BYOC Settings"` button for admins).
   - `CampaignCreatorModal.tsx`: remove hardcoded Night City `FALLBACK_PRESETS` (lines ~44–170+). Fetch presets from `/v1/creation/reference` (or `/health` + presets); when `!rulesIndexed`, render the **BYOC Setup Required** gate (with `"Open BYOC Settings"` button for admins).
6. **Tests (`ui/src/App.test.tsx`, `tests/test_creation.py`)**:
   - Update `App.test.tsx` creator tests to provide `rules_indexed: true` without `freeform`, and add tests verifying the BYOC gate when `rules_indexed: false`.
   - Update `tests/test_creation.py` to assert `build_creation_reference(None)` returns `rules_indexed: False` with empty reference collections.

### Verification
```bash
cd ui && npm test -- --run && npm run build
.venv/bin/python -m pytest tests/test_creation.py tests/test_api.py tests/test_auth_and_settings.py -q
```

---

## Phase 2: Character Creator & Character Panel UX/UI Fixes + Page Number Removal

### Context & Goal
Fix 6 specific layout, visibility, collapsibility, and page-citation issues in `CharacterCreatorModal.tsx` and `CharacterPanel.tsx` (can be executed independently of other phases):
1. **Color wheel button** looks out of place in size, font, and vertical alignment.
2. **Role extra features** (`Tech`, `Medtech`, `Fixer`, `Nomad`, `Exec`) appear below the 10-role grid out of sight unless the user knows to scroll.
3. **Cultural Native Language** (`Skills` tab) wastes a full 3-column grid row when alone.
4. **Street Reputation & Starting Hooks** (`Lifepath` tab) is hidden by default, labeled `(p. 193 · Optional)`, and is the only collapsible section in Lifepath.
5. **Housing, Lifestyle & Trauma Team** (`Gear` tab) is buried at the very bottom below the entire gear shop catalog.
6. **Hardcoded page numbers** appear across Character Creator and Character Panel.

*(Before starting: confirm with the user whether all Lifepath card sections should be **collapsible and expanded by default** vs. **none collapsible**.)*

### Exact Files & Changes
1. **`ui/src/components/CharacterCreatorModal.tsx`**:
   - **Color Wheel (Identity & Role tab, lines ~2362–2395)**:
     - Match the preset color buttons (`inline-flex items-center gap-1.5 rounded border px-2 py-1 text-[11px] font-medium`).
     - Render a matching `h-2.5 w-2.5 rounded-full` color swatch (`style={{ backgroundColor: normalizeColorHex(characterColor) }}`) and hide native `<input type="color">` chrome via `sr-only` (or `absolute inset-0 h-full w-full cursor-pointer opacity-0`) inside the `relative` `<label>`.
   - **Role Extra Features Visibility (Identity & Role tab, lines ~2480–2728)**:
     - Tighten role card padding (`p-2`, `gap-1.5`) to save vertical space.
     - Add a visible `"Role Options"` badge on the 5 roles that have extra setup (`Tech`, `Medtech`, `Fixer`, `Nomad`, `Exec`).
     - Add a clickable `"Configure {selectedRole} Options ↓"` pill in the Role section header whenever one of those 5 roles is selected, and auto-`scrollIntoView({ behavior: "smooth", block: "nearest" })` the Role-Specific Ability Choices container on role selection.
   - **Cultural Native Language (Skills tab, lines ~2944–2997)**:
     - Replace `grid grid-cols-1 gap-2 rounded-lg border ... p-3 sm:grid-cols-3` with a compact `flex flex-wrap items-center gap-3 rounded-lg border ... px-3 py-2` bar so `Free +4 Cultural Native Language` + any active specialization dropdowns share a single tight row.
   - **Lifepath Collapsibility & Street Reputation (lines ~459, ~3245–3841)**:
     - Set `showRepHooks` default to `true` (not hidden by default).
     - Remove `(p. 193 · Optional)` → `Street Reputation & Starting Hooks` (remove `"Optional"` and page number).
     - Make **all** Lifepath card sections (`Bio & Backstory`, `Street Origins & Background`, `Values & Personality`, `Friends, Enemies & Past Romances`, `Street Reputation & Starting Hooks`) consistently collapsible with uniform toggle headers, **all expanded by default (`true`)** (or none collapsible if user prefers).
   - **Gear Tab Placement (lines ~3846–3900 & ~4751–4829)**:
     - Move the `Housing, Lifestyle & Trauma Team` card from the bottom of the Gear tab to the **top** of the Gear tab (immediately below the package/budget header, above the weapons/shop catalog).
   - **Remove Page Numbers**:
     - Strip all hardcoded page citations (`Corebook p.${role.page}`, `(p. 153)`, `· Corebook p.${sk.printed_page}`, `(p. 193 · Optional)`, `(p. 358)`, `· Corebook p.${item.printed_page}`, `(pp. 223, 377–378)`, `(pp. 377–378)`).
2. **`ui/src/components/CharacterPanel.tsx`**:
   - Strip `(p. 230)` and `(Corebook pp. 408-411)` from Therapy messages/tooltips (lines ~560, 577, 1136, 1145) and Improvement Points tooltip (line ~1438).
3. **`ui/src/App.test.tsx`**:
   - Update assertions for removed page numbers and `"Optional"`, assert `Street Reputation & Starting Hooks` is visible by default in Lifepath, and assert `Housing, Lifestyle & Trauma Team` renders before the gear shop list.

### Verification
```bash
cd ui && npm test -- --run && npm run build
```

---

## Phase 3: Icon-Only Per-Textfield AI Actions & Campaign Architect UX Overhaul

### Context & Goal
Upgrade Improve/Regen AI buttons across both Character Creator and Campaign Architect and fix Campaign Architect collapsibility and page-number clutter (can be executed independently of other phases):
1. `FieldAiActions` should render **icon-only buttons with hover tooltips** (no `"Improve"` / `"Regen"` text labels) to reduce clutter.
2. Improve/Regen should apply to **every individual textfield** (not groups of fields) in both Character Creator and Campaign Architect.
3. Campaign Architect sections should have **consistent collapsibility** (`showWorldEntities` and `showSessionZero` should not be the only collapsible sections; make all sections collapsible and expanded by default, or none collapsible if user prefers), remove `"Optional"` labels, and strip all page numbers.

### Exact Files & Changes
1. **`ui/src/components/FieldAiActions.tsx` (lines 1–47)**:
   - Remove visible `<span>Improve</span>` and `<span>Regen</span>` text labels.
   - Render compact icon-only `<button>`s (`Wand2` and `RefreshCw`) with `title={`Improve ${label}`}` / `title={`Regenerate ${label}`}` hover tooltips, `aria-label` attributes, and spin/pulse feedback while `busyAction` is active.
2. **`creation_catalog.py` (lines ~1042–1623)**:
   - Add `reputation_note`, `trauma_hook`, `addiction_hook`, and `debt_hook` to `_BIO_FIELDS`.
   - Extend `generate_creation_ai_assist` to support per-textfield / per-entry targeting (e.g., optional `entry_index` / `sub_field` or field keys) for:
     - Character Creator: individual Friend / Enemy / Past Romance textfields and Street Reputation / Hooks textfields.
     - Campaign Architect: `gig_title`, `gig_client`, `gig_target`, `gig_deadline`, `gig_notes`, `clock_name`, `clock_note`, and individual indexed NPC / Objective / Secret / Location / Discovery textfields.
   - Strip hardcoded page numbers (`Corebook p. 396`, etc.) from `_BEAT_KEY_TO_FIELD` and prompt strings.
3. **`ui/src/components/CharacterCreatorModal.tsx`**:
   - Add icon-only `FieldAiActions` to each textfield in `Street Reputation & Starting Hooks` (`reputationNote`, `traumaHook`, `addictionHook`, `debtHook`).
   - Replace group-level `FieldAiActions` on `Friends`, `Enemies`, and `Past Romances` headers (lines ~3604, 3651, 3728) with per-textfield `FieldAiActions` on individual contact textfields.
4. **`ui/src/components/CampaignCreatorModal.tsx`**:
   - **Consistent Collapsibility**: Make **all** major sections (`Setting & Style`, `Premise & Opening`, `Beat Chart Outline`, `Starting NPCs & Objectives`, `World Builder Extras`, `GM Secrets & Opening Clocks`, `Session Zero Dials & Table Boundaries`) consistently collapsible, **all expanded by default (`true`)** (updating `showWorldEntities` and `showSessionZero` defaults from `false` to `true`).
   - **Per-Textfield AI Icons**: Remove group-level `FieldAiActions` on `Beat Chart` (line ~1535), `Starting NPCs` (line ~1588), `Starting Objectives` (line ~1698), `GM Secrets` (line ~1954), and `Opening Clock` (line ~2030); attach icon-only `FieldAiActions` to **each individual textfield** (Title, Premise, Opening Scene, each Beat field, each NPC textfield, each Objective textfield, GM Secrets textarea & each secret textfield, Clock Name & Trigger Note, Starting Gig fields, Location notes, and Discovery/Clue fields).
   - **Remove `"Optional"` & Page Numbers**: Strip `"Optional"` suffixes and `(pp. 395–408)`, `(pp. 298–317)`, `(pp. 393–405)`, `(pp. 168–188)` from all labels/options (lines ~1185, 1340, 1374, 1533, 1544, 2027, 2197, 2263).
5. **`ui/src/App.test.tsx`**:
   - Update tests for icon-only `FieldAiActions` (matching via `aria-label` / `title`), per-textfield AI buttons, removed page numbers/`"Optional"`, and default-expanded Campaign Architect sections.

### Verification
```bash
cd ui && npm test -- --run && npm run build
.venv/bin/python -m pytest tests/test_creation_catalog.py tests/test_api.py -q
```

---

## Phase 4: Database-Driven Extraction & Stripping Hardcoded Corebook Prose/Lore

### Context & Goal
Remove hardcoded Night City lore, verbatim Corebook prose descriptions, and hardcoded page citations from backend Python catalog/reference modules (`corebook_gm_data.py`, `creation_catalog.py`, `creation_reference.py`), and instead populate roles, skills, items, districts, factions, lifepath tables, and descriptions directly from the user's indexed `rules.sqlite` / `rule_entries` library (`library.py`, `sourcecatalog.py`) after BYOC PDF upload.

*(Note: Because `tests/test_creation.py` and `tests/test_creation_catalog.py` currently test the old hardcoded builders, update those tests in this phase to use synthetic `rules.sqlite` fixtures.)*

### Exact Files & Changes
1. **`library.py` & `sourcecatalog.py`**:
   - Expand `rules.sqlite` extraction (`pages`, `source_sections`, `source_tables`, `rule_entries`) during `build_library(conn)` and query helpers so:
     - Role summaries/abilities, districts, factions, caper/beat structures, housing/lifestyle tiers, and lifepath tables are extracted from the user's indexed PDF pages/sections/tables into `rule_entries` / structured queries.
   - Remove the fallback import of hardcoded prose/lore from `creation_catalog.build_library_corebook_entries` (lines ~399–410 of `library.py`), keeping `rule_entries` strictly sourced from the user's `rules.sqlite` PDF.
2. **`corebook_gm_data.py`, `creation_catalog.py`, `creation_reference.py`**:
   - Strip hardcoded Night City districts/factions lore (`build_campaign_presets()` in `creation_catalog.py`), verbatim Corebook item/role prose descriptions, and hardcoded page citations (`Corebook pp. ...`).
   - Update `creation_reference.py` (`build_creation_reference(rules_path)`) and campaign preset builders to read roles, skills, shop items, lifepath data, districts, and factions directly from `rules.sqlite` (`rule_entries` + `sourcecatalog` + `pages`), keeping only factual mechanical schemas/math (stat names, slot math, roll formulas) where required by game rules validation.
3. **Tests (`tests/test_creation.py`, `tests/test_creation_catalog.py`, `tests/test_library.py`)**:
   - Update tests to build/use a synthetic `rules.sqlite` fixture to verify dynamic extraction and confirm hardcoded copyrighted lore/prose is stripped.

### Verification
```bash
cd ui && npm test -- --run && npm run build
.venv/bin/python -m pytest tests/test_creation.py tests/test_creation_catalog.py tests/test_library.py tests/test_campaign.py tests/test_api.py tests/test_gameplay.py tests/test_gameplay_api.py tests/test_auth_and_settings.py tests/test_turnloop.py tests/test_launcher.py -q
```
