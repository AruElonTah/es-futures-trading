"""Reproducibility helpers — uuid7 + git_sha + adr_hash + param_hash + data_hash.

Implements FND-08: every Phase 4+ optimization run's ``runs`` row records the
provenance fingerprint (run_id, git_sha, data_hash, param_hash, seed, adr_hash,
started_at, finished_at, status, notes). Phase 3's reproducibility CI test
re-computes ``data_hash`` for the canonical SPY-day fixture and compares
against the stored hex — a single drift between pandas/pyarrow patch versions
fails the gate (trust-the-numbers invariant).

Recipe references: 01-RESEARCH.md Pattern 7 (lines 786-847) + Open Question
O-4 (lines 1442-1446). ``pyarrow`` is pinned to ``>=17.0,<18.0`` in
``packages/trading-core/pyproject.toml`` to lock byte-stability across patch
upgrades (the three Parquet write flags below — compression=None,
use_dictionary=False, write_statistics=False — eliminate pyarrow's known
nondeterministic compression/metadata layers).
"""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import uuid6

# Default ADR path — the chain-of-trust anchor for every Phase 4+ run.
ADR_PATH = Path(".planning/decisions/0001-data-provider.md")

# Columns projected into the data_hash payload. Order matters — pyarrow
# preserves it on the Table and Parquet output.
_DATA_HASH_COLS = [
    "symbol",
    "timeframe",
    "ts_utc",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "rollover_seam",
    "provider",
]


def new_run_id() -> str:
    """Return a fresh UUIDv7 string.

    uuid7 is time-sortable, so the storage layer's ``ORDER BY run_id`` doubles
    as a chronological ordering for forensic replay (CLAUDE.md §audit log).
    """
    return str(uuid6.uuid7())


def git_sha() -> str:
    """Return the current HEAD SHA, or ``'unknown'`` when not in a git repo.

    The subprocess call has a hard timeout and silenced stderr so a missing
    ``git`` executable, a non-repo cwd, or a permission error all converge
    to the same fallback. Treating "no SHA" as a value (not an exception)
    keeps run-row writes infallible.
    """
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5.0,
        ).strip()
    except Exception:
        return "unknown"


def adr_hash(adr_path: Path | None = None) -> str:
    """Return sha256 hex of the ADR's verbatim bytes.

    Args:
        adr_path: optional override (used by tests). Defaults to the
            project-local ``.planning/decisions/0001-data-provider.md``.
    """
    path = adr_path if adr_path is not None else ADR_PATH
    return hashlib.sha256(path.read_bytes()).hexdigest()


def param_hash(args: dict) -> str:
    """Return sha256 hex of canonical-JSON-encoded ``args``.

    Canonicalization: sorted keys, compact separators, UTF-8 bytes, ``default=str``
    for ``date``/``datetime`` (ISO 8601 surrogate). Reordering keys does NOT
    change the hash; changing any value does.
    """
    canonical = json.dumps(
        args, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def data_hash(df: pd.DataFrame) -> str:
    """Deterministic byte-stable hash of a bar payload.

    Recipe (Pattern 7 / O-4):
        (1) sort by ``(symbol, timeframe, ts_utc)`` to remove row-order variance
        (2) project to ``_DATA_HASH_COLS`` (drops ``ingested_at`` / index)
        (3) write to a Parquet byte blob via pyarrow with
            ``compression="none"``, ``use_dictionary=False``,
            ``write_statistics=False`` (eliminates pyarrow's
            nondeterministic layers)
        (4) sha256 the buffer bytes.

    Returns:
        64-char lowercase sha256 hex.
    """
    projected = (
        df[_DATA_HASH_COLS]
        .sort_values(["symbol", "timeframe", "ts_utc"])
        .reset_index(drop=True)
    )
    table = pa.Table.from_pandas(projected, preserve_index=False)
    buf = io.BytesIO()
    pq.write_table(
        table,
        buf,
        compression="none",
        use_dictionary=False,
        write_statistics=False,
    )
    return hashlib.sha256(buf.getvalue()).hexdigest()
