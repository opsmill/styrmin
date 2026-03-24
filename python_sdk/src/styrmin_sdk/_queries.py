from pathlib import Path

_GRAPHQL_DIR = Path(__file__).parent / "graphql"


def load_query(name: str) -> str:
    """Load a GraphQL query from styrmin_sdk/graphql/<name>.graphql."""
    return (_GRAPHQL_DIR / f"{name}.graphql").read_text()
