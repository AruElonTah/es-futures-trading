"""Wave 0 stubs for TV route tests (Phase 6).

Task IDs: 06-02-06, 06-02-07
Strict-xfail stubs; Plan 02 flips them to real tests.

The `client` fixture provides a minimal TestClient for the main API app.
Plan 02 will use (or replace) this fixture when it wires TVBridge into the
FastAPI lifespan and registers the tv.py router.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    """Minimal TestClient for the main API app (no TVBridge wired yet in Wave 1)."""
    from api.app import app
    return TestClient(app)


@pytest.mark.xfail(reason="implemented in Plan 02", strict=True)
def test_tv_focus(client: TestClient) -> None:
    """POST /tv/focus returns 202 Accepted; symbol validated against allowlist."""
    pytest.fail("Plan 02 implements")


@pytest.mark.xfail(reason="implemented in Plan 02", strict=True)
def test_create_delete_alert(client: TestClient) -> None:
    """POST /tv/alerts persists tv_alert_id to tv_alerts table; DELETE removes it."""
    pytest.fail("Plan 02 implements")
