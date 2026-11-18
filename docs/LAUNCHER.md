# One-click launch (Linux)

Install once from this project directory (after building the web interface with `npm --prefix ui install && npm --prefix ui run build`):

```bash
.venv/bin/python launcher.py install
# Or host on your local Wi-Fi / LAN for co-op play with an optional passcode:
.venv/bin/python launcher.py install --lan --pin 4242
```

Your application menu will contain **Cyberpunk RED GM**. Launch it to start the
local server (which hosts both the backend API and the custom web interface), wait
for readiness, and open `http://127.0.0.1:8765` in a clean app window (when Chrome/Chromium
is available) or your default browser. No terminal needs to stay open. The desktop
entry also offers **Stop Cyberpunk RED GM**. The service does not auto-start at login.

Command-line equivalents:

```bash
.venv/bin/python launcher.py start
.venv/bin/python launcher.py start --browser tab
.venv/bin/python launcher.py stop
.venv/bin/python launcher.py status
```

The launcher installs a single user-level systemd unit (`redgm-backend.service`)
and a desktop entry, and automatically cleans up any older launcher-managed
`redgm-sillytavern.service` unit if present. It does not install a system-wide
daemon, run as root, or download dependencies on launch.

Both the API and the served web interface run on loopback (`127.0.0.1:8765`).
An occupied port belonging to an unmanaged process is an error: the launcher
does not kill or take over unrelated processes. Stop any manually launched
copies before using it.

`status` succeeds only when `redgm-backend.service` is installed and active.
Startup also checks that the unit remains active when `/health` responds; an
HTTP response alone is not treated as a successful launch.

If startup fails, inspect:

```bash
journalctl --user -u redgm-backend.service
```

Moving this worktree requires reinstalling the launcher to update absolute paths.
It requires a working Linux systemd user session; non-systemd systems need a
different launcher or running `.venv/bin/python redkb.py serve` directly.
