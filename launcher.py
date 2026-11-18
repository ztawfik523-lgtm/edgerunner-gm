#!/usr/bin/env python3
"""Install and control the Cyberpunk RED GM single-service local app."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

BACKEND_UNIT = "redgm-backend.service"
LEGACY_ST_UNIT = "redgm-sillytavern.service"
MARKER = "# Managed by Cyberpunk RED GM launcher"
BACKEND_URL = "http://127.0.0.1:8765/health"
UI_URL = "http://127.0.0.1:8765/"
APP_BROWSERS = ("google-chrome", "chromium", "chromium-browser", "brave-browser", "microsoft-edge")


class LauncherError(RuntimeError):
    pass


def _systemd_quote(value: str) -> str:
    if any(ch in value for ch in "\n\r\x00"):
        raise LauncherError("Launcher paths must not contain newlines or NUL characters")
    return '"' + value.replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"') + '"'


def _exec_quote(value: str) -> str:
    return _systemd_quote(value.replace("$", "$$"))


def _working_directory(value: str) -> str:
    # WorkingDirectory is a single path value, not an ExecStart argument list:
    # surrounding quotes become literal path characters in systemd's parser.
    if any(ch in value for ch in "\n\r\x00"):
        raise LauncherError("Launcher paths must not contain newlines or NUL characters")
    return value.replace("%", "%%")


def _desktop_quote(value: str) -> str:
    # Desktop Exec arguments use desktop-entry escaping, not shell quoting.
    if any(ch in value for ch in "\n\r\x00"):
        raise LauncherError("Launcher paths must not contain newlines or NUL characters")
    escaped = value.replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")
    return '"' + escaped.replace("\\", "\\\\") + '"'


def _atomic_write(path: Path, content: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_name, mode)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _unit_file(unit_dir: Path, unit: str, body: str) -> tuple[Path, str]:
    path = unit_dir / unit
    if path.exists() and MARKER not in path.read_text(encoding="utf-8", errors="replace"):
        raise LauncherError(f"Refusing to overwrite existing unmanaged file: {path}")
    return path, f"{MARKER}\n{body}"


def _systemctl(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    result = subprocess.run(["systemctl", "--user", *args], text=True, capture_output=True)
    if check and result.returncode:
        raise LauncherError((result.stderr or result.stdout or f"systemctl {' '.join(args)} failed").strip())
    return result


def _is_owned_unit(unit_dir: Path, unit: str) -> bool:
    path = unit_dir / unit
    return path.is_file() and MARKER in path.read_text(encoding="utf-8", errors="replace")


def _owned_units(config_home: Path) -> set[str]:
    unit_dir = config_home / "systemd" / "user"
    return {unit for unit in (BACKEND_UNIT, LEGACY_ST_UNIT) if _is_owned_unit(unit_dir, unit)}


def install(
    project: Path,
    config_home: Path,
    data_home: Path,
    browser_mode: str = "auto",
    lan: bool = False,
    pin: str = "",
) -> None:
    project = project.expanduser().resolve()
    py = project / ".venv" / "bin" / "python"
    if not (project / "redkb.py").is_file() or not py.is_file():
        raise LauncherError(f"Expected redkb.py and .venv/bin/python in {project}; set up the project environment first")
    # Resolving the venv symlink would invoke system Python without its packages.
    python_path = str(py)
    host = "0.0.0.0" if lan else "127.0.0.1"
    pin_flag = f" --pin {_exec_quote(pin)}" if pin else ""
    backend = "\n".join(
        (
            "[Unit]",
            "Description=Cyberpunk RED GM server and web interface",
            "After=network.target",
            "",
            "[Service]",
            "Type=exec",
            f"WorkingDirectory={_working_directory(str(project))}",
            f"ExecStart={_exec_quote(python_path)} {_exec_quote(str((project / 'redkb.py').resolve()))} serve --host {host} --port 8765{pin_flag}",
            "Restart=on-failure",
            "RestartSec=2",
            "",
            "[Install]",
            "WantedBy=default.target",
            "",
        )
    )
    unit_dir = config_home / "systemd" / "user"
    desktop_dir = data_home / "applications"
    backend_path, backend_contents = _unit_file(unit_dir, BACKEND_UNIT, backend)
    desktop = desktop_dir / "cyberpunk-red-gm.desktop"
    if desktop.exists() and MARKER not in desktop.read_text(encoding="utf-8", errors="replace"):
        raise LauncherError(f"Refusing to overwrite existing unmanaged file: {desktop}")
    script = str(Path(__file__).resolve())
    browser_flag = "" if browser_mode == "auto" else f" --browser {browser_mode}"
    entry = "\n".join(
        (
            "[Desktop Entry]",
            "Type=Application",
            "Name=Cyberpunk RED GM",
            "Comment=Start the Cyberpunk RED GM tabletop interface",
            "Terminal=false",
            f"Exec={_desktop_quote(sys.executable)} {_desktop_quote(script)} start{browser_flag}",
            "Actions=Stop;",
            "",
            "[Desktop Action Stop]",
            "Name=Stop Cyberpunk RED GM",
            f"Exec={_desktop_quote(sys.executable)} {_desktop_quote(script)} stop",
            "",
        )
    )
    legacy_path = unit_dir / LEGACY_ST_UNIT
    if _is_owned_unit(unit_dir, LEGACY_ST_UNIT):
        _systemctl("stop", LEGACY_ST_UNIT)
        legacy_path.unlink(missing_ok=True)
    _atomic_write(backend_path, backend_contents, 0o600)
    _atomic_write(desktop, f"{MARKER}\n{entry}", 0o644)
    _systemctl("daemon-reload", check=True)
    print(f"Installed user service and desktop launcher. Start with: {sys.executable} {script} start")


def _port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.25)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            return 200 <= response.status < 400
    except (OSError, urllib.error.URLError):
        return False


def _notify(message: str) -> None:
    print(message, file=sys.stderr)
    notify = shutil.which("notify-send")
    if notify:
        subprocess.Popen([notify, "Cyberpunk RED GM", message], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def _open_ui(url: str, browser_mode: str = "auto") -> None:
    if browser_mode in {"auto", "app"}:
        for candidate in APP_BROWSERS:
            binary = shutil.which(candidate)
            if binary:
                subprocess.Popen(
                    [binary, f"--app={url}"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                return
    opener = shutil.which("xdg-open")
    if opener:
        subprocess.Popen([opener, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def start(config_home: Path, no_browser: bool = False, browser_mode: str = "auto") -> None:
    owned = _owned_units(config_home)
    if BACKEND_UNIT not in owned:
        raise LauncherError("Service is not installed. Run launcher.py install first.")
    active = _systemctl("is-active", "--quiet", BACKEND_UNIT).returncode == 0
    if _port_open(8765) and not active:
        raise LauncherError("Port 8765 is already occupied by an unmanaged process; stop it yourself before launching.")
    started = False
    try:
        if not active:
            started = True
            _systemctl("start", BACKEND_UNIT, check=True)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if _ready(BACKEND_URL):
                result = _systemctl("is-active", BACKEND_UNIT)
                if result.returncode != 0 or result.stdout.strip() != "active":
                    raise LauncherError(f"Managed service is not active: {BACKEND_UNIT}")
                if not no_browser:
                    _open_ui(UI_URL, browser_mode=browser_mode)
                print(f"Cyberpunk RED GM is ready at {UI_URL.rstrip('/')}")
                return
            time.sleep(0.5)
        raise LauncherError("Service did not become ready within 30 seconds. Inspect with: journalctl --user -u redgm-backend.service")
    except Exception:
        if started:
            _systemctl("stop", BACKEND_UNIT)
        raise


def stop(config_home: Path) -> None:
    owned = _owned_units(config_home)
    if not owned:
        raise LauncherError("No managed Cyberpunk RED GM services are installed.")
    errors = []
    for unit in (LEGACY_ST_UNIT, BACKEND_UNIT):
        if unit in owned:
            result = _systemctl("stop", unit)
            if result.returncode:
                errors.append(result.stderr.strip() or f"Unable to stop {unit}")
    if errors:
        raise LauncherError("; ".join(errors))
    print("Cyberpunk RED GM service stopped.")


def status(config_home: Path) -> int:
    owned = _owned_units(config_home)
    if BACKEND_UNIT not in owned:
        print(f"{BACKEND_UNIT}: not installed")
        return 1
    result = _systemctl("is-active", BACKEND_UNIT)
    state = result.stdout.strip() or "inactive"
    print(f"{BACKEND_UNIT}: {state}")
    return 0 if state == "active" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("install")
    setup.add_argument("--project", type=Path, default=Path(__file__).resolve().parent)
    setup.add_argument("--browser", choices=["auto", "app", "tab"], default="auto")
    setup.add_argument("--lan", action="store_true", help="Allow LAN devices to connect to the installed service")
    setup.add_argument("--pin", default="", help="Optional room passcode for LAN co-op")
    start_p = sub.add_parser("start")
    start_p.add_argument("--no-browser", action="store_true")
    start_p.add_argument("--browser", choices=["auto", "app", "tab"], default="auto")
    sub.add_parser("stop")
    sub.add_parser("status")
    args = parser.parse_args(argv)
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    try:
        if args.command == "install":
            install(args.project, config_home, data_home, browser_mode=args.browser, lan=args.lan, pin=args.pin)
        elif args.command == "start":
            start(config_home, args.no_browser, browser_mode=args.browser)
        elif args.command == "stop":
            stop(config_home)
        else:
            return status(config_home)
    except (LauncherError, OSError) as exc:
        _notify(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
