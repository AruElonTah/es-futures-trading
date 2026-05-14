"""Verify the Phase 0 spike artifacts exist on disk and are non-empty.

PHASE 0 SPIKE — DO NOT IMPORT FROM PRODUCTION CODE.

Re-runnable: `.venv-spike/Scripts/python.exe scripts/spike/verify_artifacts.py`
   (also works under any Python 3.11+; stdlib-only).
Exits 0 if all manifest entries exist and meet their minimum sizes;
exits 1 listing the failures otherwise.
"""

import sys
from pathlib import Path

# (path, minimum_bytes) — minimum sizes are chosen to catch empty / placeholder
# files without being so tight that legitimate-but-compact artifacts trip the
# gate. The tv-mcp-stderr.log threshold is intentionally low (50 bytes) because
# mcp SDK 1.x does not expose subprocess stderr; the file is a placeholder note
# documenting that limitation rather than a captured server-stderr stream.
MANIFEST: list[tuple[str, int]] = [
    (".planning/research/spike-0/twelvedata-probe.json", 200),
    (".planning/research/spike-0/spy-bar-budget.md",     500),
    (".planning/research/spike-0/tv-mcp-tools.json",     200),
    (".planning/research/spike-0/tv-mcp-transcript.log", 500),
    (".planning/research/spike-0/tv-mcp-stderr.log",      50),
    (".planning/research/spike-0/tv-restart-test.log",   500),
    (".planning/research/spike-0/comparison-table.md",  1000),
    (".planning/decisions/0001-data-provider.md",       1500),
]


def main() -> int:
    failures: list[str] = []
    for path_str, min_size in MANIFEST:
        p = Path(path_str)
        if not p.exists():
            print(f"FAIL: missing {path_str}")
            failures.append(path_str)
            continue
        size = p.stat().st_size
        if size < min_size:
            print(f"FAIL: {path_str} is {size} bytes (need >= {min_size})")
            failures.append(path_str)
            continue
        print(f"PASS: {path_str} ({size} bytes)")

    total = len(MANIFEST)
    if failures:
        print(f"=== {len(failures)} failure(s) of {total} ===")
        return 1
    print(f"=== ALL {total} ARTIFACTS PRESENT AND NON-EMPTY ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
