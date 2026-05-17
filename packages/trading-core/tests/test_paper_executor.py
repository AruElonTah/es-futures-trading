"""Wave 0 placeholder for PaperExecutor tests — BT-03, BT-08.

Requirements:
  BT-03 — Fill simulation: next-bar-open entry, session-phase-aware slippage
           (>= 2 ticks during 9:30-9:45 ET, 1 tick off-peak), worst-case
           intrabar stop/target (D-12: stop-first when both hit same bar).
  BT-08 — EOD forced flat at last RTH bar: sum(positions) == 0 after session end.

Analog: packages/trading-core/tests/test_duckdb_store.py (tmp_path fixtures + assertion)

This file is a Wave 0 stub. Wave 2 Plan 02 implements PaperExecutor and fills in
the real tests.
"""

import pytest


@pytest.mark.xfail(reason="Wave 2 Plan 02 — not yet implemented", strict=True)
def test_placeholder_until_wave_2():
    raise NotImplementedError
