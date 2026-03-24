import json
import urllib.error
import urllib.request
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

KIND_CLUSTER_NAME = "styrmin"
KUBERNETES_ROOT_NAMESPACE = "styrmin"
MAIN_DIRECTORY_PATH = Path(__file__).parent.parent
TASKS_DIRECTORY_PATH = Path(__file__).parent
BACKEND_DIRECTORY = "backend"
GRAPHQL_DIR = MAIN_DIRECTORY_PATH / "tasks" / "graphql"


def print_header(message: str) -> str:
    console = Console()
    console.print(
        Panel(
            "[bold green]▶[/bold green] " + message,
            style="bold yellow",
        )
    )
    return message


def load_query(name: str) -> str:
    """Load a GraphQL query from tasks/graphql/<name>.graphql."""
    return (GRAPHQL_DIR / f"{name}.graphql").read_text()


def graphql(url: str, query: str, variables: dict) -> dict:  # type: ignore[type-arg]
    """Send a GraphQL request and return the parsed response body."""
    payload = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})  # noqa: S310
    try:
        with urllib.request.urlopen(req) as response:  # noqa: S310
            return json.loads(response.read())  # type: ignore[no-any-return]
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        raise RuntimeError(f"GraphQL request failed ({exc.code}): {body}") from exc
