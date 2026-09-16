import json
import urllib.error
import urllib.request
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

VCLUSTER_NAME = "styrmin"
KUBERNETES_ROOT_NAMESPACE = "styrmin"
MAIN_DIRECTORY_PATH = Path(__file__).parent.parent
TASKS_DIRECTORY_PATH = Path(__file__).parent
BACKEND_DIRECTORY = "backend"
GRAPHQL_DIR = MAIN_DIRECTORY_PATH / "tasks" / "graphql"

# In-cluster Garage, the S3-compatible store Velero writes local backups to.
# These match dev/local/garage.yaml and are demo values, not secrets.
GARAGE_ENDPOINT = f"http://garage.{KUBERNETES_ROOT_NAMESPACE}.svc:3900"
GARAGE_BUCKET = "velero"
GARAGE_REGION = "garage"
GARAGE_ACCESS_KEY_ID = "GKdeadbeefdeadbeefdeadbeef"
GARAGE_SECRET_ACCESS_KEY = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"  # noqa: S105


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


def graphql(
    url: str,
    query: str,
    variables: dict,  # type: ignore[type-arg]
    token: str | None = None,
) -> dict:  # type: ignore[type-arg]
    """Send a GraphQL request and return the parsed response body.

    When ``token`` is provided it is sent as ``Authorization: Bearer
    <token>``; the server's auth middleware accepts this transport for
    SDK / script callers (see ADR-016).
    """
    payload = json.dumps({"query": query, "variables": variables}).encode()
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=payload, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(req) as response:  # noqa: S310
            return json.loads(response.read())  # type: ignore[no-any-return]
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        raise RuntimeError(f"GraphQL request failed ({exc.code}): {body}") from exc
