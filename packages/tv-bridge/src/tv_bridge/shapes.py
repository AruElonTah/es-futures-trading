"""Pure-function MCP draw_shape payload builders (Phase 6 Plan 02, Task 1).

No class, no I/O, no side effects. Each function returns a dict that can be
passed directly as ``args`` to ``TVBridge.call_tool("draw_shape", ...)``.

MCP draw_shape schema (verified against tool definition):
    Required: shape (str), point ({time: int, price: float})
    Optional: point2 ({time: int, price: float}) — second corner for rectangle
              overrides (JSON str)  — style keys: linecolor, linewidth, linestyle
              text (str)           — label text

Security mitigations (T-06-02-01, T-06-02-03):
    - Every ``text`` field is capped to 64 characters via ``str(...)[:64]``
      to prevent runaway-string payloads that could crash TV Desktop's renderer.
    - Every numeric field passes through ``float()`` or ``int()``, which raises
      ``TypeError`` on non-numeric input before an MCP call is made.
"""

from __future__ import annotations

import json
from typing import Any


def entry_arrow_args(
    *,
    side: str,
    entry_price: float,
    signal_id: str,
    signal_ts_epoch: int,
) -> dict[str, Any]:
    """Return draw_shape kwargs for an entry horizontal_line marker.

    Args:
        side: "long" or "short" — controls line color.
        entry_price: Entry price level (numeric).
        signal_id: Signal identifier (used to cap text length only; not
            embedded in a SQL string — no injection risk here).
        signal_ts_epoch: Unix epoch seconds for the signal timestamp (point.time).

    Returns:
        dict suitable for ``call_tool("draw_shape", ...)``
    """
    price = float(entry_price)
    color = "#00ff88" if side == "long" else "#ff4444"
    text = str(f"ENTRY {side.upper()} {entry_price}")[:64]
    return {
        "shape": "horizontal_line",
        "point": {"time": int(signal_ts_epoch), "price": price},
        "overrides": json.dumps({"linecolor": color, "linewidth": 2}),
        "text": text,
    }


def stop_line_args(
    *,
    stop_price: float,
    signal_id: str,
    signal_ts_epoch: int,
) -> dict[str, Any]:
    """Return draw_shape kwargs for a stop-loss horizontal_line.

    Args:
        stop_price: Stop price level (numeric).
        signal_id: Signal identifier (used for text cap only).
        signal_ts_epoch: Unix epoch seconds for the signal timestamp (point.time).

    Returns:
        dict suitable for ``call_tool("draw_shape", ...)``
    """
    price = float(stop_price)
    text = str(f"STOP {stop_price}")[:64]
    return {
        "shape": "horizontal_line",
        "point": {"time": int(signal_ts_epoch), "price": price},
        "overrides": json.dumps({"linecolor": "#ff4444", "linewidth": 1, "linestyle": 2}),
        "text": text,
    }


def target_line_args(
    *,
    target_price: float,
    signal_id: str,
    signal_ts_epoch: int,
) -> dict[str, Any]:
    """Return draw_shape kwargs for a target horizontal_line.

    Args:
        target_price: Target price level (numeric).
        signal_id: Signal identifier (used for text cap only).
        signal_ts_epoch: Unix epoch seconds for the signal timestamp (point.time).

    Returns:
        dict suitable for ``call_tool("draw_shape", ...)``
    """
    price = float(target_price)
    text = str(f"TARGET {target_price}")[:64]
    return {
        "shape": "horizontal_line",
        "point": {"time": int(signal_ts_epoch), "price": price},
        "overrides": json.dumps({"linecolor": "#00aaff", "linewidth": 1, "linestyle": 2}),
        "text": text,
    }


def orb_box_args(
    *,
    orb_high: float,
    orb_low: float,
    session_open_ts: int,
    orb_end_ts: int,
) -> dict[str, Any]:
    """Return draw_shape kwargs for an ORB rectangle.

    The rectangle spans from session_open_ts to orb_end_ts horizontally and
    orb_low to orb_high vertically, representing the Opening Range Box.

    Args:
        orb_high: Upper boundary of the opening range (numeric).
        orb_low:  Lower boundary of the opening range (numeric).
        session_open_ts: Unix epoch seconds for 09:30 ET (top-left corner time).
        orb_end_ts: Unix epoch seconds for end of ORB window (bottom-right corner time).

    Returns:
        dict suitable for ``call_tool("draw_shape", ...)``
    """
    return {
        "shape": "rectangle",
        "point": {"time": int(session_open_ts), "price": float(orb_high)},
        "point2": {"time": int(orb_end_ts), "price": float(orb_low)},
        "overrides": json.dumps({"linecolor": "#ffcc00", "linewidth": 1}),
    }
