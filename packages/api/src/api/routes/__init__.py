"""API route modules — bars, backtests.

Each sub-module exposes an ``APIRouter`` instance imported by app.py via
``include_router``. No public exports are needed here; the sub-modules are
accessed as ``from api.routes import bars, backtests``.
"""
