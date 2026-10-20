"""Top-level demo orchestration tasks.

Four top-level commands compose the existing cluster / helm / bootstrap
pieces into a single happy-path experience:

    invoke build     # build the styrmin image
    invoke start     # create + provision everything
    invoke stop      # pause (preserve state)
    invoke destroy   # tear down
    invoke reset     # destroy + start

``invoke record`` then records the feature demos as MP4 videos on the running stack.

The Cloudflare wildcard zone *.local.styrmin.io resolves to 127.0.0.1,
so no /etc/hosts manipulation is needed.
"""

from __future__ import annotations

import shlex
import socket
import time
from pathlib import Path
from typing import Any

import yaml
from invoke import Context, task
from rich.console import Console
from rich.panel import Panel

from tasks import agent, cluster, dev

from .utils import (
    GARAGE_ACCESS_KEY_ID,
    GARAGE_SECRET_ACCESS_KEY,
    KUBERNETES_ROOT_NAMESPACE,
    MAIN_DIRECTORY_PATH,
    VCLUSTER_NAME,
    print_header,
)

DEMO_HOSTNAME = "styrmin.local.styrmin.io"
DEMO_FQDN_SUFFIX = "local.styrmin.io"
DEMO_RELEASE = "styrmin"
DEMO_IMAGE = agent.IMAGE_REF
DEMO_PORT = 8080
DEMO_VALUES = MAIN_DIRECTORY_PATH / "dev" / "local" / "demo-values.yaml"
HELM_STYRMIN_DIR = MAIN_DIRECTORY_PATH / "helm" / "styrmin"
PORT_FORWARD_PID_FILE = MAIN_DIRECTORY_PATH / ".vcluster" / "traefik.pid"
SEMAPHORE_DEMO_IMAGE = "styrmin-demo/semaphore:v2.16.47"
SEMAPHORE_DEMO_DIR = MAIN_DIRECTORY_PATH / "backend" / "tests" / "e2e" / "demos" / "semaphore"
DEMO_VIDEOS_DIR = MAIN_DIRECTORY_PATH / "demo-videos"


def _demo_url() -> str:
    return f"http://{DEMO_HOSTNAME}:{DEMO_PORT}"


def _image_exists(context: Context, image: str = DEMO_IMAGE) -> bool:
    result = context.run(f"docker image inspect {image}", warn=True, hide=True)
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
    raise RuntimeError(f"Timed out after {timeout:.0f}s waiting for {host}:{port} to accept connections")


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
        print_header(f"{DEMO_IMAGE} not found — building...")
        build(context)
    else:
        console.print(f"[green]✓[/green] Reusing existing image {DEMO_IMAGE} (pass --build-image to rebuild)")

    cluster.create(context)
    cluster.connect(context)
    cluster.traefik(context)
    cluster.garage(context)

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
    admin_username, admin_password = _admin_credentials()
    if admin_password.startswith("<"):
        msg = (
            "demo-values.yaml has no adminPassword set — the server will "
            "generate a random one and bootstrap login will fail. Set "
            "styrmin.adminPassword in dev/local/demo-values.yaml."
        )
        raise RuntimeError(msg)
    try:
        dev.bootstrap(
            context,
            api_url=f"{_demo_url()}/graphql",
            fqdn_suffix=DEMO_FQDN_SUFFIX,
            external_url_scheme="http",
            external_url_port=DEMO_PORT,
            admin_username=admin_username,
            admin_password=admin_password,
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


def build_semaphore_image(context: Context) -> None:
    """Build the demo Semaphore image with the Infrahub Ansible collection; it is never pushed (FR-015)."""
    print_header(f"Building {SEMAPHORE_DEMO_IMAGE}...")
    context.run(f"docker build -t {SEMAPHORE_DEMO_IMAGE} {SEMAPHORE_DEMO_DIR}", pty=True)


@task(
    help={
        "demo": "Record only this demo: deploy-upgrade, component-overrides, backup-restore or clone. "
        "Default: all four demos.",
        "output_dir": "Where to write the MP4 files. Default: demo-videos/ at the repository root.",
        "build_image": f"Rebuild {SEMAPHORE_DEMO_IMAGE} even if it already exists.",
    }
)
def record(context: Context, demo: str = "", output_dir: str = "", build_image: bool = False) -> None:
    """Record the feature demos as MP4 videos on the running demo stack."""
    if build_image or not _image_exists(context, SEMAPHORE_DEMO_IMAGE):
        build_semaphore_image(context)
    else:
        Console().print(
            f"[green]✓[/green] Reusing existing image {SEMAPHORE_DEMO_IMAGE} (pass --build-image to rebuild)"
        )
    target = Path(output_dir).resolve() if output_dir else DEMO_VIDEOS_DIR
    arguments = ["--output-dir", shlex.quote(str(target))]
    if demo:
        arguments += ["--demo", shlex.quote(demo)]
    username, password = _admin_credentials()
    # The password goes through the environment so it never shows in a command line or a log.
    environment = {
        "STYRMIN_DEMO_URL": _demo_url(),
        "STYRMIN_DEMO_USERNAME": username,
        "STYRMIN_DEMO_PASSWORD": password,
    }
    with context.cd(MAIN_DIRECTORY_PATH / "backend"):
        result = context.run(f"python -m tests.e2e.demos {' '.join(arguments)}", env=environment, pty=True, warn=True)
    if result is not None and result.exited != 0:
        raise SystemExit(result.exited)


def _admin_credentials() -> tuple[str, str]:
    """Read the admin username/password the demo will seed.

    Source of truth is ``demo-values.yaml`` — the same file Helm reads — so
    customising it keeps the printed summary in sync. An empty/unset
    ``adminPassword`` means the bootstrap routine will generate one and log
    it once at WARN level; surface that instead of inventing a value.
    """
    values: dict[str, Any] = yaml.safe_load(DEMO_VALUES.read_text()) or {}
    styrmin = values.get("styrmin") or {}
    username = styrmin.get("adminUsername") or "admin"
    password = styrmin.get("adminPassword") or "<generated — see server logs>"
    return username, password


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
    admin_username, admin_password = _admin_credentials()
    body = (
        f"[bold]Styrmin UI:[/bold]     {url}\n"
        f"[bold]GraphQL:[/bold]        {url}/graphql\n"
        f"[bold]Admin login:[/bold]    {admin_username} / {admin_password}\n"
        f"[bold]Garage S3:[/bold]      kubectl port-forward svc/garage 3900:3900 -n {KUBERNETES_ROOT_NAMESPACE}\n"
        f"[bold]Garage creds:[/bold]   {GARAGE_ACCESS_KEY_ID} / {GARAGE_SECRET_ACCESS_KEY}\n\n"
        f"[bold]Deployments:[/bold]\n{deploy_output}"
    )
    console.print(Panel(body, title="[bold green]Styrmin demo is ready", style="green"))
