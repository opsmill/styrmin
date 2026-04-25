"""Top-level demo orchestration tasks.

Four top-level commands compose the existing cluster / helm / bootstrap
pieces into a single happy-path experience:

    invoke build     # build the styrmin image
    invoke start     # create + provision everything
    invoke stop      # pause (preserve state)
    invoke destroy   # tear down
    invoke reset     # destroy + start

The Cloudflare wildcard zone *.local.styrmin.io resolves to 127.0.0.1,
so no /etc/hosts manipulation is needed.
"""

from __future__ import annotations

import socket
import time

from invoke import Context, task
from rich.console import Console
from rich.panel import Panel

from tasks import agent, cluster, dev

from .utils import KUBERNETES_ROOT_NAMESPACE, MAIN_DIRECTORY_PATH, VCLUSTER_NAME, print_header

DEMO_HOSTNAME = "styrmin.local.styrmin.io"
DEMO_FQDN_SUFFIX = "local.styrmin.io"
DEMO_RELEASE = "styrmin"
DEMO_IMAGE = "styrmin:latest"
DEMO_PORT = 8080
DEMO_VALUES = MAIN_DIRECTORY_PATH / "dev" / "local" / "demo-values.yaml"
HELM_STYRMIN_DIR = MAIN_DIRECTORY_PATH / "helm" / "styrmin"
PORT_FORWARD_PID_FILE = MAIN_DIRECTORY_PATH / ".vcluster" / "traefik.pid"


def _demo_url() -> str:
    return f"http://{DEMO_HOSTNAME}:{DEMO_PORT}"


def _image_exists(context: Context) -> bool:
    result = context.run(f"docker image inspect {DEMO_IMAGE}", warn=True, hide=True)
    return result is not None and result.ok


def _start_traefik_port_forward(context: Context) -> None:
    """Start a backgrounded `kubectl port-forward` for Traefik.

    Used uniformly on Linux and macOS so the demo flow is identical
    across platforms (no reliance on vCluster's embedded LB provider).
    Port 8080 is used because 80 is privileged.
    Stops any previous port-forward recorded in the PID file first.

    Blocks until the local port is actually listening so callers can
    issue requests without racing kubectl's startup.
    """
    _stop_traefik_port_forward(context)
    PORT_FORWARD_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    print_header(f"Starting Traefik port-forward ({DEMO_PORT}:80)...")
    context.run(
        f"nohup kubectl port-forward svc/traefik {DEMO_PORT}:80"
        f" -n {KUBERNETES_ROOT_NAMESPACE}"
        f" > /tmp/styrmin-traefik-portforward.log 2>&1 &"
        f" echo $! > {PORT_FORWARD_PID_FILE}",
        pty=False,
    )
    _wait_for_port(DEMO_PORT)


def _wait_for_port(port: int, host: str = "127.0.0.1", timeout: float = 30.0) -> None:
    """Block until *host:port* accepts a TCP connection or *timeout* elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(
        f"Timed out after {timeout:.0f}s waiting for {host}:{port} to accept connections"
    )


def _stop_traefik_port_forward(context: Context) -> None:
    if not PORT_FORWARD_PID_FILE.exists():
        return
    pid = PORT_FORWARD_PID_FILE.read_text().strip()
    if pid:
        context.run(f"kill {pid} 2>/dev/null || true", warn=True, hide=True)
    PORT_FORWARD_PID_FILE.unlink(missing_ok=True)


@task
def build(context: Context) -> None:
    """Build the container image and Helm dependencies needed for the demo."""
    agent.build_image(context)
    print_header("Updating helm/agent dependencies...")
    with context.cd("helm/agent"):
        context.run("helm dependency update", pty=True)
    print_header("Updating helm/styrmin dependencies...")
    with context.cd("helm/styrmin"):
        context.run("helm dependency update", pty=True)


@task(help={"build_image": "Force a rebuild of the styrmin image even if it already exists."})
def start(context: Context, build_image: bool = False) -> None:
    """Create the vCluster and deploy a working Styrmin demo end-to-end."""
    console = Console()

    if build_image or not _image_exists(context):
        print_header("styrmin:latest not found — building...")
        build(context)
    else:
        console.print(f"[green]✓[/green] Reusing existing image {DEMO_IMAGE} (pass --build-image to rebuild)")

    cluster.create(context)
    cluster.connect(context)
    cluster.traefik(context)
    cluster.minio(context)

    print_header(f"Deploying the Styrmin Helm chart (release={DEMO_RELEASE})...")
    context.run(
        f"helm upgrade --install {DEMO_RELEASE} {HELM_STYRMIN_DIR}"
        f" -n {KUBERNETES_ROOT_NAMESPACE} --create-namespace"
        f" -f {DEMO_VALUES}"
        f" --wait --timeout 10m",
        pty=True,
    )

    _start_traefik_port_forward(context)

    print_header("Waiting for the Styrmin server to be ready...")
    context.run(
        f"kubectl rollout status deployment/{DEMO_RELEASE}-server -n {KUBERNETES_ROOT_NAMESPACE} --timeout=300s",
        pty=True,
    )

    print_header("Bootstrapping cluster, environment, and local driver...")
    try:
        dev.bootstrap(
            context,
            api_url=f"{_demo_url()}/graphql",
            fqdn_suffix=DEMO_FQDN_SUFFIX,
            external_url_scheme="http",
            external_url_port=DEMO_PORT,
        )
    except SystemExit as exc:
        console.print(f"[yellow]⚠[/yellow] Bootstrap skipped (already initialized): {exc}")

    _print_summary(context)


@task
def stop(context: Context) -> None:
    """Pause the demo environment (preserves state)."""
    _stop_traefik_port_forward(context)
    print_header(f"Pausing the {VCLUSTER_NAME} cluster...")
    context.run(f"vcluster pause {VCLUSTER_NAME} --driver=docker", pty=True, warn=True)


@task(help={"yes": "Skip the confirmation prompt."})
def destroy(context: Context, yes: bool = False) -> None:
    """Tear down the demo environment."""
    if not yes:
        console = Console()
        console.print(f"[yellow]This will delete the '{VCLUSTER_NAME}' vCluster and all associated data.[/yellow]")
        answer = input("Continue? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            console.print("Aborted.")
            return
    _stop_traefik_port_forward(context)
    cluster.delete(context)


@task
def reset(context: Context) -> None:
    """Destroy and re-create the demo environment from scratch."""
    destroy(context, yes=True)
    start(context)


def _print_summary(context: Context) -> None:
    """Print the final summary panel with URLs and component status."""
    console = Console()
    url = _demo_url()
    deployments = context.run(
        f"kubectl get deploy -n {KUBERNETES_ROOT_NAMESPACE} --no-headers",
        hide=True,
        warn=True,
    )
    deploy_output = deployments.stdout if deployments and deployments.ok else "(unavailable)"
    body = (
        f"[bold]Styrmin UI:[/bold]     {url}\n"
        f"[bold]GraphQL:[/bold]        {url}/graphql\n"
        f"[bold]MinIO console:[/bold]  kubectl port-forward svc/minio 9001:9001 -n {KUBERNETES_ROOT_NAMESPACE}\n"
        f"[bold]MinIO creds:[/bold]    minioadmin / minioadmin\n\n"
        f"[bold]Deployments:[/bold]\n{deploy_output}"
    )
    console.print(Panel(body, title="[bold green]Styrmin demo is ready", style="green"))
