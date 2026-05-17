"""safe_from_signals — lookahead-safe wrapper around vbt.Portfolio.from_signals.

Enforces:
  1. entries and exits are shifted by 1 (next-bar execution) — D-13
  2. price is a concrete array, never the string 'nextbar' (crashes Numba JIT)
  3. short_entries / short_exits are shifted when supplied; omitted entirely when None

See 03-RESEARCH.md §safe_from_signals Wrapper Pattern + §Pitfall 1 + §Pitfall 3.

Direct calls to vbt.Portfolio.from_signals() are blocked by the
no-direct-vbt-from-signals pre-commit hook (D-13); this module is explicitly
excluded from that hook — it is the ONLY legitimate call site.

Why .infer_objects(copy=False) after .fillna(False):
    pandas 2.2.x emits FutureWarning: Downcasting object dtype arrays on .fillna
    because shift(1) temporarily makes a boolean Series object-typed.
    Appending .infer_objects(copy=False) suppresses the warning and forces the
    correct dtype without a copy — see 03-RESEARCH.md §Pitfall 3.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
import vectorbt as vbt

if TYPE_CHECKING:
    pass

# NOTE: This is the ONLY legitimate call site for vbt.Portfolio.from_signals
# — pre-commit hook excludes this file (D-13).


def safe_from_signals(
    close: pd.Series,
    entries: pd.Series,
    exits: pd.Series,
    *,
    price: pd.Series,
    sl_stop: pd.Series | float | None = None,
    tp_stop: pd.Series | float | None = None,
    short_entries: pd.Series | None = None,
    short_exits: pd.Series | None = None,
    open: pd.Series | None = None,
    high: pd.Series | None = None,
    low: pd.Series | None = None,
    **kwargs,
) -> "vbt.Portfolio":
    """Lookahead-safe wrapper around vbt.Portfolio.from_signals.

    Applies entries.shift(1) + exits.shift(1) internally so the caller passes
    UNSHIFTED signal booleans (signal fires on bar N → execution fills at bar N+1).

    Args:
        close:         pd.Series with UTC DatetimeIndex — closing prices.
        entries:       Unshifted boolean Series. True = enter long this bar.
        exits:         Unshifted boolean Series. True = exit long this bar.
        price:         MUST be a pd.Series (or array) of fill prices (e.g., next-bar
                       open). Passing a string (e.g., 'nextbar') crashes Numba JIT
                       with an opaque TypingError — see 03-RESEARCH.md §Pitfall 1.
        sl_stop:       Stop-loss fraction ((entry-stop)/entry). Optional.
        tp_stop:       Take-profit fraction ((target-entry)/entry). Optional.
        short_entries: Unshifted boolean Series for short entries. Optional.
        short_exits:   Unshifted boolean Series for short exits. Optional.
        open:          pd.Series of open prices (required for intrabar stop/target).
        high:          pd.Series of high prices (required for intrabar stop/target).
        low:           pd.Series of low prices (required for intrabar stop/target).
        **kwargs:      Forwarded verbatim to vbt.Portfolio.from_signals (freq,
                       init_cash, size, direction, seed, …).

    Returns:
        vbt.Portfolio — the portfolio object returned by vbt.Portfolio.from_signals.

    Raises:
        ValueError:    If price is a string instance (D-13 guard).
    """
    # Guard: price must not be a string — Numba JIT crashes on strings (Pitfall 1).
    if isinstance(price, str):
        raise ValueError(
            "safe_from_signals: price must be an array of fill prices, not a string. "
            "Pass the next-bar open prices as a pd.Series. "
            "Passing price='nextbar' crashes Numba JIT."
        )

    # Shift entries/exits internally — caller passes UNSHIFTED signals.
    # Under pandas 2.2.x+, .shift(1) on a bool Series produces object dtype,
    # and .fillna(False) then emits FutureWarning about silent downcasting.
    # We use .where(notna(), False).astype(bool) which is FutureWarning-free
    # and produces the correct bool-dtype result. See 03-RESEARCH.md §Pitfall 3.
    def _shift_bool(s: pd.Series) -> pd.Series:
        shifted = s.shift(1)
        return shifted.where(shifted.notna(), other=False).astype(bool)

    shifted_entries = _shift_bool(entries)
    shifted_exits = _shift_bool(exits)

    # Shift short entries/exits only when the caller supplied them.
    shifted_short_entries = (
        _shift_bool(short_entries)
        if short_entries is not None
        else None
    )
    shifted_short_exits = (
        _shift_bool(short_exits)
        if short_exits is not None
        else None
    )

    # Build kwargs dict — only include optional keys when caller supplied them,
    # to avoid injecting unexpected None values into VBT's Numba-compiled inner loop.
    call_kwargs: dict = dict(
        close=close,
        entries=shifted_entries,
        exits=shifted_exits,
        price=price,
        **kwargs,
    )

    if sl_stop is not None:
        call_kwargs["sl_stop"] = sl_stop
    if tp_stop is not None:
        call_kwargs["tp_stop"] = tp_stop
    if short_entries is not None:
        call_kwargs["short_entries"] = shifted_short_entries
    if short_exits is not None:
        call_kwargs["short_exits"] = shifted_short_exits
    if open is not None:
        call_kwargs["open"] = open
    if high is not None:
        call_kwargs["high"] = high
    if low is not None:
        call_kwargs["low"] = low

    return vbt.Portfolio.from_signals(**call_kwargs)
