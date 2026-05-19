"""Wall-clock EOD flatten scheduler — RM-07 / D-11.

Fires an async callback at ``session_close - lead_seconds`` wall-clock time
every calendar day. In paper mode, the callback is typically a no-op because
there are no live positions; Phase 6 will wire it to the live executor.

Design decisions:
  - No market-calendar check: the scheduler fires every day regardless of
    holidays or half-days. Flatten on a non-trading day is harmless (no open
    positions in paper mode). Calendar enforcement is Phase 6+.
  - No persistence of the last-fire time: a restart within the 90s sleep window
    will re-fire the callback on the same day. The callback is idempotent.
  - ZoneInfo used for DST-correct conversion (``America/New_York``).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from trading_core.logging import get_logger


class EodScheduler:
    """Fires an async callback at ``session_close - lead_seconds`` each day.

    Args:
        on_flatten: Async callable with no arguments; called when EOD fires.
        close_time_et: Cash session close in ``HH:MM`` format (ET). Matches
            ``Instrument.rth_close_et`` for ES/MES (``"16:00"``).
        lead_seconds: Fire this many seconds before ``close_time_et``.
            Default 60 → fires at 15:59:00 ET.
        tz: IANA timezone name for the session close. Default ``"America/New_York"``.
    """

    def __init__(
        self,
        *,
        on_flatten: Callable[[], Coroutine[Any, Any, None]],
        close_time_et: str = "16:00",
        lead_seconds: int = 60,
        tz: str = "America/New_York",
    ) -> None:
        self._on_flatten = on_flatten
        self._close_time_et = close_time_et
        self._lead_seconds = lead_seconds
        self._tz = ZoneInfo(tz)
        self._log = get_logger(__name__)

    async def run(self) -> None:
        """Main loop — sleeps until next fire time, calls on_flatten, repeats.

        The loop runs indefinitely; the caller cancels it via the asyncio task.
        After firing, sleeps 90 seconds to avoid a double-fire on the same day
        (the fire time is now in the past, so _next_fire_time() will return
        tomorrow's time; the extra sleep is a belt-and-suspenders guard).
        """
        while True:
            fire_at = self._next_fire_time()
            now_utc = datetime.now(timezone.utc)
            sleep_secs = (fire_at - now_utc).total_seconds()
            if sleep_secs > 0:
                self._log.debug(
                    "eod_scheduler.sleeping",
                    fire_at=fire_at.isoformat(),
                    sleep_secs=round(sleep_secs, 1),
                )
                await asyncio.sleep(sleep_secs)
            self._log.info("eod_scheduler.firing", fire_at=fire_at.isoformat())
            try:
                await self._on_flatten()
            except Exception:
                self._log.exception("eod_scheduler.on_flatten_error")
            # Sleep 90s to drift past the close time so _next_fire_time()
            # returns tomorrow's fire time on the next loop iteration.
            await asyncio.sleep(90)

    def _next_fire_time(self) -> datetime:
        """Compute next wall-clock fire time in UTC.

        Parses ``close_time_et`` (``HH:MM``) and subtracts ``lead_seconds`` to
        get the fire time in ET, then converts to UTC. If today's fire time is
        already in the past, returns tomorrow's fire time.

        Returns:
            A timezone-aware UTC datetime for the next fire time.
        """
        now_et = datetime.now(self._tz)
        close_h, close_m = (int(x) for x in self._close_time_et.split(":"))
        # Build today's close time in ET
        today_close_et = now_et.replace(
            hour=close_h, minute=close_m, second=0, microsecond=0
        )
        # Subtract lead seconds to get today's fire time
        today_fire_et = today_close_et - timedelta(seconds=self._lead_seconds)
        # Convert to UTC
        today_fire_utc = today_fire_et.astimezone(timezone.utc)

        now_utc = datetime.now(timezone.utc)
        if today_fire_utc > now_utc:
            return today_fire_utc

        # Today's fire time has already passed — return tomorrow's
        tomorrow_fire_et = today_fire_et + timedelta(days=1)
        return tomorrow_fire_et.astimezone(timezone.utc)
