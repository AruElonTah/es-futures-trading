"""Pydantic Settings root (FND-03).

Single-root Settings per 01-RESEARCH.md Open Question O-3 — `api` and
`tv-bridge` import this same class rather than maintaining per-package
settings.

Precedence (highest → lowest): environment variables > .env file > YAML
file (config/system.yaml) > Python defaults. This is the order
`settings_customise_sources` returns sources in.

API keys are typed `SecretStr` so Pydantic v2's default repr redacts them
(threat T-01-02-01: API key in log lines). Structlog redaction at the
adapter boundary lands in Plan 04.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Tuple, Type

from pydantic import SecretStr
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)


class Settings(BaseSettings):
    """Project-wide configuration. Merges env > .env > yaml > defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # config/system.yaml is the merged YAML root per D-03.
        yaml_file="config/system.yaml",
        yaml_file_encoding="utf-8",
        # Allow extras in the yaml so adding new keys does not require code change.
        extra="ignore",
    )

    # Provider tokens.
    twelvedata_api_key: SecretStr | None = None

    # Storage roots.
    duckdb_path: Path = Path("data/duckdb/trading.duckdb")
    parquet_root: Path = Path("data/parquet")
    audit_log_dir: Path = Path("data/logs/audit")

    # Provider selection (ADR 0001: TradingView primary, Twelve Data secondary).
    default_provider: Literal["twelvedata", "tradingview"] = "tradingview"

    # TradingView MCP server path (WR-06: centralised here, read by both
    # tv_bridge.bridge and tv_bridge.replay — no more hardcoded paths).
    # Override via TV_MCP_SERVER_PATH env var or config/system.yaml.
    tv_mcp_server_path: str = r"C:\Users\Admin\tradingview-mcp-jackson"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        """Wire the YAML source between dotenv and defaults.

        Order (highest priority first): init kwargs > env > .env > YAML > secrets.
        """

        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )
