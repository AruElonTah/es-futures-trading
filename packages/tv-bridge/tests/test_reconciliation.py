"""Wave 0 stubs for reconciliation tests (Phase 6).

Task IDs: 06-03-03, 06-03-04
Strict-xfail stubs; Plan 03 flips them to real tests.
"""

from __future__ import annotations

import pytest


@pytest.mark.xfail(reason="implemented in Plan 03", strict=True)
async def test_price_divergence(in_memory_store) -> None:
    """Reconciliation detects >0.05% price divergence between TV ES and Twelve Data SPY-proxy."""
    pytest.fail("Plan 03 implements")


@pytest.mark.xfail(reason="implemented in Plan 03", strict=True)
async def test_audit_log_write(in_memory_store) -> None:
    """Reconciliation writes audit_log row with topic='reconciliation_alert' on divergence."""
    pytest.fail("Plan 03 implements")
