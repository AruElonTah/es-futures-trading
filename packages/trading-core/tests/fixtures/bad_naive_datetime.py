"""Fixture for the no-naive-tz pre-commit hook test (FND-05).

This file intentionally contains naive datetime calls. The
`scripts/hooks/no_naive_tz.py` AST scanner must REJECT this file
(exit 1 + emit a `<path>:<lineno>: ...` message for each violation).

DO NOT add `from datetime import datetime` aliases, decorators, or
`tz=` kwargs here — the whole point is that this file is the
positive-test for the hook's rejection path. Plan 01-05 Task 1.
"""

from datetime import datetime


def bad():
    return datetime.now()


def also_bad():
    return datetime.utcnow()
