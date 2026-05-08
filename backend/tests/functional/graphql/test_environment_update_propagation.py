"""GraphQL ↔ DB propagation tests for ``updateEnvironment`` fanout (009).

Phase-1 placeholder so the file is wired into pytest collection. Real
fanout-dispatch + mutation-result coupling tests land in T022/T023/T024.
The imports below mirror ``test_env_vars_propagation.py`` (008) to lock
the convention before the real tests fill in.
"""

from __future__ import annotations

from ._queries import load_query
from .conftest import gql

__all__ = ["gql", "load_query"]


def test_placeholder() -> None:
    """Placeholder so pytest collects this file before T022+ land."""
    assert True
