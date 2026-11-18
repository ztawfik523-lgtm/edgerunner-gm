import importlib.util
from pathlib import Path
import subprocess

import pytest

LAUNCHER_PATH = Path(__file__).resolve().parents[1] / "launcher.py"
spec = importlib.util.spec_from_file_location("launcher", LAUNCHER_PATH)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def setup_tree(tmp_path):
    project = tmp_path / "project%dir"
    project.mkdir()
    (project / "redkb.py").touch()
    python = project / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.touch()
    return project


def test_install_generates_single_managed_unit_and_desktop(tmp_path, monkeypatch):
    project = setup_tree(tmp_path)
    config, data = tmp_path / "config", tmp_path / "data"
    # Pre-seed an old managed SillyTavern unit to confirm cleanup.
    units = config / "systemd/user"
    units.mkdir(parents=True)
    (units / launcher.LEGACY_ST_UNIT).write_text(launcher.MARKER)

    calls = []
    monkeypatch.setattr(
        launcher,
        "_systemctl",
        lambda *a, **k: calls.append(a) or subprocess.CompletedProcess(a, 0, "", ""),
    )
    launcher.install(project, config, data)
    back = (units / launcher.BACKEND_UNIT).read_text()
    desktop = (data / "applications/cyberpunk-red-gm.desktop").read_text()
    assert launcher.MARKER in back and launcher.MARKER in desktop
    assert f'WorkingDirectory={str(project).replace("%", "%%")}\n' in back
    assert str(project / ".venv/bin/python").replace("%", "%%") in back
    assert "serve --host 127.0.0.1 --port 8765" in back
    assert "Terminal=false" in desktop and "Actions=Stop;" in desktop
    assert "WantedBy=default.target" in back
    assert not (units / launcher.LEGACY_ST_UNIT).exists()
    assert ("stop", launcher.LEGACY_ST_UNIT) in calls
    assert ("daemon-reload",) in calls


def test_install_refuses_foreign_collision(tmp_path):
    project = setup_tree(tmp_path)
    config = tmp_path / "config"
    units = config / "systemd/user"
    units.mkdir(parents=True)
    (units / launcher.BACKEND_UNIT).write_text("foreign")
    with pytest.raises(launcher.LauncherError, match="Refusing"):
        launcher.install(project, config, tmp_path / "data")


def test_stop_only_stops_owned_named_units(tmp_path, monkeypatch):
    units = tmp_path / "systemd/user"
    units.mkdir(parents=True)
    (units / launcher.BACKEND_UNIT).write_text(launcher.MARKER)
    calls = []
    monkeypatch.setattr(
        launcher,
        "_systemctl",
        lambda *args, **kwargs: calls.append(args) or subprocess.CompletedProcess(args, 0, "", ""),
    )
    launcher.stop(tmp_path)
    assert calls == [("stop", launcher.BACKEND_UNIT)]


def test_status_missing_unit_reports_and_fails(tmp_path, capsys):
    assert launcher.status(tmp_path) == 1
    output = capsys.readouterr().out
    assert f"{launcher.BACKEND_UNIT}: not installed" in output


def test_port_conflict_does_not_start_or_kill(tmp_path, monkeypatch):
    units = tmp_path / "systemd/user"
    units.mkdir(parents=True)
    (units / launcher.BACKEND_UNIT).write_text(launcher.MARKER)
    calls = []
    monkeypatch.setattr(
        launcher,
        "_systemctl",
        lambda *args, **kwargs: calls.append(args) or subprocess.CompletedProcess(args, 1, "", ""),
    )
    monkeypatch.setattr(launcher, "_port_open", lambda port: port == 8765)
    with pytest.raises(launcher.LauncherError, match="occupied"):
        launcher.start(tmp_path, no_browser=True)
    assert calls == [("is-active", "--quiet", launcher.BACKEND_UNIT)]


def test_readiness_timeout_rolls_back_started_unit(tmp_path, monkeypatch):
    units = tmp_path / "systemd/user"
    units.mkdir(parents=True)
    (units / launcher.BACKEND_UNIT).write_text(launcher.MARKER)
    calls = []

    def systemctl(*args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 1 if args[:2] == ("is-active", "--quiet") else 0, "", "")

    monkeypatch.setattr(launcher, "_systemctl", systemctl)
    monkeypatch.setattr(launcher, "_port_open", lambda port: False)
    monkeypatch.setattr(launcher, "_ready", lambda url: False)
    monkeypatch.setattr(launcher.time, "monotonic", iter([0, 31]).__next__)
    monkeypatch.setattr(launcher.time, "sleep", lambda seconds: None)
    with pytest.raises(launcher.LauncherError, match="30 seconds"):
        launcher.start(tmp_path, no_browser=True)
    assert ("stop", launcher.BACKEND_UNIT) in calls


def test_ready_endpoint_requires_managed_unit_active(tmp_path, monkeypatch):
    units = tmp_path / "systemd/user"
    units.mkdir(parents=True)
    (units / launcher.BACKEND_UNIT).write_text(launcher.MARKER)
    calls = []

    def systemctl(*args, **kwargs):
        calls.append(args)
        if args[:2] == ("is-active", "--quiet"):
            return subprocess.CompletedProcess(args, 1, "", "")
        if args == ("is-active", launcher.BACKEND_UNIT):
            return subprocess.CompletedProcess(args, 3, "inactive\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(launcher, "_systemctl", systemctl)
    monkeypatch.setattr(launcher, "_port_open", lambda port: False)
    monkeypatch.setattr(launcher, "_ready", lambda url: True)

    with pytest.raises(launcher.LauncherError, match=launcher.BACKEND_UNIT):
        launcher.start(tmp_path, no_browser=True)
    assert ("is-active", launcher.BACKEND_UNIT) in calls
    assert ("stop", launcher.BACKEND_UNIT) in calls


def test_open_ui_prefers_app_window_and_falls_back(monkeypatch):
    launched = []

    class DummyPopen:
        def __init__(self, cmd, **kwargs):
            launched.append(cmd)

    monkeypatch.setattr(launcher.subprocess, "Popen", DummyPopen)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/chromium" if name == "chromium" else None)
    launcher._open_ui("http://127.0.0.1:8765/", browser_mode="auto")
    assert launched[-1] == ["/usr/bin/chromium", "--app=http://127.0.0.1:8765/"]

    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/xdg-open" if name == "xdg-open" else None)
    launcher._open_ui("http://127.0.0.1:8765/", browser_mode="auto")
    assert launched[-1] == ["/usr/bin/xdg-open", "http://127.0.0.1:8765/"]


def test_venv_symlink_is_not_resolved_in_unit(tmp_path, monkeypatch):
    project = setup_tree(tmp_path)
    py = project / ".venv/bin/python"
    py.unlink()
    py.symlink_to("/usr/bin/python3")
    monkeypatch.setattr(launcher, "_systemctl", lambda *a, **kw: subprocess.CompletedProcess(a, 0, "", ""))
    config = tmp_path / "config"
    launcher.install(project, config, tmp_path / "data")
    contents = (config / "systemd/user" / launcher.BACKEND_UNIT).read_text()
    assert str(py).replace("%", "%%") in contents
    assert 'ExecStart="/usr/bin/python3"' not in contents


def test_systemd_and_desktop_escaping():
    assert launcher._exec_quote('/home/$name/100%') == '"/home/$$name/100%%"'
    assert launcher._desktop_quote('a\\b') == '"a\\\\\\\\b"'
    with pytest.raises(launcher.LauncherError):
        launcher._systemd_quote('path\nExecStart=bad')
