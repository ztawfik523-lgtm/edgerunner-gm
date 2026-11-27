# One-Click Desktop Launcher (Linux)

After building the web UI (`npm --prefix ui install && npm --prefix ui run build`), you can install a desktop app shortcut so you don't need to keep a terminal window open:

```bash
.venv/bin/python launcher.py install
```

To allow friends on your local Wi-Fi / LAN to join with a room PIN:

```bash
.venv/bin/python launcher.py install --lan --pin 4242
```

Once installed, open **Cyberpunk RED GM** from your application menu. It starts the local server in the background and opens `http://127.0.0.1:8765` in a clean app window (or your default browser). Your app menu also gets a **Stop Cyberpunk RED GM** shortcut.

### Terminal Shortcuts

```bash
.venv/bin/python launcher.py start
.venv/bin/python launcher.py start --browser tab
.venv/bin/python launcher.py stop
.venv/bin/python launcher.py status
```

---

### Technical Notes & Troubleshooting

- Installs a user-level systemd unit (`redgm-backend.service`) and desktop entry. Does not require root or auto-start at login.
- Fails safely if port `8765` is already used by another process; stop any manually started server before launching.
- If startup fails, inspect logs with:
  ```bash
  journalctl --user -u redgm-backend.service
  ```
- Moving the project folder requires re-running `.venv/bin/python launcher.py install` so saved paths update. Requires a Linux systemd user session.
