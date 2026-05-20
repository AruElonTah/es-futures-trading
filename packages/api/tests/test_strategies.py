"""Wave 0 test stubs for strategies routes (Plan 07-02 work).

These stubs are discoverable by pytest and marked xfail so they appear in the
test report. Plan 07-02 will implement GET /strategies, PUT /strategies/{id}/params,
POST /strategies/{id}/toggle endpoints and turn these GREEN.

Requirements: UI-07 (Strategy Controls panel), D-17 (new API routes).
"""

from __future__ import annotations

import pytest


@pytest.mark.xfail(strict=False, reason="TODO: implement strategies routes in Plan 07-02")
def test_get_strategies_returns_list():
    """GET /strategies returns a list of registered strategies with current params.

    Expected shape:
        [{"strategy_id": "orb-v1", "name": "...", "params": {...}, "enabled": bool}, ...]
    """
    pytest.skip("TODO Plan 07-02: implement GET /strategies route")


@pytest.mark.xfail(strict=False, reason="TODO: implement strategies routes in Plan 07-02")
def test_put_strategy_params_200():
    """PUT /strategies/{id}/params with valid params returns 200 and writes YAML.

    Validates params via Pydantic ORBConfig, writes config/strategies/{id}.yaml,
    and publishes TOPIC_STRATEGY_RELOAD on the EventBus. Returns updated params.
    """
    pytest.skip("TODO Plan 07-02: implement PUT /strategies/{id}/params route")


@pytest.mark.xfail(strict=False, reason="TODO: implement strategies routes in Plan 07-02")
def test_put_strategy_params_422():
    """PUT /strategies/{id}/params with invalid params returns 422 with error detail.

    D-16: server-side Pydantic validation only. Invalid params (e.g., negative
    opening_range_minutes) return 422 with the validator message in 'detail'.
    """
    pytest.skip("TODO Plan 07-02: implement PUT /strategies/{id}/params 422 validation")


@pytest.mark.xfail(strict=False, reason="TODO: implement strategies routes in Plan 07-02")
def test_post_strategy_toggle():
    """POST /strategies/{id}/toggle toggles on/off state and writes to engine_state table.

    Returns the new enabled state. Publishes bus event for engine to react.
    """
    pytest.skip("TODO Plan 07-02: implement POST /strategies/{id}/toggle route")
