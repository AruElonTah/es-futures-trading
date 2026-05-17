#!/usr/bin/env python3
"""Pre-commit hook: block direct vbt.Portfolio.from_signals() calls (D-13).

Why this hook exists:
    Direct calls to vbt.Portfolio.from_signals() bypass the lookahead-safety
    enforcement in safe_from_signals(). The wrapper in
    packages/trading-core/src/trading_core/backtest/safe_signals.py
    is the only legitimate call site — it applies entries.shift(1) internally
    and rejects price='nextbar' (which crashes Numba JIT).

    This hook is the D-13 enforcement mechanism. See 03-CONTEXT.md §D-13
    and 03-RESEARCH.md §Pre-commit Hook Pattern.

What gets flagged:
    Any line matching the regex for 'vbt.Portfolio.from_signals(' in a
    tracked Python file, EXCEPT files in the exclude list below.

    Uses regex (not AST) — the call shape is unambiguous in Python source and
    a docstring containing this exact phrase is not a real concern. The regex
    is a linear scan with no catastrophic backtracking (T-03-01-04: accept).

Excluded files (pre-commit exclude list, not checked here):
    - packages/trading-core/src/trading_core/backtest/safe_signals.py
    - scripts/hooks/no_direct_vbt.py (this file)
    - packages/trading-core/tests/test_safe_signals.py
    - packages/trading-core/tests/integration/test_lookahead.py

CLI shape:
    python scripts/hooks/no_direct_vbt.py <file1> <file2> ...

    Exits 0 if all files are clean; exits 1 if any file contains a violation
    AND prints `<path>:<lineno>: <message>` per violation.

Plan 03-01 Task 3.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PATTERN = re.compile(r"vbt\.Portfolio\.from_signals\s*\(")


def main(argv: list[str]) -> int:
    """CLI entry — accepts file paths in argv[1:]. Returns process exit code."""
    errors: list[str] = []
    for arg in argv[1:]:
        path = Path(arg)
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            # Unreadable files are out of scope — skip silently (mirrors no_naive_tz.py).
            continue
        for lineno, line in enumerate(source.splitlines(), 1):
            if PATTERN.search(line):
                errors.append(
                    f"{path}:{lineno}: direct vbt.Portfolio.from_signals() call blocked. "
                    f"Use safe_from_signals() instead."
                )
    if errors:
        print("\n".join(errors))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
