"""Fixture for the gitleaks pre-commit hook test (FND-04).

This file intentionally contains a synthetic, realistic-shaped API-key
string so the gitleaks pre-commit hook will flag it. The string below
matches gitleaks' built-in `generic-api-key` rule (32-char hex assigned
to a variable that looks like an API key).

DO NOT remove this fixture from `tests/fixtures/`. The integration test
`tests/integration/test_pre_commit_hooks.py` passes this path to
`pre-commit run gitleaks --files <path>` and asserts a non-zero exit
code. Plan 01-05 Task 1.

This fixture must NOT be picked up by pytest collection because it
contains only a module-level string — it's safe to import.
"""

# Synthetic API key — NEVER a real credential. 32 hex chars matching
# gitleaks's generic-api-key entropy heuristic.
TWELVEDATA_API_KEY = "abc123def456ghi789jkl012mno345pq"  # noqa: S105
