"""es-api: FastAPI app and WebSocket fan-out (Phase 3+ ships the routes).

Re-exports ``app`` from :mod:`api.app` so ``uvicorn api:app`` works as a
shorthand for ``uvicorn api.app:app`` from the repo root.
"""

from api.app import app

__all__ = ["app"]
