# Cyberpunk RED Corebook tools for SillyTavern

Registers `search_corebook`, `read_corebook_page`, `game_action` and `campaign_action` against the local API. Gameplay supports backend dice/skill checks, persistent characters, direct HP/money/inventory changes, history and undo without approval prompts. Campaign commands bind this chat to durable narrative memory and explicit session starts, while native lorebooks and summaries remain available. See [campaign commands](../docs/CAMPAIGNS.md) and [operation arguments and limits](../docs/GAMEPLAY.md). The extension expects the backend at `http://127.0.0.1:8765`; use the [desktop launcher](../docs/LAUNCHER.md) to start it together with SillyTavern.

## Install

Copy this directory into SillyTavern's `data/<user>/extensions/` directory (or link it there), then restart/reload SillyTavern and enable **Cyberpunk RED Corebook** in Extensions. Enable function calling in AI Response Configuration. The backend must be running and its local index built.

For example, if SillyTavern is open at exactly `http://127.0.0.1:8000`, start the backend with `python redkb.py serve --allow-origin http://127.0.0.1:8000`. Use the exact browser origin including port, not a path. The default backend has no CORS access; this option allows scripts running on the specified origin to read the indexed book and change campaign state. Enable it only for a trusted local SillyTavern origin, and do not expose either service publicly. HTTPS SillyTavern may block an HTTP loopback backend as mixed content. The extension sends no credentials and contains no secrets.

This integration is optional and experimental (the built-in React Web UI in `../ui/` is the primary frontend). When using SillyTavern, nothing forces the model to call a tool before answering a rules question—verify rules against the returned source page.
