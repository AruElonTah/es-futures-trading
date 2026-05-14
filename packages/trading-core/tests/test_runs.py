"""Tests for ``trading_core.storage.runs`` reproducibility helpers (FND-08).

Covers:
- ``new_run_id()`` returns a string parseable as a UUIDv7.
- ``git_sha()`` returns the HEAD SHA when run inside a repo; ``'unknown'`` when
  run outside one (probed by chdir to a non-repo tmp directory).
- ``adr_hash()`` is the sha256 of the ADR bytes; deterministic across runs.
- ``param_hash`` is canonical-JSON sha256 and key-order insensitive.
- ``data_hash`` is deterministic across runs, row-order insensitive, and DOES
  change when a value changes.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from trading_core.storage.runs import (
    adr_hash,
    data_hash,
    git_sha,
    new_run_id,
    param_hash,
)


# ---------------------------------------------------------------------------
# new_run_id
# ---------------------------------------------------------------------------


class TestNewRunId:
    def test_returns_uuid7_string(self) -> None:
        import uuid6

        rid = new_run_id()
        assert isinstance(rid, str)
        # Round-trip through uuid6.UUID — invalid v7 strings raise ValueError.
        u = uuid6.UUID(rid)
        assert u.version == 7

    def test_run_ids_are_time_sortable(self) -> None:
        import time

        a = new_run_id()
        time.sleep(0.005)
        b = new_run_id()
        # uuid7 is time-sortable — lexicographic order matches generation order.
        assert a < b


# ---------------------------------------------------------------------------
# git_sha
# ---------------------------------------------------------------------------


class TestGitSha:
    def test_matches_subprocess_rev_parse(self) -> None:
        expected = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip()
        assert git_sha() == expected

    def test_returns_unknown_outside_repo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        # tmp_path is not a git repo. git_sha must return the fallback.
        assert git_sha() == "unknown"


# ---------------------------------------------------------------------------
# adr_hash
# ---------------------------------------------------------------------------


class TestAdrHash:
    def test_round_trip_against_known_bytes(self, tmp_path: Path) -> None:
        # Write known bytes to a tmp ADR file and assert the hash matches.
        body = b"# 0001 - data-provider\n\nStatus: accepted\n\n(test bytes)\n"
        adr = tmp_path / "0001-data-provider.md"
        adr.write_bytes(body)
        expected = hashlib.sha256(body).hexdigest()
        assert adr_hash(adr) == expected

    def test_deterministic_default_adr(self) -> None:
        # Running twice against the on-disk ADR must produce identical hex.
        a = adr_hash()
        b = adr_hash()
        assert a == b
        # And it must be a 64-char sha256 hex.
        assert len(a) == 64
        assert all(c in "0123456789abcdef" for c in a)


# ---------------------------------------------------------------------------
# param_hash
# ---------------------------------------------------------------------------


class TestParamHash:
    def test_canonical_json_key_order_invariant(self) -> None:
        h1 = param_hash({"symbol": "SPY", "tf": "1m", "from": date(2024, 1, 1)})
        h2 = param_hash({"tf": "1m", "from": date(2024, 1, 1), "symbol": "SPY"})
        assert h1 == h2

    def test_value_change_changes_hash(self) -> None:
        h1 = param_hash({"symbol": "SPY", "tf": "1m"})
        h2 = param_hash({"symbol": "ES", "tf": "1m"})
        assert h1 != h2

    def test_returns_sha256_hex(self) -> None:
        h = param_hash({"x": 1})
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# data_hash — Pattern 7 recipe (FND-08 + O-4)
# ---------------------------------------------------------------------------


def _bars_df_for_hash(close_override: dict[int, float] | None = None) -> pd.DataFrame:
    """Build a small canonical bar DataFrame for the data_hash tests.

    Columns match the data_hash projection order: ``[symbol, timeframe,
    ts_utc, open, high, low, close, volume, rollover_seam, provider]``.
    """
    rows = []
    start = datetime(2024, 6, 12, 13, 30, tzinfo=timezone.utc)
    for i in range(30):
        ts = start.replace(minute=30 + i) if (30 + i) < 60 else start.replace(
            hour=14, minute=(30 + i) - 60
        )
        base = 100.0 + i * 0.01
        close = base + 0.02
        if close_override and i in close_override:
            close = close_override[i]
        rows.append(
            {
                "symbol": "SPY",
                "timeframe": "1m",
                "ts_utc": ts,
                "open": base,
                "high": base + 0.05,
                "low": base - 0.05,
                "close": close,
                "volume": 1000 + i,
                "rollover_seam": False,
                "provider": "twelve_data",
            }
        )
    return pd.DataFrame(rows)


class TestDataHash:
    def test_deterministic_same_df(self) -> None:
        a = data_hash(_bars_df_for_hash())
        b = data_hash(_bars_df_for_hash())
        assert a == b

    def test_row_order_invariant(self) -> None:
        df = _bars_df_for_hash()
        a = data_hash(df)
        b = data_hash(df.iloc[::-1].reset_index(drop=True))
        assert a == b

    def test_value_change_changes_hash(self) -> None:
        a = data_hash(_bars_df_for_hash())
        b = data_hash(_bars_df_for_hash(close_override={5: 999.99}))
        assert a != b

    def test_returns_sha256_hex(self) -> None:
        h = data_hash(_bars_df_for_hash())
        assert len(h) == 64
