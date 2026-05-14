"""Settings (Pydantic Settings) tests — FND-03.

Plan 01-02 / Task 3. Behaviors:
- Settings() constructs without a .env present (defaults apply).
- TWELVEDATA_API_KEY env var → settings.twelvedata_api_key as SecretStr.
- YAML (config/system.yaml) values merge in but do NOT override .env.
  Precedence (highest→lowest): .env > yaml > defaults.
- duckdb_path / parquet_root / audit_log_dir / default_provider defaults
  resolve to documented Path / Literal values.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr


def test_settings_constructs_with_no_env(monkeypatch, tmp_path):
    """No .env, no yaml — Settings still constructs via defaults."""

    monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)  # cwd has no .env / config/

    from trading_core.config import Settings

    s = Settings()
    assert s.twelvedata_api_key is None
    assert isinstance(s.duckdb_path, Path)
    assert s.default_provider == "tradingview"


def test_settings_reads_twelvedata_key_from_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # isolate from repo .env
    monkeypatch.setenv("TWELVEDATA_API_KEY", "fake-key-123")

    from trading_core.config import Settings

    s = Settings()
    assert isinstance(s.twelvedata_api_key, SecretStr)
    assert s.twelvedata_api_key.get_secret_value() == "fake-key-123"


def test_settings_duckdb_path_default(monkeypatch, tmp_path):
    monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)

    from trading_core.config import Settings

    s = Settings()
    # Default = data/duckdb/trading.duckdb (platform-agnostic separator).
    assert s.duckdb_path == Path("data/duckdb/trading.duckdb")


def test_settings_parquet_root_default(monkeypatch, tmp_path):
    monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    from trading_core.config import Settings

    s = Settings()
    assert s.parquet_root == Path("data/parquet")


def test_settings_audit_log_dir_default(monkeypatch, tmp_path):
    monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    from trading_core.config import Settings

    s = Settings()
    assert s.audit_log_dir == Path("data/logs/audit")


def test_settings_yaml_merges_but_env_wins(monkeypatch, tmp_path):
    """Precedence test: .env > yaml > defaults.

    Set both env var and yaml value for the same key; env must win.
    Set yaml-only value for a different key; yaml value must apply.
    """

    monkeypatch.chdir(tmp_path)
    # Write a yaml that tries to override default_provider AND duckdb_path.
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "system.yaml").write_text(
        'default_provider: "twelvedata"\n'
        'duckdb_path: "yaml/path/trading.duckdb"\n',
        encoding="utf-8",
    )
    # Env sets twelvedata_api_key only; yaml does NOT set it.
    monkeypatch.setenv("TWELVEDATA_API_KEY", "env-key")

    from trading_core.config import Settings

    s = Settings()
    # yaml took effect (these keys aren't in env)
    assert s.default_provider == "twelvedata"
    assert s.duckdb_path == Path("yaml/path/trading.duckdb")
    # env took effect
    assert s.twelvedata_api_key is not None
    assert s.twelvedata_api_key.get_secret_value() == "env-key"


def test_settings_yaml_loses_to_env(monkeypatch, tmp_path):
    """Both env and yaml set the same key → env wins."""

    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "system.yaml").write_text(
        'default_provider: "twelvedata"\n', encoding="utf-8"
    )
    monkeypatch.setenv("DEFAULT_PROVIDER", "tradingview")

    from trading_core.config import Settings

    s = Settings()
    assert s.default_provider == "tradingview"


def test_settings_secret_str_redacts_in_repr(monkeypatch, tmp_path):
    """SecretStr must redact value in str() / repr() — T-01-02-01 mitigation."""

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TWELVEDATA_API_KEY", "should-not-leak")
    from trading_core.config import Settings

    s = Settings()
    repr_text = repr(s)
    str_text = str(s)
    assert "should-not-leak" not in repr_text
    assert "should-not-leak" not in str_text
