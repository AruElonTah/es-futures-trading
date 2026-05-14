"""structlog setup tests — FND-09.

Plan 01-02 / Task 3. Behaviors:
- setup_logging(audit_dir) creates the dir.
- correlation_id contextvar threaded into the JSON record.
- Calling setup_logging twice does not duplicate handlers.
- JSON output contains `level` and `timestamp` (iso, UTC).
- The function reconfigures stdout/stderr to UTF-8 errors=replace.
"""

from __future__ import annotations

import io
import json
import logging
import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _reset_root_logger():
    """Reset the stdlib root logger between tests — setup_logging mutates it."""

    yield
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass
    root.setLevel(logging.WARNING)


def test_setup_logging_creates_audit_dir(tmp_path: Path):
    from trading_core.logging import setup_logging

    audit_dir = tmp_path / "subdir" / "audit"
    assert not audit_dir.exists()
    setup_logging(audit_dir)
    assert audit_dir.exists()


def test_setup_logging_idempotent_handlers(tmp_path: Path):
    from trading_core.logging import setup_logging

    setup_logging(tmp_path / "audit")
    n1 = len(logging.getLogger().handlers)
    setup_logging(tmp_path / "audit")
    n2 = len(logging.getLogger().handlers)
    assert n1 == n2, f"second setup_logging duplicated handlers: {n1} -> {n2}"


def test_log_record_contains_correlation_id(tmp_path: Path, capsys):
    from trading_core.logging import correlation_id, get_logger, setup_logging

    audit_dir = tmp_path / "audit"
    setup_logging(audit_dir)

    token = correlation_id.set("abc-123")
    try:
        log = get_logger("test")
        log.info("a_test_event")
    finally:
        correlation_id.reset(token)

    # Flush handlers so the audit file is written.
    for h in logging.getLogger().handlers:
        h.flush()

    audit_file = audit_dir / "audit.jsonl"
    assert audit_file.exists()
    content = audit_file.read_text(encoding="utf-8")
    # The JSON record on disk should contain the correlation_id.
    assert "abc-123" in content
    # Parse the last non-empty line as JSON and check structure.
    lines = [ln for ln in content.splitlines() if ln.strip()]
    assert lines, "no log lines written to audit.jsonl"
    record = json.loads(lines[-1])
    assert record.get("correlation_id") == "abc-123"
    assert record.get("event") == "a_test_event"


def test_log_record_has_level_and_timestamp(tmp_path: Path):
    from trading_core.logging import get_logger, setup_logging

    audit_dir = tmp_path / "audit"
    setup_logging(audit_dir)
    log = get_logger("test")
    log.info("a_basic_event")

    for h in logging.getLogger().handlers:
        h.flush()

    audit_file = audit_dir / "audit.jsonl"
    lines = [ln for ln in audit_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    record = json.loads(lines[-1])
    assert "level" in record
    assert "timestamp" in record
    # ISO + UTC marker (TimeStamper(fmt='iso', utc=True) appends 'Z' or '+00:00').
    ts = record["timestamp"]
    assert ts.endswith("Z") or "+00:00" in ts


def test_stdout_reconfigure_called_on_non_utf8(tmp_path: Path, monkeypatch):
    """When stdout.encoding is not utf-8, setup_logging must reconfigure it.

    We can't easily fake the encoding pre-call on real sys.stdout, so we patch
    sys.stdout to a stub that records reconfigure() invocations.
    """

    class FakeStream:
        def __init__(self, encoding: str):
            self.encoding = encoding
            self.reconfigured_to: dict | None = None

        def reconfigure(self, **kwargs):
            self.reconfigured_to = kwargs

        def write(self, *a, **kw):
            pass

        def flush(self):
            pass

    fake_stdout = FakeStream("cp1252")
    fake_stderr = FakeStream("cp1252")
    monkeypatch.setattr(sys, "stdout", fake_stdout)
    monkeypatch.setattr(sys, "stderr", fake_stderr)

    from trading_core.logging import setup_logging

    setup_logging(tmp_path / "audit")
    assert fake_stdout.reconfigured_to == {"encoding": "utf-8", "errors": "replace"}
    assert fake_stderr.reconfigured_to == {"encoding": "utf-8", "errors": "replace"}


def test_stdout_no_reconfigure_when_already_utf8(tmp_path: Path, monkeypatch):
    """When stdout.encoding is already utf-8, setup_logging skips reconfigure."""

    class FakeStream:
        def __init__(self, encoding: str):
            self.encoding = encoding
            self.reconfigured_to: dict | None = None

        def reconfigure(self, **kwargs):
            self.reconfigured_to = kwargs

        def write(self, *a, **kw):
            pass

        def flush(self):
            pass

    fake_stdout = FakeStream("utf-8")
    fake_stderr = FakeStream("utf-8")
    monkeypatch.setattr(sys, "stdout", fake_stdout)
    monkeypatch.setattr(sys, "stderr", fake_stderr)

    from trading_core.logging import setup_logging

    setup_logging(tmp_path / "audit")
    assert fake_stdout.reconfigured_to is None
    assert fake_stderr.reconfigured_to is None
