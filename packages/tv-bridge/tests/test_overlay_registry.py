"""Wave 0 stubs for overlay registry tests (Phase 6).

Task IDs: 06-02-04, 06-02-05, 06-04-01
These stubs are strict-xfail; Plan 02 and Plan 04 flip them to real tests.
"""

from __future__ import annotations

import pytest


@pytest.mark.xfail(reason="implemented in Plan 02", strict=True)
def test_write_overlay(in_memory_store) -> None:
    """tv_overlays row written with correct (strategy_id, signal_id, shape_id) tuple."""
    pytest.fail("Plan 02 implements")


@pytest.mark.xfail(reason="implemented in Plan 02", strict=True)
def test_cap_enforcement(in_memory_store, mock_mcp_session) -> None:
    """201st draw_shape call refused; tv_overlays cap enforced."""
    pytest.fail("Plan 02 implements")


@pytest.mark.xfail(reason="implemented in Plan 04", strict=True)
def test_nightly_cleanup(in_memory_store) -> None:
    """Nightly cleanup removes tv_overlays rows older than 5 trading days."""
    pytest.fail("Plan 04 implements")
