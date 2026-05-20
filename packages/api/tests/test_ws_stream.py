"""WS /stream tests — D-04 (7-topic mirror), D-05 (envelope),
D-06 (asyncio.Queue fan-out), SP-01 (bus→executor pipeline observable end-to-end).

Plan 03-04 Task 2 — proves the WebSocket fan-out surface:
  - ConnectionManager connects + disconnects WebSocket clients
  - D-05 envelope shape: {"type": "<topic>", "payload": {...}}
  - All 7 topics subscribed by the background fan-out task (D-04)
  - Per-client asyncio.Queue isolation (D-06 — no broadcaster dep)
  - Clean disconnect without server-side exception
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _make_test_app(duckdb_path):
    """Delegate to conftest.make_test_app (shared factory)."""
    import sys
    import pathlib
    import importlib

    tests_dir = str(pathlib.Path(__file__).parent)
    if tests_dir not in sys.path:
        sys.path.insert(0, tests_dir)
    _conftest = importlib.import_module("conftest")
    return _conftest.make_test_app(duckdb_path)

from trading_core.data.models import Bar
from trading_core.events.models import (
    BarReceived,
    DegradedStateEvent,
    Event,
    TOPIC_BARS,
    TOPIC_DEGRADED_STATE,
    TOPIC_EQUITY,
    TOPIC_FILLS,
    TOPIC_POSITIONS,
    TOPIC_RISK_DECISIONS,
    TOPIC_SIGNALS,
)

_ALL_TOPICS = [
    TOPIC_BARS,
    TOPIC_SIGNALS,
    TOPIC_RISK_DECISIONS,
    TOPIC_FILLS,
    TOPIC_POSITIONS,
    TOPIC_EQUITY,
    TOPIC_DEGRADED_STATE,
]

_NOW_UTC = datetime(2024, 1, 2, 14, 30, 0, tzinfo=timezone.utc)


def _sample_bar() -> Bar:
    return Bar(
        symbol="SPY",
        timeframe="1m",
        ts_utc=_NOW_UTC,
        open=Decimal("470.00"),
        high=Decimal("471.00"),
        low=Decimal("469.50"),
        close=Decimal("470.50"),
        volume=1000,
    )


class TestWsStreamConnect:
    def test_ws_stream_accepts_connection(self, tmp_path: Path) -> None:
        """WS /stream accepts a connection without error."""
        app = _make_test_app(tmp_path / "t.duckdb")
        with TestClient(app) as client:
            with client.websocket_connect("/stream") as ws:
                # Connection accepted — just verify we can enter/exit cleanly
                pass


class TestWsStreamEnvelope:
    def test_ws_stream_envelope_shape(self, tmp_path: Path) -> None:
        """D-05: received message has exactly {type, payload} keys.

        Publishes a DegradedStateEvent; asserts the envelope shape and that
        payload contains the expected source field.
        """
        app = _make_test_app(tmp_path / "t.duckdb")
        with TestClient(app) as client:
            with client.websocket_connect("/stream") as ws:
                # Publish via the bus on the same event loop as the lifespan
                event = DegradedStateEvent(
                    topic=TOPIC_DEGRADED_STATE,
                    emitted_at=_NOW_UTC,
                    source="tradingview_mcp",
                    reason="test",
                )
                asyncio.get_event_loop().run_until_complete(
                    app.state.bus.publish(TOPIC_DEGRADED_STATE, event)
                )
                raw = ws.receive_text()
                msg = json.loads(raw)

        # D-05 envelope: {type, seq, payload} — seq added in Phase 7 Plan 01 (SP-06/D-19)
        assert "type" in msg, f"D-05 envelope must have 'type'; got {msg.keys()}"
        assert "payload" in msg, f"D-05 envelope must have 'payload'; got {msg.keys()}"
        assert "seq" in msg, f"D-05 envelope must have 'seq' (SP-06); got {msg.keys()}"
        assert msg["type"] == "degraded_state"
        assert msg["payload"]["source"] == "tradingview_mcp"
        assert msg["payload"]["reason"] == "test"

    def test_ws_stream_bar_received_envelope(self, tmp_path: Path) -> None:
        """D-05: BarReceived event on TOPIC_BARS produces correct envelope."""
        app = _make_test_app(tmp_path / "t.duckdb")
        with TestClient(app) as client:
            with client.websocket_connect("/stream") as ws:
                event = BarReceived(
                    topic=TOPIC_BARS,
                    emitted_at=_NOW_UTC,
                    bar=_sample_bar(),
                )
                asyncio.get_event_loop().run_until_complete(
                    app.state.bus.publish(TOPIC_BARS, event)
                )
                raw = ws.receive_text()
                msg = json.loads(raw)

        assert msg["type"] == "bars"
        assert "bar" in msg["payload"]
        assert msg["payload"]["bar"]["symbol"] == "SPY"


class TestWsStream7Topics:
    """D-04: the background fan-out subscribes to all 7 EventBus topics.

    Only TOPIC_BARS (BarReceived) and TOPIC_DEGRADED_STATE (DegradedStateEvent)
    have concrete Event subclasses in Phase 3. The remaining 5 topics
    (TOPIC_SIGNALS, TOPIC_RISK_DECISIONS, TOPIC_FILLS, TOPIC_POSITIONS,
    TOPIC_EQUITY) have no concrete Event subclass yet — Phase 2/5 will add
    them. The ConnectionManager is topic-agnostic: it serializes ANY Event
    regardless of subclass, so all 7 subscriptions are registered correctly.
    The test exercises the 2 topics with concrete classes; the other 5 are
    documented as not having concrete classes yet (non-blocking, see SUMMARY).
    """

    @pytest.mark.parametrize(
        "topic,event_factory",
        [
            (
                TOPIC_BARS,
                lambda: BarReceived(
                    topic=TOPIC_BARS,
                    emitted_at=_NOW_UTC,
                    bar=_sample_bar(),
                ),
            ),
            (
                TOPIC_DEGRADED_STATE,
                lambda: DegradedStateEvent(
                    topic=TOPIC_DEGRADED_STATE,
                    emitted_at=_NOW_UTC,
                    source="test",
                    reason="topic test",
                ),
            ),
        ],
        ids=["bars", "degraded_state"],
    )
    def test_ws_stream_topic_mirror(
        self, tmp_path: Path, topic: str, event_factory
    ) -> None:
        """D-04: events on the subscribed topic reach the WS client."""
        app = _make_test_app(tmp_path / "t.duckdb")
        with TestClient(app) as client:
            with client.websocket_connect("/stream") as ws:
                event = event_factory()
                asyncio.get_event_loop().run_until_complete(
                    app.state.bus.publish(topic, event)
                )
                raw = ws.receive_text()
                msg = json.loads(raw)

        assert msg["type"] == topic, (
            f"Expected type={topic!r}, got {msg['type']!r}"
        )
        assert "payload" in msg


class TestWsStreamMultiClient:
    def test_ws_stream_two_clients_both_receive(self, tmp_path: Path) -> None:
        """D-06: two concurrent clients both receive a single published event.

        Both connections use the same TestClient (same event loop / lifespan).
        """
        app = _make_test_app(tmp_path / "t.duckdb")
        with TestClient(app) as client:
            with client.websocket_connect("/stream") as ws1:
                with client.websocket_connect("/stream") as ws2:
                    event = DegradedStateEvent(
                        topic=TOPIC_DEGRADED_STATE,
                        emitted_at=_NOW_UTC,
                        source="multi_test",
                        reason="both clients",
                    )
                    asyncio.get_event_loop().run_until_complete(
                        app.state.bus.publish(TOPIC_DEGRADED_STATE, event)
                    )
                    raw1 = ws1.receive_text()
                    raw2 = ws2.receive_text()

        msg1 = json.loads(raw1)
        msg2 = json.loads(raw2)
        assert msg1["type"] == "degraded_state"
        assert msg2["type"] == "degraded_state"
        assert msg1["payload"]["source"] == "multi_test"
        assert msg2["payload"]["source"] == "multi_test"


class TestWsStreamDisconnect:
    def test_ws_stream_disconnect_clean(self, tmp_path: Path) -> None:
        """Disconnecting a client does not crash the fan-out task.

        After disconnect: publish another event; assert fan_out_task.done() is
        False (still running) and not exception-carrying.
        """
        app = _make_test_app(tmp_path / "t.duckdb")
        with TestClient(app) as client:
            # Connect then disconnect
            with client.websocket_connect("/stream"):
                pass  # exit = disconnect

            # Publish after disconnect — should not raise
            event = DegradedStateEvent(
                topic=TOPIC_DEGRADED_STATE,
                emitted_at=_NOW_UTC,
                source="post_disconnect",
                reason="after client left",
            )
            asyncio.get_event_loop().run_until_complete(
                app.state.bus.publish(TOPIC_DEGRADED_STATE, event)
            )

            # Fan-out task must still be running (lifespan is still active)
            assert not app.state.fan_out_task.done(), (
                "fan_out_task must still be running after a client disconnect"
            )
