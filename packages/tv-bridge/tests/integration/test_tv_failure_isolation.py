"""Wave 0 stub for TV failure isolation integration test (Phase 6).

Task ID: 06-04-02
Marked skip (not xfail) until Plan 04 — this test requires a full TVBridge
supervisor loop + pipeline integration that does not exist in Wave 1.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="implemented in Plan 04 — requires full TVBridge supervisor + pipeline")
async def test_pipeline_continues_when_tv_killed() -> None:
    """Pipeline continues with no skipped signals when TV Desktop is killed mid-session."""
    pass
