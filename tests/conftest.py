"""Global pytest isolation so tests never read or mutate the user's live settings file."""
from __future__ import annotations

from pathlib import Path
import pytest


@pytest.fixture(autouse=True)
def _isolate_redgm_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("REDGM_SETTINGS_FILE", str(tmp_path / "settings.json"))
    for var in (
        "REDGM_ADMIN_USER",
        "REDGM_ADMIN_PASS",
        "REDGM_USER_USER",
        "REDGM_USER_PASS",
        "REDGM_AUTH_SECRET",
        "REDGM_ROOM_PIN",
        "REDGM_HOST",
        "REDGM_PORT",
        "REDGM_PUBLIC_URL",
        "REDGM_ALLOWED_ORIGINS",
    ):
        monkeypatch.delenv(var, raising=False)
