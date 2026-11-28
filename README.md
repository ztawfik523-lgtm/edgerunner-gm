# Edgerunner GM

Play solo or co-op **Cyberpunk RED (2045)** campaigns in your browser with an AI Game Master that handles dice rolls, skill checks, character sheets, world clocks, and campaign memory.

> *Edgerunner GM is unofficial content provided under the Homebrew Content Policy of R. Talsorian Games and is not approved or endorsed by RTG. This content references materials that are the property of R. Talsorian Games and its licensees.*

---

## Bring Your Own Corebook

**You need your own Cyberpunk RED Corebook PDF.** This repository includes **no** copyrighted Corebook PDF, rulebook text, or private campaign data, and the app has no built-in copy of the book's content.

Upload the PDF on the setup screen the first time you open the app. A live progress bar builds a private rules database on your server, which supplies the Roles, `Streetrat` / `Edgerunner` / `Complete Package` character creation, gear catalogs, campaign presets, and exact page lookup. Play starts once indexing finishes.

---

## Quick Setup

### Option 1: Docker (Easiest for a Cloud VM or Home Server)

Requires [Docker](https://docs.docker.com/get-docker/) and Docker Compose.

```bash
git clone https://github.com/ztawfik523-lgtm/edgerunner-gm.git
cd edgerunner-gm
cp .env.example .env
# Set REDGM_BOOTSTRAP_TOKEN in .env to a random value of at least 32 characters.
docker compose up -d --build
```

Then open **`http://YOUR-SERVER-IP:8765`** (or `http://127.0.0.1:8765` if local) in your browser:
1. Create your **Admin** username and password on the welcome screen (if hosting publicly, this keeps your settings private).
2. Click the model button in the top-right to open **Settings → Connection**, pick a preset (Ollama, OpenRouter, NVIDIA NIM, OpenAI, etc.), paste your API key if needed, and click **Test Connection** then **Save Settings**.
3. Upload your Corebook PDF on the setup screen (or later from **Settings → Corebook PDF**) and wait for the progress bar to reach 100%.

*(Tip: To also enable optional local AI meaning search inside Docker, set `INSTALL_SEMANTIC=true` in `.env` before building.)*

---

### Option 2: Run Directly on Your Computer (Python + Node.js)

Requires **Python 3.11+** and **Node.js 20+**.

```bash
git clone https://github.com/ztawfik523-lgtm/edgerunner-gm.git
cd edgerunner-gm

python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

npm --prefix ui install
npm --prefix ui run build

# Generate a one-time browser setup token (keep it private).
export REDGM_BOOTSTRAP_TOKEN="$(python -c 'import secrets; print(secrets.token_hex(32))')"
.venv/bin/python redkb.py serve
```

Open **`http://127.0.0.1:8765`** in your browser.

- **Playing with friends on home Wi-Fi?** Run `.venv/bin/python redkb.py serve --lan --pin 4242` (or change **Network** inside Settings).
- **Linux desktop one-click shortcut:** See the [Desktop Launcher Guide](docs/LAUNCHER.md).

---

## Learn How to Play & Customize

- **[Player & GM Guide](docs/PLAYER_GUIDE.md)** — Plain-English walkthrough of character creation, Corebook upload, dice/LUCK/Overclock, branching chat, co-op rooms, and customizing the GM's prompts and behavior.

---

## For Developers & Advanced Self-Hosters

All architecture details, CLI commands, HTTP API endpoints, environment variables, optional SillyTavern/MCP integrations, and test suites live separately in:

- **[Technical & Developer Reference](docs/TECHNICAL.md)**
- [Desktop Launcher Guide](docs/LAUNCHER.md) · [SillyTavern Extension](sillytavern-extension/README.md)

---

## License & Attribution

- **Source Code:** Licensed under the **[MIT License](LICENSE)** — free to use, modify, self-host, and distribute as long as credit and the copyright notice are preserved.
- **Tabletop IP Notice:** *Edgerunner GM is unofficial content provided under the Homebrew Content Policy of R. Talsorian Games and is not approved or endorsed by RTG. This content references materials that are the property of R. Talsorian Games and its licensees. No copyrighted Corebook text or PDF is included in this repository.*
