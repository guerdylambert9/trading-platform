from __future__ import annotations

import os

import pytest

from trader.config import ENV_FILE_VAR, Settings, get_settings


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch):
    """Keep the developer's shell variables and .env files out of every test."""
    fields = {name.upper() for name in Settings.model_fields} | {ENV_FILE_VAR}
    for key in list(os.environ):
        if key.upper() in fields:
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
