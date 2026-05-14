#!/usr/bin/env python3
"""Pre-commit hook: forbid datetime.now() / datetime.utcnow() without tz (FND-05).

Why AST and not regex?
    A regex-based hook fires on string literals, docstrings, and comments
    containing the phrase 'datetime.now()'. False positives turn the hook
    into a # noqa-spam generator and developers learn to ignore it.
    See 01-RESEARCH.md Pitfall 8 (lines 1031-1078).

What gets flagged:
    - `datetime.utcnow()` — unconditionally (deprecated in 3.12, always naive).
    - `datetime.now()` with no positional arg AND no `tz=` kwarg — naive.

What does NOT trigger:
    - `datetime.now(tz=timezone.utc)` — tz= kwarg present.
    - `datetime.now(timezone.utc)` — positional tz argument.
    - `# comment mentioning datetime.now()` — AST sees no call.
    - `'''docstring mentioning datetime.now()'''` — AST sees no call.
    - `some_other.now()` — only flags calls where the immediate attribute
      receiver is the name `datetime`.

CLI shape:
    python scripts/hooks/no_naive_tz.py <file1> <file2> ...

    Exits 0 if all files are clean; exits 1 if any file contains a violation
    AND prints `<path>:<lineno>: <message>` per violation.

Plan 01-05 Task 1.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path


def lint(path: Path) -> list[tuple[int, str]]:
    """Return [(lineno, message), ...] for every naive-datetime call in `path`.

    Empty list = clean file. Caller is responsible for printing each
    diagnostic with the path prefix.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        # Unreadable files are out of scope for this hook — pre-commit's
        # types filter usually handles binary skip, but defend in depth.
        return []

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        # Don't punish a syntactically-broken file twice (Python compiler /
        # other hooks will catch it). Return clean here.
        return []

    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Only match `<receiver>.now()` / `<receiver>.utcnow()`.
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr not in ("now", "utcnow"):
            continue
        # Only match when the receiver is the bare name `datetime`.
        if not (isinstance(func.value, ast.Name) and func.value.id == "datetime"):
            continue

        if func.attr == "utcnow":
            # datetime.utcnow() is always naive AND deprecated in 3.12.
            violations.append(
                (
                    node.lineno,
                    "datetime.utcnow() is deprecated and produces a naive timestamp; "
                    "use datetime.now(tz=timezone.utc)",
                )
            )
            continue

        # datetime.now(...) — needs SOMETHING tz-like.
        # A positional argument counts (`datetime.now(timezone.utc)`).
        # A `tz=` kwarg counts (`datetime.now(tz=timezone.utc)`).
        # Bare `datetime.now()` is the violation we want.
        kw_names = {kw.arg for kw in node.keywords if kw.arg is not None}
        if "tz" not in kw_names and not node.args:
            violations.append(
                (
                    node.lineno,
                    "datetime.now() without tz= produces naive timestamp",
                )
            )

    return violations


def main(argv: list[str]) -> int:
    """CLI entry — accepts file paths in `argv[1:]`. Returns process exit code."""
    rc = 0
    for arg in argv[1:]:
        p = Path(arg)
        for lineno, msg in lint(p):
            print(f"{p}:{lineno}: {msg}")
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
