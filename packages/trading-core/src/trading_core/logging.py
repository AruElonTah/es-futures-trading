"""structlog setup with correlation IDs + Windows-safe UTF-8 reconfigure (FND-09).

Why Windows UTF-8 reconfigure runs first:
    On Windows, sys.stdout / sys.stderr default to cp1252 when output is
    piped (e.g., `... > log.txt`, task scheduler). A single log line
    containing a non-Latin-1 character (en-dash, smart quote, JSON
    Unicode literal) raises UnicodeEncodeError, which crashes the
    asyncio task group. The reconfigure happens BEFORE any handler is
    constructed so the very first log line is safe.

Why concurrent_log_handler.ConcurrentRotatingFileHandler:
    logging.handlers.WatchedFileHandler cannot rotate open files on
    Windows. concurrent-log-handler is designed cross-platform.
    See 01-RESEARCH.md §Anti-Patterns line 949 + Pitfall 5.

Why two handlers (file + console):
    The file is the audit log (JSON, FND-09). stderr is the dev console.
    Both share the same processor chain via structlog's
    ProcessorFormatter wrapper.

Correlation IDs:
    `correlation_id` and `signal_id` ContextVars are injected into every
    record by `_add_context`. Phase 3 wires `signal_id = uuid7()` at
    signal emission; downstream risk decisions / fills inherit it.
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from pathlib import Path

import structlog
from concurrent_log_handler import ConcurrentRotatingFileHandler

# Module-level ContextVars are the canonical correlation surface.
correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
signal_id: ContextVar[str | None] = ContextVar("signal_id", default=None)

# Sentinel attribute on the root logger to detect prior setup_logging() calls
# without relying on handler-name matching (idempotency requirement).
_SETUP_FLAG = "_trading_core_logging_setup_done"


def _add_context(logger, method_name, event_dict):
    """Inject correlation_id / signal_id contextvars into every record."""

    if cid := correlation_id.get():
        event_dict["correlation_id"] = cid
    if sid := signal_id.get():
        event_dict["signal_id"] = sid
    return event_dict


def setup_logging(audit_dir: Path) -> None:
    """Configure structlog for stderr (dev) and rotating JSONL audit log.

    Safe to call multiple times — second-and-later calls reset to a clean
    handler list (no duplication).
    """

    # CRITICAL: defensive UTF-8 reconfigure FIRST — every script entry that
    # may run with piped stdout must do this before any log line is emitted.
    # See 01-RESEARCH.md Pitfall 5 (Windows cp1252 trap).
    encoding = getattr(sys.stdout, "encoding", "") or ""
    if encoding.lower() != "utf-8":
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    audit_dir.mkdir(parents=True, exist_ok=True)

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        _add_context,
        structlog.processors.add_log_level,
        timestamper,
    ]

    # Cross-platform rotating JSONL file. 50 MB / 20 backups / utf-8 / Windows-safe.
    file_handler = ConcurrentRotatingFileHandler(
        filename=str(audit_dir / "audit.jsonl"),
        maxBytes=50 * 1024 * 1024,
        backupCount=20,
        encoding="utf-8",
    )
    file_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=shared_processors,
        )
    )

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            # colors=False — Windows console renders ANSI escapes as literal text
            # under cp1252 historically. ConsoleRenderer with colors disabled is
            # the safe default for both Win + POSIX redirected runs.
            processor=structlog.dev.ConsoleRenderer(colors=False),
            foreign_pre_chain=shared_processors,
        )
    )

    root = logging.getLogger()
    # Replace any existing handlers — idempotent setup (a second call does NOT
    # duplicate the handler list).
    for h in list(root.handlers):
        root.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass
    root.handlers = [file_handler, console_handler]
    root.setLevel(logging.INFO)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    setattr(root, _SETUP_FLAG, True)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger. Thin wrapper for import-site clarity."""

    return structlog.get_logger(name)
