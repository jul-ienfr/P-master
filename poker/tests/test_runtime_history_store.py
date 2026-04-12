"""Compatibility shim for the canonical runtime history tests.

The real pytest coverage lives in ``tests/test_runtime_history_store.py``.
This module stays importable for older tooling that references the historical
``poker.tests`` path, but it intentionally defines no local tests to avoid
divergence between two copies.
"""

from tests.test_runtime_history_store import *  # noqa: F401,F403

__test__ = False
