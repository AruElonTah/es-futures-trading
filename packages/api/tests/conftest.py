# Plan 01-04+ will import shared fixtures from trading_core.tests via pytest_plugins.
#
# Note: under pytest --import-mode=importlib + no tests/__init__.py (Plan 01-01
# decision #1), `pytest_plugins = ["trading_core.tests.conftest"]` does NOT
# work — trading_core.tests is not an importable Python package. The api tests
# do not currently need any shared fixtures (test_health.py uses TestClient
# directly), so this conftest stays empty for Phase 1. Phase 3 can use the
# `importmode=importlib` sys.path trick (prepending packages/trading-core/tests
# to sys.path) if/when shared fixtures are actually needed.
