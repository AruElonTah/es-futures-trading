"""Phase 7 Plan 01 Task 2 — RED/GREEN tests for WS ConnectionManager seq counter.

Tests (SP-06 — sequence number gap detection):
1. Fresh ConnectionManager has _seq initialized to 0
2. First message dispatched via fan-out carries seq=1
3. Two consecutive messages have seq N and N+1 (monotonically increasing)
4. dict payloads get seq injected directly
5. Non-dict (Event) payloads get seq in the envelope
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from trading_core.events import EventBus
from trading_core.events.models import (
    TOPIC_DEGRADED_STATE,
    DegradedStateEvent,
)

_NOW_UTC = datetime(2024, 1, 2, 14, 30, 0, tzinfo=timezone.utc)


def _make_test_app_with_seq(duckdb_path):
    """Build a minimal test app that exposes the WS endpoint with the seq-aware ConnectionManager."""
    import sys
    import pathlib
    import importlib

    tests_dir = str(pathlib.Path(__file__).parent)
    if tests_dir not in sys.path:
        sys.path.insert(0, tests_dir)
    _conftest = importlib.import_module("conftest")
    return _conftest.make_test_app(duckdb_path)


class TestConnectionManagerSeqInit:
    def test_seq_counter_initializes_to_zero(self):
        """ConnectionManager._seq must initialize to 0."""
        from api.ws import ConnectionManager
        bus = EventBus()
        manager = ConnectionManager(bus)
        assert manager._seq == 0, (
            f"ConnectionManager._seq must start at 0; got {manager._seq}"
        )


class TestWsSeqMonotonic:
    def test_first_message_has_seq_one(self, tmp_path: Path) -> None:
        """The first WS message dispatched carries seq=1."""
        from fastapi.testclient import TestClient

        app = _make_test_app_with_seq(tmp_path / "t.duckdb")
        with TestClient(app) as client:
            with client.websocket_connect("/stream") as ws:
                event = DegradedStateEvent(
                    topic=TOPIC_DEGRADED_STATE,
                    emitted_at=_NOW_UTC,
                    source="test_seq",
                    reason="first message",
                )
                asyncio.get_event_loop().run_until_complete(
                    app.state.bus.publish(TOPIC_DEGRADED_STATE, event)
                )
                raw = ws.receive_text()
                msg = json.loads(raw)

        assert "seq" in msg, f"Message must contain 'seq' field; got keys: {msg.keys()}"
        assert msg["seq"] == 1, f"First message seq must be 1; got {msg['seq']}"

    def test_two_consecutive_messages_seq_monotonic(self, tmp_path: Path) -> None:
        """Two consecutive messages have seq N and N+1."""
        from fastapi.testclient import TestClient

        app = _make_test_app_with_seq(tmp_path / "t.duckdb")
        with TestClient(app) as client:
            with client.websocket_connect("/stream") as ws:
                for i in range(2):
                    event = DegradedStateEvent(
                        topic=TOPIC_DEGRADED_STATE,
                        emitted_at=_NOW_UTC,
                        source="test_seq",
                        reason=f"message {i}",
                    )
                    asyncio.get_event_loop().run_until_complete(
                        app.state.bus.publish(TOPIC_DEGRADED_STATE, event)
                    )

                raw1 = ws.receive_text()
                raw2 = ws.receive_text()

        msg1 = json.loads(raw1)
        msg2 = json.loads(raw2)

        assert "seq" in msg1, f"msg1 must have 'seq' field; got: {msg1.keys()}"
        assert "seq" in msg2, f"msg2 must have 'seq' field; got: {msg2.keys()}"
        assert msg2["seq"] == msg1["seq"] + 1, (
            f"seq must be monotonically increasing: msg1.seq={msg1['seq']}, "
            f"msg2.seq={msg2['seq']} (expected msg2.seq = msg1.seq + 1)"
        )

    def test_dict_payload_gets_seq_injected(self, tmp_path: Path) -> None:
        """Plain dict events (e.g., engine_state) get 'seq' injected into the dict."""
        from fastapi.testclient import TestClient
        from trading_core.events.models import TOPIC_ENGINE_STATE

        app = _make_test_app_with_seq(tmp_path / "t.duckdb")
        with TestClient(app) as client:
            with client.websocket_connect("/stream") as ws:
                # Publish a plain dict (same pattern as risk routes use for engine_state)
                asyncio.get_event_loop().run_until_complete(
                    app.state.bus.publish(
                        TOPIC_ENGINE_STATE,
                        {"type": "engine_state_changed", "payload": {"state": "running"}},
                    )
                )
                raw = ws.receive_text()
                msg = json.loads(raw)

        assert "seq" in msg, (
            f"Dict event must have 'seq' injected; got keys: {msg.keys()}"
        )
        assert isinstance(msg["seq"], int)

    def test_event_object_gets_seq_in_envelope(self, tmp_path: Path) -> None:
        """Non-dict (Event subclass) payloads carry 'seq' in the top-level envelope."""
        from fastapi.testclient import TestClient

        app = _make_test_app_with_seq(tmp_path / "t.duckdb")
        with TestClient(app) as client:
            with client.websocket_connect("/stream") as ws:
                event = DegradedStateEvent(
                    topic=TOPIC_DEGRADED_STATE,
                    emitted_at=_NOW_UTC,
                    source="envelope_test",
                    reason="event obj",
                )
                asyncio.get_event_loop().run_until_complete(
                    app.state.bus.publish(TOPIC_DEGRADED_STATE, event)
                )
                raw = ws.receive_text()
                msg = json.loads(raw)

        # The envelope for Event objects is: {"type": ..., "seq": ..., "payload": {...}}
        assert "seq" in msg, f"Event envelope must have 'seq'; got: {msg.keys()}"
        assert "payload" in msg
        assert "type" in msg
        assert isinstance(msg["seq"], int)
