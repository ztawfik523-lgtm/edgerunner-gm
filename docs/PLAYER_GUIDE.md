# Player & GM Guide

Welcome to **Edgerunner GM**. This guide covers everything you need to run solo or co-op Cyberpunk RED games from your browser — no terminal commands required.

---

## 1. First-Time Setup in the Browser

### Connect Your AI Model
1. Click the **Configure AI** (or current model name) button in the top-right bar to open **Settings**.
2. In the **Connection** tab, choose a preset (like **Ollama** for free local models on your PC, or **NVIDIA NIM**, **OpenRouter**, or **OpenAI** for cloud models).
3. Enter your **Model ID** and **API Key** (local models like Ollama don't need an API key).
4. Click **Test Connection** to confirm it works, then **Save Settings**.

### Upload Your Corebook PDF (Required)
Edgerunner GM needs your own legally owned Cyberpunk RED Corebook PDF; it ships none of the book's content. Until a Corebook is indexed the app shows its setup screen:
1. Upload the PDF there. To replace it later, open **Settings → Corebook PDF**.
2. Drag and drop your PDF file or click **Upload Corebook PDF**.
3. Watch the progress bar as the server reads the pages and builds your searchable rulebook library. When it reaches **100%**, the app opens with the Roles, weapons, cyberware, skills, and page references read from your book — no restart needed.

---

## 2. Creating a Campaign & Characters

- **Create a Campaign:** Click **New** in the top bar to open the Campaign Creator. You can type a quick name for a blank sandbox, or fill in your district, factions, and premise (and use **AI Generate** to flesh out an opening scene, NPCs, Beat Chart, and hidden GM hooks). Districts, corporations, zone types, threat ratings, and screamsheet headlines come from your Corebook; add gangs, caper style, and NPCs yourself or let the AI write them.
- **Build a Character:** Open the **Character** tab on the right and click **Create Character**:
  - **Streetrat / Edgerunner / Complete Package:** Each uses your Corebook's Role templates, skills, starting gear, and lifepath tables.
  - Hover or click a Role, skill, or item to read your Corebook's description, and use the **Lifepath** and **AI Co-Writer** helpers to build your backstory and contacts.

---

## 3. Playing a Turn

- **Starting a Session:** Click **Start Session** in the top bar when a new session begins to refill every party member's **LUCK**.
- **Pre-Committing LUCK & Overclock:** Before sending an action in chat, you can spend **LUCK** points for a bonus on your roll, or toggle **Overclock** (`-2` Humanity for `+2` on a risky check).
- **Behind the Scenes (Automatic Rules & Dice):**
  - The app rolls real `d10`/`d6` dice on the server (including exploding `10`s and `1`s and automatic wound penalties) so the AI can't fudge numbers.
  - Every roll and stat/HP/eddie change appears as a card you can inspect — and if something ever needs a tweak, use the **Undo** controls in Character or Campaign history.
- **Branching, Editing & Regenerating:**
  - Hover over any message to **edit** it, **regenerate** the GM's reply (with an optional Director Note like *"make the fixer demand double"*), or **switch between reply branches** (`< 1/2 >`).
- **World Clocks & Compression:**
  - Track looming heat, deadlines, and faction timers in the **Campaign** panel.
  - When a story grows long, click **Compress to Library** so the AI distills old messages into clean NPC, faction, and location dossiers while keeping the summary crisp.

---

## 4. Customizing Your AI Game Master

Open **Settings** (top-right) to tailor the experience to your table:

### GM Speed vs Depth (Top Bar & Settings → Turn & Tuning)
- **GM Quality:** Uses full AI thinking on rules, storytelling, and session notes.
- **GM Balanced:** Same great writing with less waiting (keeps full thinking for rules & dice, skips extra wait time on narration and notes).

### Turn & Tuning Tab
- **Presets:** Start from built-in profiles (*Nemotron 1M Deep Roleplay*, *Balanced & Fast*, *Gritty & Deterministic*) or save your own.
- **GM Tone & Reply Length:** Pick *Grounded*, *Cinematic*, *Lethal*, or *Sandbox*, and choose *Concise*, *Standard*, or *Detailed* replies.
- **Creativity & Output:** Adjust Story Temperature, Rules Temperature, Character/Campaign Creator Temperature, and Max Output Tokens.
- **Table & Memory Toggles:**
  - Turn **on/off** automatic post-turn NPC & clue note-taking (*Chronicler*).
  - Turn **on/off** colored keyword highlights inside GM prose.
  - Turn **on/off** automatic saving of AI-invented Library entries.
  - Turn **on/off** long-chat compression reminders.

### Prompts Tab
Each turn runs through clearly separated AI stages, each with its own editable prompt block and **Sent to:** badge:
- **Player Dialogue, Narration & Multi-Player Handling:** Customize how player turns are formatted (`[{speaker}]: {message}`), how quotes vs actions vs `((OOC))` notes are parsed, how the GM narrates your character without puppeting them, and how multiple Co-op players share turns without hijacking idle teammates.
- **Pass 2 — GM Story Narrator & World:** Edit **GM Voice & Persona**, **House Rules & Setting Lore**, and extra prose notes.
- **Pass 1 — Rules & Dice Planner:** Add extra rules/dice/clock referee notes.
- **Pass 3 — Post-Turn Chronicler (Session Note-Taker):** Toggle the Chronicler **ON/OFF** right in this card (or in **Turn & Tuning**) and customize what it logs into Campaign State.
- **History Compression (Archivist) & Character/Campaign Generator:** Customize long-chat compression notes and the AI Co-Writer used in Character & Campaign Creators.
- **Advanced Built-In System Rules:** Expand this section at the bottom of the **Prompts** tab if you want to inspect or rewrite the full default instructions (such as NPC naming rules, street economy ranges, Fog-of-War rules, and pacing guidelines). Click **Revert field** or **Reset All Prompts** anytime to go back to defaults.

---

## 5. Playing Co-op with Friends

1. In **Settings → Network**, set **Bind IP** to `0.0.0.0 (LAN / Public)` if hosting on local Wi-Fi or a cloud VM, and restart if prompted.
2. In **Settings → Access & Auth**, set up an **Admin** account (and optionally allow players to register their own accounts or join with a shared player passcode).
3. Click **Co-op** in the top bar to copy the join URL, set your display name, and claim your character seat.
