"""Global pytest isolation so tests never read or mutate the user's live settings file."""
from __future__ import annotations

from pathlib import Path
import pytest


@pytest.fixture(autouse=True)
def _isolate_redgm_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("REDGM_SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.setenv("REDGM_BOOTSTRAP_TOKEN", "test-bootstrap-token-" + ("a" * 40))
    for var in (
        "REDGM_ADMIN_USER",
        "REDGM_ADMIN_PASS",
        "REDGM_USER_USER",
        "REDGM_USER_PASS",
        "REDGM_ROOM_PIN",
        "REDGM_HOST",
        "REDGM_PORT",
        "REDGM_PUBLIC_URL",
        "REDGM_ALLOWED_ORIGINS",
    ):
        monkeypatch.delenv(var, raising=False)
