"""Storage domain — DuckDB connection + schema + upserts + Parquet partitioning.

Plan 01-04 ships:
- ``schema.sql`` — DDL single source of truth (bars, bar_gaps, instruments, runs)
- ``duckdb_store.DuckDBStore`` — connection + ensure_schema + ON CONFLICT upserts
  + Hive-partitioned Parquet writes (MD-04)
- ``runs`` (Task 2) — uuid7 + git_sha + adr_hash + param_hash + data_hash
  reproducibility recipe (FND-08)

Single-writer convention (MD-04): only the FastAPI process (Phase 3) and the
``seed_bars.py`` CLI (Plan 05) instantiate ``DuckDBStore``. There is no code
enforcement of this — the convention is documented here and in ``duckdb_store``.
"""

from __future__ import annotations

from .duckdb_store import DuckDBStore

__all__ = ["DuckDBStore"]
