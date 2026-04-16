"""Load GraphQL operations for the agent status reporter."""

from __future__ import annotations

from pathlib import Path

_GRAPHQL_DIR = Path(__file__).resolve().parent


def load_query(name: str) -> str:
    """Load a GraphQL query from the agent/status directory."""
    return (_GRAPHQL_DIR / f"{name}.graphql").read_text()
