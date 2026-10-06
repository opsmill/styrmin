"""Load GraphQL operations for the flow step reporter."""

from __future__ import annotations

from pathlib import Path

_GRAPHQL_DIR = Path(__file__).resolve().parent


def load_query(name: str) -> str:
    """Load a GraphQL operation from the agent/steps directory."""
    return (_GRAPHQL_DIR / f"{name}.graphql").read_text()
