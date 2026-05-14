"""Phase 0 spike — Twelve Data REST API probe.

PHASE 0 SPIKE — DO NOT IMPORT FROM PRODUCTION CODE.

Verifies whether Twelve Data covers ES futures and confirms SPY 1m availability for
the eventual secondary DataSource. Writes raw probe responses + rate-limit headers
to .planning/research/spike-0/twelvedata-probe.json. Plan 3's ADR cites this file
verbatim.

Per RESEARCH.md sections:
- "The 4 probe calls"
- "Concrete PowerShell + Python probe script"
- "Rate-limit headers"
- "Failure modes to capture"
- "SPY Backfill Rate-Limit Math"

Stdlib-only by design — pyproject.toml does not yet exist in this repo.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ENDPOINT_BASE = "https://api.twelvedata.com"
OUTPUT_PATH = Path(".planning/research/spike-0/twelvedata-probe.json")
PACE_SECONDS = 9.0  # free tier: 8 credits/min; 9s adds a safety margin
REDACTION_SENTINEL = "<TWELVEDATA_API_KEY>"
REQUEST_TIMEOUT_SECONDS = 30.0


def _load_env_file(path: Path) -> None:
    """Manually parse .env into os.environ (no python-dotenv dep).

    Honors any value the operator already exported in the shell session by only
    setting keys that are not already present in os.environ.
    """
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if key in os.environ:
            continue
        os.environ[key] = value


def _redact(url: str, api_key: str) -> str:
    """Replace every occurrence of the raw API key in `url` with the sentinel."""
    if not api_key:
        return url
    return url.replace(api_key, REDACTION_SENTINEL)


def _probe(name: str, url: str, api_key: str) -> dict:
    """Send a single GET. Capture headers + body verbatim. Never log the raw URL."""
    logged_url = _redact(url, api_key)
    record: dict = {
        "url": logged_url,
        "http_status": None,
        "headers": {"api-credits-used": None, "api-credits-left": None},
        "body": None,
    }
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            record["http_status"] = response.status
            record["headers"]["api-credits-used"] = response.headers.get("api-credits-used")
            record["headers"]["api-credits-left"] = response.headers.get("api-credits-left")
            body_text = response.read().decode("utf-8")
            try:
                record["body"] = json.loads(body_text)
            except json.JSONDecodeError:
                record["body"] = {"_raw_non_json": body_text}
    except urllib.error.HTTPError as e:
        record["http_status"] = e.code
        record["headers"]["api-credits-used"] = e.headers.get("api-credits-used") if e.headers else None
        record["headers"]["api-credits-left"] = e.headers.get("api-credits-left") if e.headers else None
        try:
            error_text = e.read().decode("utf-8", errors="replace")
        except Exception:
            error_text = ""
        record["error"] = error_text
        if e.code == 429:
            # Per RESEARCH.md Common Pitfall #2: do NOT silently retry on 429.
            # Surface this to the operator so "rate-limited" is not confused with
            # "feature unavailable".
            sys.exit(f"rate-limited (HTTP 429) on probe {name} — wait 60s and re-run")
    except urllib.error.URLError as e:
        record["http_status"] = None
        record["error"] = f"URLError: {e.reason}"
    except Exception as e:  # network anomaly
        record["http_status"] = None
        record["error"] = f"Exception: {type(e).__name__}: {e}"
    return record


def main() -> int:
    _load_env_file(Path(".env"))
    api_key = os.environ.get("TWELVEDATA_API_KEY", "").strip()
    if not api_key:
        sys.exit("ERROR: set TWELVEDATA_API_KEY in .env or environment before running")

    # The 4 probes from RESEARCH.md §"The 4 probe calls". apikey is appended to
    # every URL for consistency, but always passes through _redact() before logging.
    probes = [
        ("stocks_ES",      f"{ENDPOINT_BASE}/stocks?symbol=ES&apikey={api_key}"),
        ("commodities_ES", f"{ENDPOINT_BASE}/commodities?symbol=ES&apikey={api_key}"),
        ("etf_SPY",        f"{ENDPOINT_BASE}/etf?symbol=SPY&apikey={api_key}"),
        ("timeseries_SPY", f"{ENDPOINT_BASE}/time_series?symbol=SPY&interval=1min&outputsize=5&apikey={api_key}"),
    ]

    results: dict = {
        "probed_at_utc": datetime.now(timezone.utc).isoformat(),
        "twelvedata_endpoint_base": ENDPOINT_BASE,
        "probes": {},
    }

    for i, (name, url) in enumerate(probes):
        if i > 0:
            time.sleep(PACE_SECONDS)  # free-tier 8 credits/min pacing
        results["probes"][name] = _probe(name, url, api_key)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(results, indent=2, sort_keys=False),
        encoding="utf-8",
    )

    print(f"wrote {OUTPUT_PATH}")
    for name in ("stocks_ES", "commodities_ES", "etf_SPY", "timeseries_SPY"):
        rec = results["probes"][name]
        body = rec.get("body") or {}
        body_status = body.get("status") if isinstance(body, dict) else "n/a"
        headers = rec["headers"]
        print(
            f"{name}: http={rec['http_status']} "
            f"credits_used={headers['api-credits-used']} "
            f"credits_left={headers['api-credits-left']} "
            f"status={body_status}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
