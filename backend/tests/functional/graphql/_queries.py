"""Loader for functional-test GraphQL operation files.

Per project policy (Constitution §V + dev/guides/graphql-propagation-tests.md),
GraphQL operation strings used by these tests MUST live in dedicated
``.graphql`` files under ``backend/tests/functional/graphql/operations/`` and
be loaded via this helper. Inline GraphQL strings in test modules are not
allowed — they bypass ``uv run invoke validate-graphql`` and let schema drift
go undetected.

Add a new operation by creating ``<operation_name>.graphql`` (snake_case) in
the ``operations/`` subdirectory next to this file, then
``load_query("<operation_name>")`` in the test module. ``validate-graphql``
discovers the file automatically via ``rglob`` and will fail CI if the
operation no longer matches the schema.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_GRAPHQL_DIR = Path(__file__).parent / "operations"


@lru_cache(maxsize=None)
def load_query(name: str) -> str:
    """Load a GraphQL operation by snake_case file stem.

    Raises ``FileNotFoundError`` if no matching file exists — callers should
    fix the typo or add the missing ``.graphql`` file rather than catching.
    """

    path = _GRAPHQL_DIR / f"{name}.graphql"
    return path.read_text()
