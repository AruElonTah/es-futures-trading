"""Wave 0 stub for TVReplayDataSource tests (Phase 6).

Task ID: 06-03-02
Strict-xfail stub; Plan 03 flips it to a real test.
"""

from __future__ import annotations

import pytest


@pytest.mark.xfail(reason="implemented in Plan 03", strict=True)
async def test_fetch_bars(mock_mcp_session) -> None:
    """TVReplayDataSource.fetch_bars returns DataFrame with correct Bar columns and RTH-only rows."""
    pytest.fail("Plan 03 implements")
