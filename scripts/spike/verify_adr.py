"""Verify the Phase 0 ADR shape.

PHASE 0 SPIKE — DO NOT IMPORT FROM PRODUCTION CODE.

Re-runnable: `.venv-spike/Scripts/python.exe scripts/spike/verify_adr.py`.
Exits 0 if the ADR passes all checks, non-zero with a clear diagnostic otherwise.

Stdlib-only by design — pyproject.toml does not exist yet (Phase 1 deliverable).
PyYAML is used opportunistically if importable; otherwise a tiny in-house parser
handles the flat MADR frontmatter shape.
"""

import re
import sys
from pathlib import Path

ADR_PATH = Path(".planning/decisions/0001-data-provider.md")

REQUIRED_FM_KEYS = {
    "status", "deciders", "date", "adr_id", "slug",
    "supersedes", "superseded_by", "tags",
}

REQUIRED_SECTIONS = [
    "## Status",
    "## Context",
    "## Decision Drivers",
    "## Considered Options",
    "## Decision",
    "## Consequences",
    "## Verification artifacts",
    "## Pros and Cons of the Options",
]

REQUIRED_SUBSECTION = "### When to revisit"

CITED_ARTIFACTS = [
    ".planning/research/spike-0/twelvedata-probe.json",
    ".planning/research/spike-0/spy-bar-budget.md",
    ".planning/research/spike-0/tv-mcp-tools.json",
    ".planning/research/spike-0/tv-mcp-transcript.log",
    ".planning/research/spike-0/tv-restart-test.log",
    ".planning/research/spike-0/comparison-table.md",
]

SIZE_MIN_BYTES = 1500
SIZE_MAX_BYTES = 20000


def _parse_simple_yaml(text: str) -> dict:
    """Tiny YAML subset parser for flat MADR frontmatter.

    Handles: `key: value`, `key: [a, b]`, comments, blank lines.
    Strings are unquoted; values are stripped. Booleans and ints stay as strings.
    """
    out: dict = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        # Strip inline comments.
        if " #" in value:
            value = value.split(" #", 1)[0].strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            items = [item.strip() for item in inner.split(",")] if inner else []
            out[key] = [i for i in items if i]
        else:
            out[key] = value
    return out


def _extract_frontmatter(text: str) -> str | None:
    """Return the inner block between the first two `---` lines, or None."""
    if not text.startswith("---"):
        return None
    rest = text[3:]
    end = rest.find("\n---")
    if end == -1:
        return None
    inner = rest[:end]
    return inner.lstrip("\n")


def main() -> int:
    if not ADR_PATH.exists():
        print(f"FAIL: ADR not found at {ADR_PATH}")
        return 10

    body = ADR_PATH.read_text(encoding="utf-8")
    size = len(body.encode("utf-8"))
    if not (SIZE_MIN_BYTES <= size <= SIZE_MAX_BYTES):
        print(f"FAIL: ADR size {size} bytes out of range [{SIZE_MIN_BYTES},{SIZE_MAX_BYTES}]")
        return 11

    fm_text = _extract_frontmatter(body)
    if fm_text is None:
        print("FAIL: missing YAML frontmatter (file did not start with `---` block)")
        return 12

    # Try PyYAML first; fall back to the tiny in-house parser.
    fm: dict
    try:
        import yaml  # type: ignore[import-not-found]
        fm = yaml.safe_load(fm_text) or {}
    except ImportError:
        fm = _parse_simple_yaml(fm_text)

    missing_keys = REQUIRED_FM_KEYS - set(fm.keys())
    if missing_keys:
        print(f"FAIL: frontmatter missing required keys: {sorted(missing_keys)}")
        return 13

    adr_id = fm.get("adr_id")
    # Accept either string "0001" or int 1 (PyYAML drops leading zeros) — both pin this ADR.
    adr_id_ok = (
        adr_id == "0001"
        or adr_id == 1
        or (isinstance(adr_id, str) and adr_id.lstrip("0") == "1")
    )
    if not adr_id_ok:
        print(f"FAIL: adr_id is {adr_id!r}, expected '0001' (or 1)")
        return 14

    missing_sections = []
    for section in REQUIRED_SECTIONS:
        pattern = rf"^{re.escape(section)}\b"
        if not re.search(pattern, body, re.MULTILINE):
            missing_sections.append(section)
    if missing_sections:
        print(f"FAIL: missing H2 sections: {missing_sections}")
        return 15

    if REQUIRED_SUBSECTION not in body:
        print(f"FAIL: missing subsection: {REQUIRED_SUBSECTION}")
        return 16

    uncited = [p for p in CITED_ARTIFACTS if p not in body]
    if uncited:
        print(f"FAIL: cited artifacts not referenced in body: {uncited}")
        return 17

    print(
        f"PASS: ADR shape OK "
        f"(size={size} bytes, sections={len(REQUIRED_SECTIONS)}, "
        f"citations={len(CITED_ARTIFACTS)})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
